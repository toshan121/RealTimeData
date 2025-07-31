#!/usr/bin/env python3
"""
Real-Time Kafka Producer
- High-performance Kafka producer for trading data
- Handles L1, L2, and tick data streams
- Built-in performance monitoring and circuit breaker
- Designed for hedge fund level throughput
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import asdict
import threading
from collections import deque, defaultdict

try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logger.warning("Kafka not available - using mock producer")

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """Circuit breaker for fault tolerance"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        
    def call(self, func, *args, **kwargs):
        """Call function with circuit breaker protection"""
        
        if self.state == 'OPEN':
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = 'HALF_OPEN'
                logger.info("Circuit breaker: HALF_OPEN - attempting recovery")
            else:
                raise Exception("Circuit breaker OPEN - calls blocked")
        
        try:
            result = func(*args, **kwargs)
            
            # Success - reset if in HALF_OPEN
            if self.state == 'HALF_OPEN':
                self.reset()
                
            return result
            
        except Exception as e:
            self.record_failure()
            raise e
    
    def record_failure(self):
        """Record a failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"Circuit breaker OPEN - {self.failure_count} failures")
    
    def reset(self):
        """Reset circuit breaker"""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'
        logger.info("Circuit breaker RESET - service recovered")


class MockKafkaProducer:
    """Mock Kafka producer for testing when Kafka is not available"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.messages_sent = 0
        
    def send(self, topic: str, value: bytes, key: bytes = None):
        """Mock send - just log the message"""
        self.messages_sent += 1
        if self.messages_sent % 1000 == 0:
            logger.debug(f"Mock Kafka: sent {self.messages_sent} messages to {topic}")
        
        # Return a mock future
        class MockFuture:
            def add_callback(self, callback):
                pass
            def add_errback(self, errback):
                pass
                
        return MockFuture()
    
    def flush(self):
        pass
        
    def close(self):
        logger.info(f"Mock Kafka producer closed. Total messages: {self.messages_sent}")


class RealTimeKafkaProducer:
    """
    High-performance Kafka producer for real-time trading data
    Features:
    - Asynchronous sends with callbacks
    - Circuit breaker for fault tolerance
    - Performance monitoring and metrics
    - Batch optimization
    - Topic management
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.kafka_config = config.get('kafka', {})
        self.scaling_config = config.get('scaling', {})
        
        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.scaling_config.get('failure_threshold', 5),
            recovery_timeout=self.scaling_config.get('recovery_timeout_seconds', 30)
        )
        
        # Performance tracking
        self.stats = {
            'messages_sent': 0,
            'messages_failed': 0,
            'bytes_sent': 0,
            'send_rate_per_second': 0,
            'last_send_time': None,
            'topic_stats': defaultdict(int),
            'error_stats': defaultdict(int)
        }
        
        # Rate tracking for performance monitoring
        self.send_times = deque(maxlen=1000)
        self.stats_lock = threading.Lock()
        
        # Initialize producer
        self.producer = None
        self._setup_producer()
        
    def _setup_producer(self):
        """Setup Kafka producer with optimized configuration"""
        
        if not KAFKA_AVAILABLE:
            logger.warning("Using mock Kafka producer")
            self.producer = MockKafkaProducer(self.config)
            return
            
        try:
            producer_config = {
                'bootstrap_servers': self.kafka_config.get('bootstrap_servers', ['localhost:9092']),
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'key_serializer': lambda k: k.encode('utf-8') if k else None,
                
                # Performance optimizations
                'batch_size': self.kafka_config.get('batch_size', 16384),
                'linger_ms': self.kafka_config.get('linger_ms', 5),
                'acks': self.kafka_config.get('acks', 1),
                'compression_type': 'snappy',
                'max_in_flight_requests_per_connection': 5,
                'retries': 3,
                'retry_backoff_ms': 100,
                
                # Buffer settings for high throughput
                'buffer_memory': 33554432,  # 32MB
                'max_block_ms': 5000,
            }
            
            self.producer = KafkaProducer(**producer_config)
            logger.info("✓ Kafka producer initialized with high-performance settings")
            
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            logger.warning("Falling back to mock producer")
            self.producer = MockKafkaProducer(self.config)
    
    def _update_stats(self, topic: str, data_size: int, success: bool = True):
        """Update performance statistics"""
        with self.stats_lock:
            current_time = time.time()
            
            if success:
                self.stats['messages_sent'] += 1
                self.stats['bytes_sent'] += data_size
                self.stats['topic_stats'][topic] += 1
            else:
                self.stats['messages_failed'] += 1
            
            self.stats['last_send_time'] = current_time
            self.send_times.append(current_time)
            
            # Calculate send rate (messages per second)
            if len(self.send_times) >= 2:
                time_window = self.send_times[-1] - self.send_times[0]
                if time_window > 0:
                    self.stats['send_rate_per_second'] = len(self.send_times) / time_window
    
    def _send_message(self, topic: str, data: Dict, key: Optional[str] = None):
        """Send message to Kafka with circuit breaker protection"""
        
        def _actual_send():
            serialized_data = data if isinstance(data, dict) else asdict(data)
            data_size = len(json.dumps(serialized_data))
            
            future = self.producer.send(
                topic=topic,
                value=serialized_data,
                key=key
            )
            
            # Add callbacks for monitoring
            future.add_callback(lambda metadata: self._update_stats(topic, data_size, True))
            future.add_errback(lambda error: self._handle_send_error(topic, error))
            
            return future
        
        try:
            return self.circuit_breaker.call(_actual_send)
        except Exception as e:
            logger.error(f"Failed to send message to {topic}: {e}")
            self._update_stats(topic, 0, False)
            return None
    
    def _handle_send_error(self, topic: str, error):
        """Handle Kafka send errors"""
        with self.stats_lock:
            self.stats['error_stats'][str(type(error).__name__)] += 1
        
        logger.error(f"Kafka send error for topic {topic}: {error}")
        self._update_stats(topic, 0, False)
    
    def send_l1_data(self, l1_data) -> bool:
        """Send Level 1 data to Kafka"""
        try:
            topic = self.kafka_config['topics']['l1_quotes']
            key = l1_data.symbol if hasattr(l1_data, 'symbol') else None
            
            future = self._send_message(topic, l1_data, key)
            return future is not None
            
        except Exception as e:
            logger.error(f"Error sending L1 data: {e}")
            return False
    
    def send_l2_data(self, l2_data) -> bool:
        """Send Level 2 data to Kafka"""
        try:
            topic = self.kafka_config['topics']['l2_quotes']
            key = l2_data.symbol if hasattr(l2_data, 'symbol') else None
            
            future = self._send_message(topic, l2_data, key)
            return future is not None
            
        except Exception as e:
            logger.error(f"Error sending L2 data: {e}")
            return False
    
    def send_tick_data(self, tick_data) -> bool:
        """Send tick data to Kafka"""
        try:
            topic = self.kafka_config['topics']['ticks']
            key = tick_data.symbol if hasattr(tick_data, 'symbol') else None
            
            future = self._send_message(topic, tick_data, key)
            return future is not None
            
        except Exception as e:
            logger.error(f"Error sending tick data: {e}")
            return False
    
    def send_metrics(self, metrics_data: Dict) -> bool:
        """Send system metrics to Kafka"""
        try:
            topic = self.kafka_config['topics']['metrics']
            
            # Add timestamp if not present
            if 'timestamp' not in metrics_data:
                metrics_data['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            future = self._send_message(topic, metrics_data)
            return future is not None
            
        except Exception as e:
            logger.error(f"Error sending metrics: {e}")
            return False
    
    def flush(self):
        """Flush pending messages"""
        try:
            if hasattr(self.producer, 'flush'):
                self.producer.flush()
        except Exception as e:
            logger.error(f"Error flushing Kafka producer: {e}")
    
    def close(self):
        """Close Kafka producer"""
        try:
            logger.info("Closing Kafka producer...")
            
            # Flush any pending messages
            self.flush()
            
            # Close producer
            if hasattr(self.producer, 'close'):
                self.producer.close()
            
            # Log final statistics
            logger.info(f"Kafka producer closed. Final stats: {self.get_stats()}")
            
        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")
    
    def get_stats(self) -> Dict:
        """Get current producer statistics"""
        with self.stats_lock:
            return {
                **self.stats.copy(),
                'circuit_breaker_state': self.circuit_breaker.state,
                'topic_distribution': dict(self.stats['topic_stats']),
                'error_distribution': dict(self.stats['error_stats'])
            }
    
    def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        
        health_status = {
            'status': 'healthy',
            'circuit_breaker': self.circuit_breaker.state,
            'last_send_age_seconds': None,
            'send_rate': self.stats['send_rate_per_second'],
            'error_rate': 0
        }
        
        # Check last send time
        if self.stats['last_send_time']:
            age = time.time() - self.stats['last_send_time']
            health_status['last_send_age_seconds'] = age
            
            if age > 60:  # No sends for 1 minute
                health_status['status'] = 'warning'
        
        # Check error rate
        total_messages = self.stats['messages_sent'] + self.stats['messages_failed']
        if total_messages > 0:
            error_rate = self.stats['messages_failed'] / total_messages
            health_status['error_rate'] = error_rate
            
            if error_rate > 0.05:  # >5% error rate
                health_status['status'] = 'critical'
        
        # Check circuit breaker
        if self.circuit_breaker.state == 'OPEN':
            health_status['status'] = 'critical'
        elif self.circuit_breaker.state == 'HALF_OPEN':
            health_status['status'] = 'warning'
        
        return health_status


# Factory function for easy instantiation
def create_kafka_producer(config: Dict) -> RealTimeKafkaProducer:
    """Factory function to create configured Kafka producer"""
    return RealTimeKafkaProducer(config)