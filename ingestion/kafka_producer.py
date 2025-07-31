"""
IQFeed to Kafka Producer

Following PROJECT_ROADMAP.md Phase 2.2: Real-time data streaming with robust error handling
Following RULES.md: Structured error handling, loud failures, real data only

Streams IQFeed market data to Kafka topics with guaranteed delivery and monitoring.
NO MOCKS - Only real Kafka connections and IQFeed data.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
import os
from dotenv import load_dotenv

from kafka import KafkaProducer
from kafka.errors import KafkaError, KafkaTimeoutError, KafkaConnectionError

from .iqfeed_client import IQFeedClient
from .exceptions import (
    KafkaPublishingError,
    DataValidationError,
    ProcessingError
)

# Load environment variables
load_dotenv()

# Configure logging for loud failures
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Message type enumeration for Kafka topics."""
    L2_ORDER_BOOK = "l2_order_book"
    TRADES = "trades"
    QUOTES = "quotes"
    HEARTBEAT = "heartbeat"


@dataclass
class PublishResult:
    """Result of Kafka message publishing."""
    success: bool
    topic: str
    partition: Optional[int] = None
    offset: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class ProducerStatistics:
    """Producer performance statistics."""
    messages_sent: int = 0
    messages_failed: int = 0
    bytes_sent: int = 0
    l2_messages: int = 0
    trade_messages: int = 0
    quote_messages: int = 0
    last_message_time: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = self.messages_sent + self.messages_failed
        return self.messages_sent / total if total > 0 else 0.0


class IQFeedKafkaProducer:
    """
    Produces IQFeed market data to Kafka topics.
    
    Implements high-throughput streaming with guaranteed delivery
    as specified in PROJECT_ROADMAP.md Phase 2.2.
    """
    
    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        iqfeed_host: Optional[str] = None,
        iqfeed_port: Optional[int] = None,
        message_handler: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize Kafka producer for IQFeed data.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            iqfeed_host: IQFeed host
            iqfeed_port: IQFeed port
            message_handler: Optional custom message handler
        """
        self.bootstrap_servers = bootstrap_servers or os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
        
        # Topic configuration matching infrastructure setup
        self.topics = {
            MessageType.L2_ORDER_BOOK: os.getenv('KAFKA_L2_TOPIC', 'iqfeed.l2.raw'),
            MessageType.TRADES: os.getenv('KAFKA_TRADES_TOPIC', 'iqfeed.trades.raw'),
            MessageType.QUOTES: os.getenv('KAFKA_QUOTES_TOPIC', 'iqfeed.quotes.raw'),
            MessageType.HEARTBEAT: os.getenv('KAFKA_HEARTBEAT_TOPIC', 'trading.heartbeat')
        }
        
        # Producer configuration optimized for high-throughput financial data
        self.producer_config = {
            'bootstrap_servers': self.bootstrap_servers,
            'key_serializer': lambda x: x.encode('utf-8') if x else None,
            'value_serializer': self._serialize_value,
            'acks': 'all',  # Wait for all replicas for guaranteed delivery
            'retries': 5,  # Increased retries for reliability
            'retry_backoff_ms': 100,  # Fast retry for low latency
            'max_in_flight_requests_per_connection': 5,  # Higher throughput while maintaining order per partition
            'compression_type': 'lz4',  # Faster compression for financial data
            'batch_size': 32768,  # Larger batches for higher throughput
            'linger_ms': 1,  # Lower latency for real-time data
            'buffer_memory': 67108864,  # 64MB buffer for high-throughput
            'request_timeout_ms': 30000,  # 30 second timeout
            'delivery_timeout_ms': 120000,  # 2 minute total delivery timeout
            'enable_idempotence': True,  # Enable idempotence for exactly-once semantics
        }
        
        # Initialize components
        self._producer: Optional[KafkaProducer] = None
        self._iqfeed_client = IQFeedClient(host=iqfeed_host, port=iqfeed_port)
        self._running = False
        self._producer_thread: Optional[threading.Thread] = None
        
        # Statistics and monitoring
        self._stats = ProducerStatistics()
        self._stats_lock = threading.Lock()
        self._last_heartbeat = datetime.now()
        
        # Message handling
        self._message_handler = message_handler or self._default_message_handler
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._max_buffer_size = int(os.getenv('PRODUCER_BUFFER_SIZE', '10000'))
        
        # Health monitoring
        self._last_successful_publish = datetime.now()
        self._consecutive_failures = 0
        self._max_consecutive_failures = int(os.getenv('PRODUCER_MAX_FAILURES', '10'))
        
        logger.info(f"IQFeed Kafka producer initialized (servers: {self.bootstrap_servers})")
    
    def start(self, symbols: List[str]) -> bool:
        """
        Start producing IQFeed data to Kafka.
        
        Args:
            symbols: List of symbols to subscribe to
            
        Returns:
            True if started successfully
            
        Raises:
            KafkaPublishingError: If startup fails
        """
        logger.info(f"Starting IQFeed Kafka producer for {len(symbols)} symbols")
        
        try:
            # Initialize Kafka producer
            self._producer = KafkaProducer(**self.producer_config)
            logger.info("Kafka producer created successfully")
            
            # Connect to IQFeed
            connection_result = self._iqfeed_client.connect()
            if not connection_result.success:
                raise KafkaPublishingError(
                    f"Failed to connect to IQFeed: {connection_result.error_message}",
                    "iqfeed_connection"
                )
            
            # Subscribe to symbols
            subscription_errors = []
            for symbol in symbols:
                # Subscribe to L2 data
                l2_result = self._iqfeed_client.subscribe_l2_data(symbol)
                if not l2_result.success:
                    subscription_errors.append(f"L2 subscription failed for {symbol}: {l2_result.error_message}")
                
                # Subscribe to trades
                trade_result = self._iqfeed_client.subscribe_trades(symbol)
                if not trade_result.success:
                    subscription_errors.append(f"Trade subscription failed for {symbol}: {trade_result.error_message}")
            
            if subscription_errors:
                error_msg = "; ".join(subscription_errors)
                logger.warning(f"Some subscriptions failed: {error_msg}")
                # Continue if at least some subscriptions worked
            
            # Start producer thread
            self._running = True
            self._producer_thread = threading.Thread(target=self._produce_messages, daemon=True)
            self._producer_thread.start()
            
            logger.info("IQFeed Kafka producer started successfully")
            return True
            
        except KafkaPublishingError:
            # Re-raise KafkaPublishingError unchanged (preserves operation type)
            self.stop()
            raise
        except Exception as e:
            logger.error(f"Failed to start producer: {e}")
            self.stop()
            raise KafkaPublishingError(f"Producer startup failed: {e}", "startup")
    
    def stop(self):
        """Stop the producer and cleanup resources."""
        logger.info("Stopping IQFeed Kafka producer")
        
        self._running = False
        
        # Wait for producer thread to finish
        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=10.0)
        
        # Disconnect from IQFeed
        try:
            self._iqfeed_client.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting from IQFeed: {e}")
        
        # Close Kafka producer
        if self._producer:
            try:
                self._producer.flush(timeout=30)  # Wait for pending messages
                self._producer.close(timeout=30)
            except Exception as e:
                logger.warning(f"Error closing Kafka producer: {e}")
            finally:
                self._producer = None
        
        logger.info("IQFeed Kafka producer stopped")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get current producer statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._stats_lock:
            now = datetime.now()
            
            return {
                'messages_sent': self._stats.messages_sent,
                'messages_failed': self._stats.messages_failed,
                'bytes_sent': self._stats.bytes_sent,
                'success_rate': self._stats.success_rate,
                'l2_messages': self._stats.l2_messages,
                'trade_messages': self._stats.trade_messages,
                'quote_messages': self._stats.quote_messages,
                'last_message_time': self._stats.last_message_time.isoformat() if self._stats.last_message_time else None,
                'consecutive_failures': self._consecutive_failures,
                'buffer_size': len(self._message_buffer),
                'running': self._running,
                'iqfeed_connected': self._iqfeed_client.is_connected(),
                'uptime_seconds': (now - self._last_heartbeat).total_seconds() if self._running else 0
            }
    
    def publish_message(self, message: Dict[str, Any], message_type: MessageType) -> PublishResult:
        """
        Publish a single message to Kafka.
        
        Args:
            message: Message to publish
            message_type: Type of message for topic routing
            
        Returns:
            PublishResult with publishing status
        """
        if not self._producer:
            return PublishResult(
                success=False,
                topic="",
                error_message="Producer not initialized"
            )
        
        try:
            # Validate message
            self._validate_message(message, message_type)
            
            # Add metadata
            enriched_message = self._enrich_message(message, message_type)
            
            # Determine topic and key
            topic = self.topics[message_type]
            key = message.get('symbol', 'unknown')
            
            # Publish to Kafka
            future = self._producer.send(topic, value=enriched_message, key=key)
            record_metadata = future.get(timeout=10)  # Wait for ack
            
            # Update statistics
            with self._stats_lock:
                self._stats.messages_sent += 1
                self._stats.bytes_sent += len(json.dumps(enriched_message, default=self._json_serializer).encode('utf-8'))
                self._stats.last_message_time = datetime.now()
                
                if message_type == MessageType.L2_ORDER_BOOK:
                    self._stats.l2_messages += 1
                elif message_type == MessageType.TRADES:
                    self._stats.trade_messages += 1
                elif message_type == MessageType.QUOTES:
                    self._stats.quote_messages += 1
            
            self._consecutive_failures = 0
            self._last_successful_publish = datetime.now()
            
            return PublishResult(
                success=True,
                topic=topic,
                partition=record_metadata.partition,
                offset=record_metadata.offset,
                timestamp=datetime.fromtimestamp(record_metadata.timestamp / 1000.0)
            )
            
        except Exception as e:
            # Update failure statistics
            with self._stats_lock:
                self._stats.messages_failed += 1
                
            self._consecutive_failures += 1
            error_msg = f"Failed to publish message: {e}"
            logger.error(error_msg)
            
            # Check if we've exceeded failure threshold
            if self._consecutive_failures >= self._max_consecutive_failures:
                logger.error(f"Too many consecutive failures ({self._consecutive_failures}), stopping producer")
                self._running = False
            
            return PublishResult(
                success=False,
                topic=self.topics.get(message_type, "unknown"),
                error_message=error_msg
            )
    
    def _produce_messages(self):
        """Main producer loop - processes IQFeed messages and publishes to Kafka."""
        logger.info("Producer thread started")
        
        last_heartbeat = time.time()
        
        while self._running:
            try:
                # Get message from IQFeed
                message = self._iqfeed_client.get_next_message(timeout=1.0)
                
                if message:
                    # Process message through handler
                    self._message_handler(message)
                else:
                    # No message received - brief sleep to prevent CPU spinning
                    time.sleep(0.1)
                
                # Send heartbeat every 30 seconds
                now = time.time()
                if now - last_heartbeat >= 30:
                    self._send_heartbeat()
                    last_heartbeat = now
                
                # Process buffered messages if any
                self._process_message_buffer()
                
            except Exception as e:
                logger.error(f"Error in producer loop: {e}")
                if not self._running:
                    break
                time.sleep(1)  # Brief pause before retry
        
        logger.info("Producer thread stopped")
    
    def _default_message_handler(self, message: Dict[str, Any]):
        """Default message handler - routes messages to appropriate Kafka topics."""
        try:
            # Determine message type based on content
            if 'level' in message and 'operation' in message:
                # L2 order book message
                result = self.publish_message(message, MessageType.L2_ORDER_BOOK)
            elif 'trade_price' in message and 'trade_size' in message:
                # Trade message
                result = self.publish_message(message, MessageType.TRADES)
            elif 'bid_price' in message and 'ask_price' in message and 'trade_price' not in message:
                # Quote message
                result = self.publish_message(message, MessageType.QUOTES)
            else:
                # Unknown message type - log and skip
                logger.warning(f"Unknown message type, skipping: {message}")
                return
            
            if not result.success:
                logger.error(f"Failed to publish message: {result.error_message}")
                
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
    
    def _validate_message(self, message: Dict[str, Any], message_type: MessageType):
        """Validate message structure before publishing."""
        if not isinstance(message, dict):
            raise DataValidationError("Message must be a dictionary", message)
        
        # Check required fields based on message type
        required_fields = {
            MessageType.L2_ORDER_BOOK: ['symbol', 'timestamp'],  # Rich order book - just need basic fields
            MessageType.TRADES: ['symbol', 'timestamp', 'trade_price', 'trade_size'],
            MessageType.QUOTES: ['symbol', 'timestamp', 'bid_price', 'ask_price'],
            MessageType.HEARTBEAT: ['timestamp', 'producer_id']
        }
        
        if message_type in required_fields:
            for field in required_fields[message_type]:
                if field not in message:
                    raise DataValidationError(f"Missing required field: {field}", message)
    
    def _enrich_message(self, message: Dict[str, Any], message_type: MessageType) -> Dict[str, Any]:
        """Enrich message with metadata for Kafka."""
        enriched = message.copy()
        
        # Add producer metadata
        enriched['_metadata'] = {
            'producer_id': f"iqfeed_producer_{os.getpid()}",
            'message_type': message_type.value,
            'kafka_timestamp': datetime.now(timezone.utc).isoformat(),
            'schema_version': '1.0'
        }
        
        return enriched
    
    def _send_heartbeat(self):
        """Send heartbeat message to monitor producer health."""
        try:
            heartbeat_msg = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'producer_id': f"iqfeed_producer_{os.getpid()}",
                'statistics': self.get_statistics()
            }
            
            self.publish_message(heartbeat_msg, MessageType.HEARTBEAT)
            
        except Exception as e:
            logger.warning(f"Failed to send heartbeat: {e}")
    
    def _process_message_buffer(self):
        """Process any buffered messages."""
        with self._buffer_lock:
            if not self._message_buffer:
                return
            
            # Process up to 100 messages at a time
            batch = self._message_buffer[:100]
            self._message_buffer = self._message_buffer[100:]
        
        for buffered_message in batch:
            try:
                self._message_handler(buffered_message)
            except Exception as e:
                logger.error(f"Error processing buffered message: {e}")
    
    def _serialize_value(self, x):
        """Optimized serialization for financial data messages."""
        return json.dumps(x, default=self._json_serializer, separators=(',', ':')).encode('utf-8')
    
    def _json_serializer(self, obj):
        """Custom JSON serializer optimized for financial data types."""
        if isinstance(obj, datetime):
            # Use more efficient timestamp format for financial data
            return obj.timestamp()
        elif hasattr(obj, '__float__'):
            # Handle numpy types and Decimal for financial precision
            return float(obj)
        elif hasattr(obj, '__int__'):
            # Handle numpy int types
            return int(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    
    def is_healthy(self) -> bool:
        """Check if producer is healthy."""
        if not self._running:
            return False
        
        # Check if we've had recent successful publishes
        time_since_success = (datetime.now() - self._last_successful_publish).total_seconds()
        if time_since_success > 300:  # 5 minutes
            return False
        
        # Check consecutive failures
        if self._consecutive_failures >= self._max_consecutive_failures:
            return False
        
        # Check IQFeed connection
        if not self._iqfeed_client.is_connected():
            return False
        
        return True