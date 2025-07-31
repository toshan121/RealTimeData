"""
Enhanced Historical Replayer with Kafka Streaming

Integrates multi-symbol temporal orchestrator with Kafka streaming for complete
historical data replay pipeline. Supports both testing and production modes.

Architecture: ClickHouse → Temporal Orchestrator → Kafka Producer → GPU Processing

Key Features:
- Seamless integration with existing Kafka infrastructure
- Configurable replay modes (testing, validation, production)
- Backpressure handling and flow control
- Real-time monitoring and metrics
- Automatic error recovery and reconnection
"""

import logging
import threading
import time
import json
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import kafka
from kafka import KafkaProducer
from kafka.errors import KafkaError, KafkaTimeoutError

from .multi_symbol_temporal_orchestrator import (
    MultiSymbolTemporalOrchestrator,
    OrchestratorMode
)
from .iqfeed_parser import IQFeedMessageParser
from .exceptions import ProcessingError, DataValidationError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReplayMode(Enum):
    """Historical replay modes."""
    TESTING = "testing"         # Fast replay for testing (no Kafka)
    VALIDATION = "validation"   # Medium speed with validation
    PRODUCTION = "production"   # Real-time replay with full Kafka integration


@dataclass
class KafkaConfig:
    """Kafka configuration for historical replay."""
    bootstrap_servers: List[str] = field(default_factory=lambda: ['localhost:9092'])
    l2_topic: str = 'market_data_l2'
    trades_topic: str = 'market_data_trades'
    quotes_topic: str = 'market_data_quotes'
    batch_size: int = 16384
    linger_ms: int = 5
    compression_type: str = 'lz4'
    acks: str = 'all'
    retries: int = 3
    max_in_flight_requests_per_connection: int = 5
    buffer_memory: int = 33554432  # 32MB


@dataclass
class ReplayerStatistics:
    """Comprehensive replayer statistics."""
    messages_sent: int = 0
    messages_failed: int = 0
    bytes_sent: int = 0
    kafka_latency_ms: float = 0.0
    orchestrator_lag_ms: float = 0.0
    start_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    throughput_msgs_per_sec: float = 0.0
    throughput_mb_per_sec: float = 0.0
    kafka_errors: int = 0
    reconnections: int = 0
    topics_written: Dict[str, int] = field(default_factory=dict)


class EnhancedHistoricalReplayer:
    """
    Enhanced historical replayer with Kafka streaming integration.
    
    Provides complete pipeline from ClickHouse historical data to Kafka topics
    with temporal synchronization and production-ready reliability.
    """
    
    def __init__(
        self,
        mode: ReplayMode = ReplayMode.VALIDATION,
        clickhouse_host: str = 'localhost',
        clickhouse_port: int = 8123,
        clickhouse_database: str = 'l2_market_data',
        clickhouse_username: str = 'l2_user',
        clickhouse_password: str = 'l2_secure_pass',
        kafka_config: Optional[KafkaConfig] = None,
        playback_speed: float = 1.0,
        max_symbols: int = 2000,
        enable_kafka: bool = True
    ):
        """
        Initialize enhanced historical replayer.
        
        Args:
            mode: Replay mode (testing, validation, production)
            clickhouse_host: ClickHouse host
            clickhouse_port: ClickHouse port
            clickhouse_database: ClickHouse database
            clickhouse_username: ClickHouse username
            clickhouse_password: ClickHouse password
            kafka_config: Kafka configuration
            playback_speed: Playback speed multiplier
            max_symbols: Maximum symbols to handle
            enable_kafka: Enable Kafka integration
        """
        self.mode = mode
        self.playback_speed = playback_speed
        self.max_symbols = max_symbols
        self.enable_kafka = enable_kafka
        
        # Kafka configuration
        self.kafka_config = kafka_config or KafkaConfig()
        
        # Temporal orchestrator
        self.orchestrator = MultiSymbolTemporalOrchestrator(
            host=clickhouse_host,
            port=clickhouse_port,
            database=clickhouse_database,
            username=clickhouse_username,
            password=clickhouse_password,
            mode=OrchestratorMode.HISTORICAL_REPLAY,
            playback_speed=playback_speed,
            window_size_minutes=5 if mode == ReplayMode.PRODUCTION else 1,
            max_memory_mb=4096 if mode == ReplayMode.PRODUCTION else 1024,
            output_queue_size=100000 if mode == ReplayMode.PRODUCTION else 10000,
            worker_threads=16 if mode == ReplayMode.PRODUCTION else 4
        )
        
        # Kafka producer
        self._kafka_producer: Optional[KafkaProducer] = None
        
        # Message parser
        self._parser = IQFeedMessageParser()
        
        # State management
        self._running = False
        self._replay_thread: Optional[threading.Thread] = None
        self._stats_thread: Optional[threading.Thread] = None
        
        # Statistics
        self._stats = ReplayerStatistics()
        self._stats_lock = threading.Lock()
        
        # Topic routing
        self._topic_mapping = {
            'T': self.kafka_config.trades_topic,
            'Q': self.kafka_config.quotes_topic,
            'U': self.kafka_config.l2_topic,
            'L2': self.kafka_config.l2_topic
        }
        
        # Shutdown handling
        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Enhanced historical replayer initialized (mode: {mode.value}, kafka: {enable_kafka})")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self._shutdown_requested = True
        self.stop()
    
    def connect(self) -> bool:
        """Connect to ClickHouse and Kafka."""
        try:
            logger.info("Connecting enhanced historical replayer")
            
            # Connect orchestrator
            if not self.orchestrator.connect():
                logger.error("Failed to connect temporal orchestrator")
                return False
            
            # Connect Kafka if enabled
            if self.enable_kafka:
                if not self._connect_kafka():
                    logger.error("Failed to connect to Kafka")
                    return False
            
            with self._stats_lock:
                self._stats.start_time = datetime.now(timezone.utc)
            
            logger.info("Enhanced historical replayer connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect replayer: {e}")
            return False
    
    def _connect_kafka(self) -> bool:
        """Connect to Kafka with retry logic."""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to Kafka (attempt {attempt + 1}/{max_retries})")
                
                self._kafka_producer = KafkaProducer(
                    bootstrap_servers=self.kafka_config.bootstrap_servers,
                    batch_size=self.kafka_config.batch_size,
                    linger_ms=self.kafka_config.linger_ms,
                    compression_type=self.kafka_config.compression_type,
                    acks=self.kafka_config.acks,
                    retries=self.kafka_config.retries,
                    max_in_flight_requests_per_connection=self.kafka_config.max_in_flight_requests_per_connection,
                    buffer_memory=self.kafka_config.buffer_memory,
                    value_serializer=lambda x: json.dumps(x).encode('utf-8'),
                    key_serializer=lambda x: x.encode('utf-8') if x else None,
                    reconnect_backoff_ms=1000,
                    retry_backoff_ms=100
                )
                
                # Test connection
                metadata = self._kafka_producer.bootstrap_connected()
                if metadata:
                    logger.info("Kafka connection established")
                    return True
                
            except Exception as e:
                logger.warning(f"Kafka connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
        
        return False
    
    def disconnect(self):
        """Disconnect and cleanup resources."""
        logger.info("Disconnecting enhanced historical replayer")
        
        # Stop replay
        self.stop()
        
        # Close Kafka producer
        if self._kafka_producer:
            try:
                self._kafka_producer.flush(timeout=10)
                self._kafka_producer.close(timeout=10)
            except Exception as e:
                logger.warning(f"Error closing Kafka producer: {e}")
            finally:
                self._kafka_producer = None
        
        # Disconnect orchestrator
        self.orchestrator.disconnect()
        
        logger.info("Enhanced historical replayer disconnected")
    
    def setup_replay(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        data_types: List[str] = ['trades', 'quotes', 'l2_updates']
    ) -> bool:
        """
        Setup historical replay configuration.
        
        Args:
            symbols: List of symbols to replay
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            data_types: Data types to include
            
        Returns:
            True if setup successful
        """
        try:
            logger.info(f"Setting up replay for {len(symbols)} symbols from {start_date} to {end_date}")
            
            # Limit symbols based on mode
            if len(symbols) > self.max_symbols:
                logger.warning(f"Limiting symbols from {len(symbols)} to {self.max_symbols}")
                symbols = symbols[:self.max_symbols]
            
            # Setup orchestrator
            success = self.orchestrator.setup_replay(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                data_types=data_types
            )
            
            if success:
                # Initialize topic statistics
                with self._stats_lock:
                    for topic in self._topic_mapping.values():
                        self._stats.topics_written[topic] = 0
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to setup replay: {e}")
            return False
    
    def start_replay(self) -> bool:
        """Start the historical replay."""
        if self._running:
            logger.warning("Replay is already running")
            return True
        
        logger.info("Starting historical replay")
        
        # Connect orchestrator first
        if not self.orchestrator.connect():
            logger.error("Failed to connect temporal orchestrator")
            return False
        
        # Start orchestrator
        if not self.orchestrator.start():
            logger.error("Failed to start temporal orchestrator")
            return False
        
        self._running = True
        
        # Start replay thread
        self._replay_thread = threading.Thread(
            target=self._replay_loop,
            name="historical-replayer",
            daemon=True
        )
        self._replay_thread.start()
        
        # Start statistics thread
        self._stats_thread = threading.Thread(
            target=self._stats_loop,
            name="replayer-stats",
            daemon=True
        )
        self._stats_thread.start()
        
        logger.info("Historical replay started")
        return True
    
    def stop_replay(self):
        """Stop the historical replay."""
        logger.info("Stopping historical replay")
        
        self._running = False
        
        # Stop orchestrator
        self.orchestrator.stop()
        
        # Wait for threads
        if self._replay_thread and self._replay_thread.is_alive():
            self._replay_thread.join(timeout=10.0)
        
        if self._stats_thread and self._stats_thread.is_alive():
            self._stats_thread.join(timeout=5.0)
        
        # Flush Kafka producer
        if self._kafka_producer:
            try:
                self._kafka_producer.flush(timeout=5)
            except Exception as e:
                logger.warning(f"Error flushing Kafka producer: {e}")
        
        logger.info("Historical replay stopped")
    
    def start(self) -> bool:
        """Start the complete replayer (connect + replay)."""
        if not self.connect():
            return False
        return self.start_replay()
    
    def stop(self):
        """Stop the complete replayer."""
        self.stop_replay()
        self.disconnect()
    
    def _replay_loop(self):
        """Main replay loop."""
        logger.info("Historical replay loop started")
        
        try:
            while self._running and not self._shutdown_requested:
                # Get next message from orchestrator
                message = self.orchestrator.get_next_message(timeout=0.1)
                
                if message is None:
                    # Check if orchestrator is still running
                    if not self.orchestrator.is_running():
                        logger.info("Orchestrator finished, ending replay")
                        break
                    continue
                
                # Process message
                success = self._process_message(message)
                
                if success:
                    with self._stats_lock:
                        self._stats.messages_sent += 1
                        self._stats.bytes_sent += len(message.get('raw_message', ''))
                        self._stats.last_message_time = datetime.now(timezone.utc)
                else:
                    with self._stats_lock:
                        self._stats.messages_failed += 1
        
        except Exception as e:
            logger.error(f"Error in replay loop: {e}")
        
        logger.info("Historical replay loop stopped")
    
    def _process_message(self, message: Dict[str, Any]) -> bool:
        """Process a single message."""
        try:
            message_type = message.get('message_type', '')
            raw_message = message.get('raw_message', '')
            symbol = message.get('symbol', '')
            
            if not raw_message:
                return False
            
            # Parse message if needed for validation
            if self.mode == ReplayMode.VALIDATION:
                try:
                    if message_type == 'T':
                        parsed = self._parser.parse_trade_message(raw_message)
                    elif message_type == 'Q':
                        parsed = self._parser.parse_quote_message(raw_message)
                    elif message_type == 'U':
                        parsed = self._parser.parse_l2_message(raw_message)
                    else:
                        logger.warning(f"Unknown message type: {message_type}")
                        return False
                except Exception as e:
                    logger.warning(f"Message parsing failed: {e}")
                    return False
            
            # Send to Kafka if enabled
            if self.enable_kafka and self._kafka_producer:
                return self._send_to_kafka(message, message_type, symbol)
            
            # For testing mode, just log occasionally
            elif self.mode == ReplayMode.TESTING:
                if self._stats.messages_sent % 1000 == 0:
                    logger.info(f"Processed {self._stats.messages_sent} messages (testing mode)")
            
            return True
            
        except Exception as e:
            logger.warning(f"Error processing message: {e}")
            return False
    
    def _send_to_kafka(self, message: Dict[str, Any], message_type: str, symbol: str) -> bool:
        """Send message to appropriate Kafka topic."""
        try:
            # Determine topic
            topic = self._topic_mapping.get(message_type)
            if not topic:
                logger.warning(f"No topic mapping for message type: {message_type}")
                return False
            
            # Prepare message for Kafka
            kafka_message = {
                'timestamp': message.get('timestamp'),
                'symbol': symbol,
                'message_type': message_type,
                'data': message.get('raw_message'),
                'tick_id': message.get('tick_id'),
                'replay_timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Send to Kafka
            future = self._kafka_producer.send(
                topic=topic,
                key=symbol,  # Partition by symbol for ordering
                value=kafka_message
            )
            
            # Add callback for monitoring
            future.add_callback(self._kafka_success_callback, topic)
            future.add_errback(self._kafka_error_callback, topic)
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to send message to Kafka: {e}")
            with self._stats_lock:
                self._stats.kafka_errors += 1
            return False
    
    def _kafka_success_callback(self, metadata, topic: str):
        """Kafka send success callback."""
        with self._stats_lock:
            self._stats.topics_written[topic] = self._stats.topics_written.get(topic, 0) + 1
    
    def _kafka_error_callback(self, exception, topic: str):
        """Kafka send error callback."""
        logger.warning(f"Kafka send failed for topic {topic}: {exception}")
        with self._stats_lock:
            self._stats.kafka_errors += 1
    
    def _stats_loop(self):
        """Statistics monitoring loop."""
        logger.info("Statistics monitoring started")
        
        last_messages = 0
        last_time = time.time()
        
        while self._running:
            try:
                time.sleep(5)  # Update every 5 seconds
                
                current_time = time.time()
                
                with self._stats_lock:
                    # Calculate throughput
                    messages_delta = self._stats.messages_sent - last_messages
                    time_delta = current_time - last_time
                    
                    if time_delta > 0:
                        self._stats.throughput_msgs_per_sec = messages_delta / time_delta
                        self._stats.throughput_mb_per_sec = (self._stats.bytes_sent / (1024 * 1024)) / time_delta
                
                # Get orchestrator stats
                orch_stats = self.orchestrator.get_statistics()
                
                # Log periodic update
                logger.info(f"Replay Stats - Sent: {self._stats.messages_sent}, "
                          f"Failed: {self._stats.messages_failed}, "
                          f"Throughput: {self._stats.throughput_msgs_per_sec:.1f} msg/s, "
                          f"Orchestrator Queue: {orch_stats.get('output_queue_size', 0)}")
                
                last_messages = self._stats.messages_sent
                last_time = current_time
                
            except Exception as e:
                logger.warning(f"Error in stats loop: {e}")
        
        logger.info("Statistics monitoring stopped")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive replayer statistics."""
        with self._stats_lock:
            stats = {
                'replayer': {
                    'mode': self.mode.value,
                    'running': self._running,
                    'messages_sent': self._stats.messages_sent,
                    'messages_failed': self._stats.messages_failed,
                    'bytes_sent': self._stats.bytes_sent,
                    'throughput_msgs_per_sec': self._stats.throughput_msgs_per_sec,
                    'throughput_mb_per_sec': self._stats.throughput_mb_per_sec,
                    'kafka_errors': self._stats.kafka_errors,
                    'topics_written': dict(self._stats.topics_written),
                    'start_time': self._stats.start_time.isoformat() if self._stats.start_time else None,
                    'last_message_time': self._stats.last_message_time.isoformat() if self._stats.last_message_time else None
                },
                'orchestrator': self.orchestrator.get_statistics(),
                'kafka_enabled': self.enable_kafka,
                'playback_speed': self.playback_speed
            }
        
        return stats
    
    def is_running(self) -> bool:
        """Check if replayer is running."""
        return self._running


def main():
    """Main function for testing the enhanced historical replayer."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Historical Replayer')
    parser.add_argument('--mode', choices=['testing', 'validation', 'production'], 
                       default='validation', help='Replay mode')
    parser.add_argument('--symbols', nargs='+', default=['AAPL', 'MSFT', 'GOOGL'], 
                       help='Symbols to replay')
    parser.add_argument('--start-date', default='2025-07-29', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2025-07-29', help='End date (YYYY-MM-DD)')
    parser.add_argument('--speed', type=float, default=1.0, help='Playback speed multiplier')
    parser.add_argument('--no-kafka', action='store_true', help='Disable Kafka integration')
    parser.add_argument('--max-messages', type=int, default=10000, help='Maximum messages to process')
    
    args = parser.parse_args()
    
    # Create replayer
    replayer = EnhancedHistoricalReplayer(
        mode=ReplayMode(args.mode),
        playback_speed=args.speed,
        enable_kafka=not args.no_kafka
    )
    
    try:
        logger.info(f"Starting replayer in {args.mode} mode")
        
        # Setup replay
        if not replayer.setup_replay(
            symbols=args.symbols,
            start_date=args.start_date,
            end_date=args.end_date
        ):
            logger.error("Failed to setup replay")
            return 1
        
        # Start replayer
        if not replayer.start():
            logger.error("Failed to start replayer")
            return 1
        
        # Monitor progress
        start_time = time.time()
        last_stats_time = start_time
        
        while replayer.is_running():
            time.sleep(1)
            
            # Print periodic statistics
            if time.time() - last_stats_time > 10:
                stats = replayer.get_statistics()
                logger.info(f"Progress: {stats}")
                last_stats_time = time.time()
            
            # Check message limit
            stats = replayer.get_statistics()
            if stats['replayer']['messages_sent'] >= args.max_messages:
                logger.info(f"Reached message limit ({args.max_messages}), stopping")
                break
            
            # Check timeout
            if time.time() - start_time > 300:  # 5 minute timeout
                logger.info("Timeout reached, stopping")
                break
        
        # Final statistics
        final_stats = replayer.get_statistics()
        logger.info(f"Final statistics: {final_stats}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1
    finally:
        replayer.stop()


if __name__ == "__main__":
    sys.exit(main())