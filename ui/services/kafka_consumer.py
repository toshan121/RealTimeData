#!/usr/bin/env python3
"""
Kafka Consumer Service for UI
Bridges Kafka messages to Redis for UI consumption
Handles multiple topics with rate limiting and error recovery
"""

import json
import time
import redis
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from kafka import KafkaConsumer
from kafka.errors import KafkaError
import sys
import os

# Add project root to path
sys.path.append(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)

logger = logging.getLogger(__name__)


@dataclass
class UIMessage:
    """Standardized message format for UI consumption"""

    topic: str
    symbol: str
    message_type: str  # 'tick', 'l1', 'l2', 'trade'
    timestamp: str
    system_timestamp: str
    data: Dict
    latency_ms: float = 0


class KafkaToRedisConsumer:
    """
    Kafka consumer that feeds Redis for UI consumption
    - Consumes from multiple Kafka topics
    - Transforms messages for UI
    - Manages Redis keys with TTL
    - Rate limiting and backpressure
    - Error handling and reconnection
    """

    def __init__(self, kafka_config: Dict, redis_config: Dict, ui_config: Dict = None):
        self.kafka_config = kafka_config
        self.redis_config = redis_config
        self.ui_config = ui_config or {
            "max_messages_per_second": 1000,
            "redis_ttl_seconds": 300,  # 5 minutes TTL for UI data
            "max_messages_per_symbol": 100,  # Keep last 100 messages per symbol
            "enable_aggregation": True,  # Create aggregated views
            "aggregation_window_seconds": 1,  # 1 second aggregation window
        }

        # Kafka consumer
        self.consumer = None
        self.topics = ["market_ticks", "market_l1", "market_l2", "market_trades"]

        # Redis client
        self.redis_client = redis.Redis(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6380),
            db=redis_config.get("db", 0),
            decode_responses=True,
        )

        # Control
        self.running = False
        self.consumer_thread = None

        # Statistics
        self.stats = {
            "messages_consumed": 0,
            "messages_to_redis": 0,
            "errors": 0,
            "last_message_time": None,
            "messages_per_second": 0,
            "topics_stats": {topic: 0 for topic in self.topics},
            "start_time": None,
        }

        # Rate limiting
        self._message_times = []
        self._last_rate_check = time.time()

    def start(self):
        """Start the Kafka to Redis consumer service"""
        if self.running:
            logger.warning("Kafka consumer already running")
            return False

        logger.info("🔄 Starting Kafka to Redis consumer")

        try:
            # Test Redis connection
            self.redis_client.ping()
            logger.info("✅ Redis connection verified")

            # Create Kafka consumer
            self.consumer = KafkaConsumer(
                *self.topics,
                bootstrap_servers=self.kafka_config.get(
                    "bootstrap_servers", ["localhost:9092"]
                ),
                group_id=self.kafka_config.get("group_id", "ui_consumer_group"),
                auto_offset_reset="latest",  # Only get new messages
                enable_auto_commit=True,
                value_deserializer=lambda x: json.loads(x.decode("utf-8"))
                if x
                else None,
                consumer_timeout_ms=1000,  # 1 second timeout for responsiveness
            )

            logger.info(f"✅ Kafka consumer created for topics: {self.topics}")

            # Start consumer thread
            self.running = True
            self.stats["start_time"] = datetime.now()

            self.consumer_thread = threading.Thread(
                target=self._consume_loop, daemon=True
            )
            self.consumer_thread.start()

            logger.info("✅ Kafka to Redis consumer started")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to start Kafka consumer: {e}")
            return False

    def stop(self):
        """Stop the Kafka to Redis consumer"""
        logger.info("🛑 Stopping Kafka to Redis consumer")

        self.running = False

        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)

        if self.consumer:
            try:
                self.consumer.close()
            except Exception as e:
                logger.error(f"Error closing Kafka consumer: {e}")

        logger.info("✅ Kafka to Redis consumer stopped")

    def _consume_loop(self):
        """Main consumption loop"""
        logger.info("👂 Starting Kafka consumption loop")

        while self.running:
            try:
                # Poll for messages with timeout
                message_batch = self.consumer.poll(timeout_ms=1000)

                if not message_batch:
                    continue

                # Process messages from all topics
                for topic_partition, messages in message_batch.items():
                    topic = topic_partition.topic

                    for message in messages:
                        if not self.running:
                            break

                        try:
                            self._process_message(topic, message.value)
                            self.stats["messages_consumed"] += 1
                            self.stats["topics_stats"][topic] += 1
                            self.stats["last_message_time"] = datetime.now()

                            # Rate limiting check
                            if self._should_rate_limit():
                                time.sleep(0.001)  # 1ms delay

                        except Exception as e:
                            logger.error(f"Error processing message from {topic}: {e}")
                            self.stats["errors"] += 1

                # Update rate statistics
                self._update_rate_stats()

            except KafkaError as e:
                logger.error(f"Kafka error: {e}")
                self.stats["errors"] += 1
                time.sleep(1)  # Wait before retrying

            except Exception as e:
                logger.error(f"Unexpected error in consume loop: {e}")
                self.stats["errors"] += 1
                time.sleep(1)

    def _process_message(self, topic: str, message_data: Dict):
        """Process a single Kafka message and store in Redis"""
        if not message_data:
            return

        try:
            # Extract common fields
            symbol = message_data.get("symbol", "UNKNOWN")
            timestamp = message_data.get("timestamp", datetime.now().isoformat())
            system_timestamp = datetime.now().isoformat()

            # Calculate latency if possible
            latency_ms = 0
            try:
                if "system_timestamp" in message_data:
                    msg_time = datetime.fromisoformat(
                        message_data["system_timestamp"].replace("Z", "+00:00")
                    )
                    now_time = datetime.now()
                    latency_ms = (
                        now_time - msg_time.replace(tzinfo=None)
                    ).total_seconds() * 1000
            except Exception as e:
                logger.warning(f"💥 FAKE ELIMINATED: Failed to calculate Kafka message latency: {e}")

            # Determine message type based on topic
            message_type = self._get_message_type(topic)

            # Create UI message
            ui_message = UIMessage(
                topic=topic,
                symbol=symbol,
                message_type=message_type,
                timestamp=timestamp,
                system_timestamp=system_timestamp,
                data=message_data,
                latency_ms=latency_ms,
            )

            # Store in Redis
            self._store_in_redis(ui_message)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise

    def _get_message_type(self, topic: str) -> str:
        """Determine message type from topic name"""
        if "tick" in topic:
            return "tick"
        elif "l1" in topic:
            return "l1"
        elif "l2" in topic:
            return "l2"
        elif "trade" in topic:
            return "trade"
        else:
            return "unknown"

    def _store_in_redis(self, ui_message: UIMessage):
        """Store UI message in Redis with appropriate keys"""
        symbol = ui_message.symbol
        message_type = ui_message.message_type

        # Convert to JSON
        message_json = json.dumps(asdict(ui_message), default=str)

        # Store latest message for each symbol/type
        latest_key = f"ui:latest:{message_type}:{symbol}"
        self.redis_client.setex(
            latest_key, self.ui_config["redis_ttl_seconds"], message_json
        )

        # Store in time-ordered list for history
        history_key = f"ui:history:{message_type}:{symbol}"
        self.redis_client.lpush(history_key, message_json)
        self.redis_client.ltrim(
            history_key, 0, self.ui_config["max_messages_per_symbol"] - 1
        )
        self.redis_client.expire(history_key, self.ui_config["redis_ttl_seconds"])

        # Store in global latest stream
        stream_key = f"ui:stream:{message_type}"
        stream_entry = {
            "symbol": symbol,
            "timestamp": ui_message.system_timestamp,
            "data": message_json,
        }
        self.redis_client.lpush(stream_key, json.dumps(stream_entry))
        self.redis_client.ltrim(stream_key, 0, 999)  # Keep last 1000 messages
        self.redis_client.expire(stream_key, self.ui_config["redis_ttl_seconds"])

        # Create aggregated views if enabled
        if self.ui_config["enable_aggregation"]:
            self._create_aggregated_views(ui_message)

        self.stats["messages_to_redis"] += 1

    def _create_aggregated_views(self, ui_message: UIMessage):
        """Create aggregated views for better UI performance"""
        symbol = ui_message.symbol

        try:
            # Count messages by symbol
            count_key = f"ui:count:{symbol}"
            self.redis_client.incr(count_key)
            self.redis_client.expire(count_key, self.ui_config["redis_ttl_seconds"])

            # Latest activity timestamp
            activity_key = f"ui:activity:{symbol}"
            self.redis_client.setex(
                activity_key,
                self.ui_config["redis_ttl_seconds"],
                ui_message.system_timestamp,
            )

            # Symbol list (for UI symbol selection)
            symbols_key = "ui:symbols:active"
            self.redis_client.sadd(symbols_key, symbol)
            self.redis_client.expire(symbols_key, self.ui_config["redis_ttl_seconds"])

        except Exception as e:
            logger.debug(f"Error creating aggregated views: {e}")

    def _should_rate_limit(self) -> bool:
        """Check if rate limiting should be applied"""
        now = time.time()
        self._message_times.append(now)

        # Keep only messages from last second
        cutoff_time = now - 1.0
        self._message_times = [t for t in self._message_times if t > cutoff_time]

        # Rate limit if exceeding threshold
        return len(self._message_times) > self.ui_config["max_messages_per_second"]

    def _update_rate_stats(self):
        """Update rate statistics"""
        now = time.time()

        if now - self._last_rate_check >= 1.0:  # Update every second
            current_rate = len([t for t in self._message_times if t > now - 1.0])
            self.stats["messages_per_second"] = current_rate
            self._last_rate_check = now

    def get_status(self) -> Dict:
        """Get consumer service status"""
        uptime = None
        if self.stats["start_time"]:
            uptime = (datetime.now() - self.stats["start_time"]).total_seconds()

        return {
            "running": self.running,
            "uptime_seconds": uptime,
            "stats": self.stats,
            "config": self.ui_config,
            "topics": self.topics,
            "redis_connection": self._test_redis_connection(),
            "kafka_connection": self._test_kafka_connection(),
        }

    def _test_redis_connection(self) -> bool:
        """Test Redis connection"""
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.warning(f"💥 FAKE ELIMINATED: Redis connection test failed: {e}")
            return False

    def _test_kafka_connection(self) -> bool:
        """Test Kafka connection"""
        try:
            return self.consumer is not None and self.running
        except Exception as e:
            logger.warning(f"💥 FAKE ELIMINATED: Kafka connection test failed: {e}")
            return False

    def get_ui_data(
        self, symbol: str, message_type: str, max_messages: int = 50
    ) -> List[Dict]:
        """Get UI data for specific symbol and type"""
        try:
            history_key = f"ui:history:{message_type}:{symbol}"
            messages = self.redis_client.lrange(history_key, 0, max_messages - 1)

            return [json.loads(msg) for msg in messages]
        except Exception as e:
            logger.error(f"Error getting UI data: {e}")
            return []

    def get_active_symbols(self) -> List[str]:
        """Get list of currently active symbols"""
        try:
            symbols_key = "ui:symbols:active"
            return list(self.redis_client.smembers(symbols_key))
        except Exception as e:
            logger.error(f"Error getting active symbols: {e}")
            return []


def create_kafka_ui_consumer(
    kafka_config: Dict, redis_config: Dict, ui_config: Dict = None
) -> KafkaToRedisConsumer:
    """Factory function to create Kafka UI consumer"""
    return KafkaToRedisConsumer(kafka_config, redis_config, ui_config)


if __name__ == "__main__":
    # Test the Kafka to Redis consumer
    logging.basicConfig(level=logging.INFO)

    kafka_config = {
        "bootstrap_servers": ["localhost:9092"],
        "group_id": "test_ui_consumer",
    }

    redis_config = {"host": "localhost", "port": 6380, "db": 0}

    ui_config = {
        "max_messages_per_second": 100,  # Lower for testing
        "redis_ttl_seconds": 60,  # Shorter TTL for testing
    }

    consumer = KafkaToRedisConsumer(kafka_config, redis_config, ui_config)

    try:
        if consumer.start():
            print("✅ Kafka to Redis consumer started successfully")

            # Run for testing
            time.sleep(30)

            # Get status
            status = consumer.get_status()
            print(f"📊 Status: {json.dumps(status, indent=2, default=str)}")

            # Get active symbols
            symbols = consumer.get_active_symbols()
            print(f"🎯 Active symbols: {symbols}")

        else:
            print("❌ Failed to start Kafka to Redis consumer")

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")

    finally:
        consumer.stop()
        print("✅ Kafka to Redis consumer stopped")
