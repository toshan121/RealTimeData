"""
Kafka Consumer for Market Data Processing

Following PROJECT_ROADMAP.md Phase 2.3: Real-time data consumption with robust error handling
Following RULES.md: Structured error handling, loud failures, real data only

Consumes market data from Kafka topics with guaranteed processing and monitoring.
NO MOCKS - Only real Kafka connections and market data.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable, Set
from dataclasses import dataclass
from enum import Enum
import os
from dotenv import load_dotenv

from kafka import KafkaConsumer, TopicPartition
from kafka.errors import KafkaError, KafkaTimeoutError, CommitFailedError

from ingestion.exceptions import (
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


class ConsumerState(Enum):
    """Consumer state enumeration."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ConsumedMessage:
    """Consumed message from Kafka."""
    topic: str
    partition: int
    offset: int
    key: Optional[str]
    value: Dict[str, Any]
    timestamp: datetime
    symbol: str
    message_type: str
    headers: Optional[Dict[str, str]] = None


@dataclass
class ConsumerStatistics:
    """Consumer performance statistics."""
    messages_consumed: int = 0
    messages_processed: int = 0
    messages_failed: int = 0
    bytes_consumed: int = 0
    l2_messages: int = 0
    trade_messages: int = 0
    quote_messages: int = 0
    last_message_time: Optional[datetime] = None
    
    @property
    def processing_success_rate(self) -> float:
        """Calculate processing success rate as percentage."""
        total = self.messages_processed + self.messages_failed
        return self.messages_processed / total if total > 0 else 0.0


class MarketDataConsumer:
    """
    Consumes market data from Kafka topics.
    
    Implements high-throughput processing with guaranteed delivery
    as specified in PROJECT_ROADMAP.md Phase 2.3.
    """
    
    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        group_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        auto_offset_reset: str = 'latest'
    ):
        """
        Initialize Kafka consumer for market data.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            group_id: Consumer group ID
            topics: List of topics to consume from
            auto_offset_reset: Offset reset policy
        """
        self.bootstrap_servers = bootstrap_servers or os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
        self.group_id = group_id or os.getenv('KAFKA_CONSUMER_GROUP', 'market_data_consumer')
        self.topics = topics or [
            os.getenv('KAFKA_L2_TOPIC', 'iqfeed.l2.raw'),
            os.getenv('KAFKA_TRADES_TOPIC', 'iqfeed.trades.raw'),
            os.getenv('KAFKA_QUOTES_TOPIC', 'iqfeed.quotes.raw')
        ]
        
        # Consumer configuration optimized for financial data
        self.consumer_config = {
            'bootstrap_servers': self.bootstrap_servers,
            'group_id': self.group_id,
            'auto_offset_reset': auto_offset_reset,
            'enable_auto_commit': False,  # Manual commit for guaranteed processing
            'max_poll_records': 1000,  # Process in batches for efficiency
            'max_poll_interval_ms': 300000,  # 5 minutes max processing time
            'session_timeout_ms': 30000,  # 30 second session timeout
            'heartbeat_interval_ms': 10000,  # 10 second heartbeat
            'fetch_min_bytes': 1024,  # Minimum fetch size
            'fetch_max_wait_ms': 500,  # Max wait for batch
            'value_deserializer': self._deserialize_value,
            'key_deserializer': lambda x: x.decode('utf-8') if x else None,
            'consumer_timeout_ms': 1000,  # 1 second poll timeout
        }
        
        # Initialize components
        self._consumer: Optional[KafkaConsumer] = None
        self._running = False
        self._consumer_thread: Optional[threading.Thread] = None
        self._state = ConsumerState.STOPPED
        
        # Message handling
        self._message_handlers: Dict[str, Callable[[ConsumedMessage], None]] = {}
        self._default_handler: Optional[Callable[[ConsumedMessage], None]] = None
        
        # Statistics and monitoring
        self._stats = ConsumerStatistics()
        self._stats_lock = threading.Lock()
        self._last_successful_process = datetime.now()
        self._consecutive_failures = 0
        self._max_consecutive_failures = int(os.getenv('CONSUMER_MAX_FAILURES', '10'))
        
        # Symbol filtering
        self._symbol_filter: Optional[Set[str]] = None
        
        # Batch processing
        self._batch_size = int(os.getenv('CONSUMER_BATCH_SIZE', '100'))
        self._commit_interval = int(os.getenv('CONSUMER_COMMIT_INTERVAL', '5'))
        self._last_commit_time = time.time()
        
        logger.info(f"Market data consumer initialized (servers: {self.bootstrap_servers}, group: {self.group_id})")
    
    def start(self, symbol_filter: Optional[List[str]] = None) -> bool:
        """
        Start consuming market data from Kafka.
        
        Args:
            symbol_filter: Optional list of symbols to filter on
            
        Returns:
            True if started successfully
            
        Raises:
            KafkaPublishingError: If startup fails
        """
        logger.info(f"Starting market data consumer for topics: {self.topics}")
        
        try:
            # Set symbol filter
            if symbol_filter:
                self._symbol_filter = set(symbol_filter)
                logger.info(f"Symbol filter enabled for: {symbol_filter}")
            
            # Initialize Kafka consumer
            self._consumer = KafkaConsumer(**self.consumer_config)
            logger.info("Kafka consumer created successfully")
            
            # Subscribe to topics
            self._consumer.subscribe(self.topics)
            logger.info(f"Subscribed to topics: {self.topics}")
            
            # Start consumer thread
            self._running = True
            self._state = ConsumerState.RUNNING
            self._consumer_thread = threading.Thread(target=self._consume_messages, daemon=True)
            self._consumer_thread.start()
            
            logger.info("Market data consumer started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start consumer: {e}")
            self.stop()
            raise KafkaPublishingError(f"Consumer startup failed: {e}", "startup")
    
    def stop(self):
        """Stop the consumer and cleanup resources."""
        logger.info("Stopping market data consumer")
        
        self._running = False
        self._state = ConsumerState.STOPPED
        
        # Wait for consumer thread to finish
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=10.0)
        
        # Close Kafka consumer
        if self._consumer:
            try:
                self._consumer.close()
            except Exception as e:
                logger.warning(f"Error closing Kafka consumer: {e}")
            finally:
                self._consumer = None
        
        logger.info("Market data consumer stopped")
    
    def pause(self):
        """Pause message consumption."""
        if self._consumer and self._state == ConsumerState.RUNNING:
            self._consumer.pause(*self._consumer.assignment())
            self._state = ConsumerState.PAUSED
            logger.info("Consumer paused")
    
    def resume(self):
        """Resume message consumption."""
        if self._consumer and self._state == ConsumerState.PAUSED:
            self._consumer.resume(*self._consumer.assignment())
            self._state = ConsumerState.RUNNING
            logger.info("Consumer resumed")
    
    def register_message_handler(self, message_type: str, handler: Callable[[ConsumedMessage], None]):
        """
        Register a handler for specific message type.
        
        Args:
            message_type: Type of message (e.g., 'l2_order_book', 'trades', 'quotes')
            handler: Handler function
        """
        self._message_handlers[message_type] = handler
        logger.info(f"Registered handler for message type: {message_type}")
    
    def set_default_handler(self, handler: Callable[[ConsumedMessage], None]):
        """Set default handler for unregistered message types."""
        self._default_handler = handler
        logger.info("Default message handler registered")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get current consumer statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._stats_lock:
            now = datetime.now()
            
            return {
                'messages_consumed': self._stats.messages_consumed,
                'messages_processed': self._stats.messages_processed,
                'messages_failed': self._stats.messages_failed,
                'bytes_consumed': self._stats.bytes_consumed,
                'processing_success_rate': self._stats.processing_success_rate,
                'l2_messages': self._stats.l2_messages,
                'trade_messages': self._stats.trade_messages,
                'quote_messages': self._stats.quote_messages,
                'last_message_time': self._stats.last_message_time.isoformat() if self._stats.last_message_time else None,
                'consecutive_failures': self._consecutive_failures,
                'running': self._running,
                'state': self._state.value,
                'topics': self.topics,
                'group_id': self.group_id,
                'symbol_filter': list(self._symbol_filter) if self._symbol_filter else None,
                'uptime_seconds': (now - self._last_successful_process).total_seconds() if self._running else 0
            }
    
    def get_consumer_lag(self) -> Dict[str, Dict[int, int]]:
        """
        Get consumer lag for all assigned partitions.
        
        Returns:
            Dictionary with topic -> partition -> lag mapping
        """
        if not self._consumer:
            return {}
        
        try:
            lag_info = {}
            assignment = self._consumer.assignment()
            
            if assignment:
                # Get high water marks
                high_water_marks = self._consumer.end_offsets(assignment)
                
                for tp in assignment:
                    # Get current position
                    current_offset = self._consumer.position(tp)
                    high_water_mark = high_water_marks.get(tp, 0)
                    
                    lag = high_water_mark - current_offset
                    
                    if tp.topic not in lag_info:
                        lag_info[tp.topic] = {}
                    lag_info[tp.topic][tp.partition] = lag
            
            return lag_info
            
        except Exception as e:
            logger.warning(f"Failed to get consumer lag: {e}")
            return {}
    
    def _consume_messages(self):
        """Main consumer loop - polls messages and processes them."""
        logger.info("Consumer thread started")
        
        while self._running:
            try:
                # Poll for messages
                message_batch = self._consumer.poll(timeout_ms=1000)
                
                if message_batch:
                    # Process batch of messages
                    self._process_message_batch(message_batch)
                    
                    # Commit offsets periodically
                    now = time.time()
                    if now - self._last_commit_time >= self._commit_interval:
                        self._commit_offsets()
                        self._last_commit_time = now
                
                else:
                    # No messages - brief sleep to prevent CPU spinning
                    time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in consumer loop: {e}")
                self._consecutive_failures += 1
                
                if self._consecutive_failures >= self._max_consecutive_failures:
                    logger.error(f"Too many consecutive failures ({self._consecutive_failures}), stopping consumer")
                    self._running = False
                    self._state = ConsumerState.ERROR
                    break
                
                time.sleep(1)  # Brief pause before retry
        
        # Final commit before shutdown
        if self._consumer:
            try:
                self._commit_offsets()
            except Exception as e:
                logger.warning(f"Failed final commit: {e}")
        
        logger.info("Consumer thread stopped")
    
    def _process_message_batch(self, message_batch: Dict[TopicPartition, List]):
        """Process a batch of messages from Kafka."""
        for topic_partition, messages in message_batch.items():
            for kafka_message in messages:
                try:
                    # Convert Kafka message to ConsumedMessage
                    consumed_message = self._convert_kafka_message(kafka_message)
                    
                    # Apply symbol filter if set
                    if self._symbol_filter and consumed_message.symbol not in self._symbol_filter:
                        continue
                    
                    # Update consumption statistics
                    with self._stats_lock:
                        self._stats.messages_consumed += 1
                        self._stats.bytes_consumed += len(kafka_message.value) if kafka_message.value else 0
                        self._stats.last_message_time = datetime.now()
                    
                    # Process message
                    self._process_message(consumed_message)
                    
                    # Update processing statistics
                    with self._stats_lock:
                        self._stats.messages_processed += 1
                        
                        # Update message type counters
                        if consumed_message.message_type == 'l2_order_book':
                            self._stats.l2_messages += 1
                        elif consumed_message.message_type == 'trades':
                            self._stats.trade_messages += 1
                        elif consumed_message.message_type == 'quotes':
                            self._stats.quote_messages += 1
                    
                    self._consecutive_failures = 0
                    self._last_successful_process = datetime.now()
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
                    with self._stats_lock:
                        self._stats.messages_failed += 1
                    
                    self._consecutive_failures += 1
    
    def _convert_kafka_message(self, kafka_message) -> ConsumedMessage:
        """Convert Kafka message to ConsumedMessage format."""
        # Extract metadata
        metadata = kafka_message.value.get('_metadata', {})
        message_type = metadata.get('message_type', 'unknown')
        
        # Extract symbol
        symbol = kafka_message.value.get('symbol', kafka_message.key or 'UNKNOWN')
        
        # Convert timestamp
        timestamp = datetime.fromtimestamp(kafka_message.timestamp / 1000.0, tz=timezone.utc)
        
        return ConsumedMessage(
            topic=kafka_message.topic,
            partition=kafka_message.partition,
            offset=kafka_message.offset,
            key=kafka_message.key,
            value=kafka_message.value,
            timestamp=timestamp,
            symbol=symbol,
            message_type=message_type,
            headers={k.decode(): v.decode() for k, v in kafka_message.headers} if kafka_message.headers else None
        )
    
    def _process_message(self, message: ConsumedMessage):
        """Process a single consumed message."""
        # Find appropriate handler
        handler = self._message_handlers.get(message.message_type, self._default_handler)
        
        if handler:
            handler(message)
        else:
            logger.warning(f"No handler registered for message type: {message.message_type}")
    
    def _commit_offsets(self):
        """Commit current offsets to Kafka."""
        try:
            self._consumer.commit()
            logger.debug("Offsets committed successfully")
        except CommitFailedError as e:
            logger.warning(f"Failed to commit offsets: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during commit: {e}")
    
    def _deserialize_value(self, x):
        """Deserialize message value from JSON bytes."""
        if x is None:
            return None
        return json.loads(x.decode('utf-8'))
    
    def is_healthy(self) -> bool:
        """Check if consumer is healthy."""
        if not self._running:
            return False
        
        if self._state == ConsumerState.ERROR:
            return False
        
        # Check consecutive failures
        if self._consecutive_failures >= self._max_consecutive_failures:
            return False
        
        # Check if we've had recent successful processing
        time_since_success = (datetime.now() - self._last_successful_process).total_seconds()
        if time_since_success > 300:  # 5 minutes
            return False
        
        return True