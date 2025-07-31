#!/usr/bin/env python3
"""
Redis Cleaner Service
Prevents Redis memory growth by managing TTL and cleanup
Critical for long-running real-time systems
"""

import redis
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

logger = logging.getLogger(__name__)


class RedisCleanerService:
    """
    Redis memory management service
    - Sets TTL on market data keys
    - Monitors memory usage
    - Configurable retention policies
    - Cleanup scheduling
    """

    def __init__(self, redis_config: Dict, cleanup_config: Dict = None):
        self.redis_client = redis.Redis(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6380),
            db=redis_config.get("db", 0),
            decode_responses=True,
        )

        # Default cleanup configuration
        self.config = cleanup_config or {
            "market_data_ttl_seconds": 3600,  # 1 hour for real-time market data
            "historical_data_ttl_seconds": 86400,  # 24 hours for historical data
            "system_metrics_ttl_seconds": 1800,  # 30 minutes for system metrics
            "cleanup_interval_seconds": 300,  # Run cleanup every 5 minutes
            "memory_threshold_mb": 512,  # Alert if Redis > 512MB
            "max_keys_per_pattern": 10000,  # Prevent runaway key creation
        }

        self.running = False
        self.cleanup_thread = None
        self.stats = {
            "keys_processed": 0,
            "keys_expired": 0,
            "memory_alerts": 0,
            "last_cleanup": None,
            "cleanup_errors": 0,
        }

        # Key patterns for different data types
        self.key_patterns = {
            "market_data": [
                "market:tick:*",
                "market:l1:*",
                "market:l2:*",
                "market:trade:*",
            ],
            "historical_data": ["historical:*", "replay:*", "simulation:*"],
            "system_metrics": ["metrics:*", "latency:*", "network:*", "status:*"],
        }

    def start(self):
        """Start the Redis cleaner service"""
        if self.running:
            logger.warning("Redis cleaner already running")
            return

        logger.info("🧹 Starting Redis cleaner service")
        self.running = True

        # Test Redis connection
        try:
            self.redis_client.ping()
            logger.info("✅ Redis connection verified")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return False

        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

        logger.info(f"✅ Redis cleaner started with config: {self.config}")
        return True

    def stop(self):
        """Stop the Redis cleaner service"""
        logger.info("🛑 Stopping Redis cleaner service")
        self.running = False

        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)

        logger.info("✅ Redis cleaner stopped")

    def _cleanup_loop(self):
        """Main cleanup loop"""
        while self.running:
            try:
                self._perform_cleanup()
                time.sleep(self.config["cleanup_interval_seconds"])
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                self.stats["cleanup_errors"] += 1
                time.sleep(10)  # Wait before retrying

    def _perform_cleanup(self):
        """Perform cleanup operations"""
        logger.debug("🔄 Running Redis cleanup cycle")

        cleanup_start = time.time()
        keys_processed = 0
        keys_expired = 0

        try:
            # Set TTL for market data keys
            for pattern in self.key_patterns["market_data"]:
                expired = self._set_ttl_for_pattern(
                    pattern, self.config["market_data_ttl_seconds"]
                )
                keys_expired += expired
                keys_processed += self._count_keys_for_pattern(pattern)

            # Set TTL for historical data keys
            for pattern in self.key_patterns["historical_data"]:
                expired = self._set_ttl_for_pattern(
                    pattern, self.config["historical_data_ttl_seconds"]
                )
                keys_expired += expired
                keys_processed += self._count_keys_for_pattern(pattern)

            # Set TTL for system metrics keys
            for pattern in self.key_patterns["system_metrics"]:
                expired = self._set_ttl_for_pattern(
                    pattern, self.config["system_metrics_ttl_seconds"]
                )
                keys_expired += expired
                keys_processed += self._count_keys_for_pattern(pattern)

            # Check memory usage
            memory_info = self._get_memory_info()
            if memory_info["used_memory_mb"] > self.config["memory_threshold_mb"]:
                logger.warning(
                    f"⚠️ Redis memory usage high: {memory_info['used_memory_mb']:.1f}MB"
                )
                self.stats["memory_alerts"] += 1

            # Update stats
            self.stats["keys_processed"] += keys_processed
            self.stats["keys_expired"] += keys_expired
            self.stats["last_cleanup"] = datetime.now()

            cleanup_time = time.time() - cleanup_start
            logger.debug(
                f"✅ Cleanup complete: {keys_processed} keys processed, {keys_expired} expired, {cleanup_time:.2f}s"
            )

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            self.stats["cleanup_errors"] += 1

    def _set_ttl_for_pattern(self, pattern: str, ttl_seconds: int) -> int:
        """Set TTL for keys matching pattern"""
        expired_count = 0

        try:
            # Get keys matching pattern (with limit to prevent memory issues)
            keys = self.redis_client.keys(pattern)

            if len(keys) > self.config["max_keys_per_pattern"]:
                logger.warning(
                    f"⚠️ Pattern {pattern} has {len(keys)} keys (limit: {self.config['max_keys_per_pattern']})"
                )
                keys = keys[: self.config["max_keys_per_pattern"]]

            # Set TTL for each key
            for key in keys:
                try:
                    # Only set TTL if key doesn't already have one
                    current_ttl = self.redis_client.ttl(key)
                    if current_ttl == -1:  # No TTL set
                        self.redis_client.expire(key, ttl_seconds)
                        expired_count += 1
                except Exception as e:
                    logger.debug(f"Error setting TTL for key {key}: {e}")

        except Exception as e:
            logger.error(f"Error processing pattern {pattern}: {e}")

        return expired_count

    def _count_keys_for_pattern(self, pattern: str) -> int:
        """Count keys matching pattern"""
        try:
            return len(self.redis_client.keys(pattern))
        except Exception as e:
            logger.debug(f"Error counting keys for pattern {pattern}: {e}")
            return 0

    def _get_memory_info(self) -> Dict:
        """Get Redis memory usage information"""
        try:
            info = self.redis_client.info("memory")
            return {
                "used_memory_mb": info["used_memory"] / (1024 * 1024),
                "used_memory_peak_mb": info["used_memory_peak"] / (1024 * 1024),
                "used_memory_rss_mb": info["used_memory_rss"] / (1024 * 1024),
                "maxmemory_mb": info.get("maxmemory", 0) / (1024 * 1024)
                if info.get("maxmemory")
                else None,
            }
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            return {"used_memory_mb": 0}

    def get_status(self) -> Dict:
        """Get cleaner service status"""
        memory_info = self._get_memory_info()

        # Count current keys by category
        key_counts = {}
        for category, patterns in self.key_patterns.items():
            total_count = sum(self._count_keys_for_pattern(p) for p in patterns)
            key_counts[category] = total_count

        return {
            "running": self.running,
            "config": self.config,
            "stats": self.stats,
            "memory_info": memory_info,
            "key_counts": key_counts,
            "last_status_check": datetime.now().isoformat(),
        }

    def manual_cleanup(self, pattern: str = None) -> Dict:
        """Trigger manual cleanup for specific pattern or all patterns"""
        logger.info(f"🔧 Manual cleanup triggered for pattern: {pattern or 'ALL'}")

        if pattern:
            # Clean specific pattern
            if pattern in sum(self.key_patterns.values(), []):
                ttl = self.config["market_data_ttl_seconds"]  # Default TTL
                expired = self._set_ttl_for_pattern(pattern, ttl)
                return {"pattern": pattern, "keys_expired": expired}
            else:
                return {"error": f"Pattern {pattern} not recognized"}
        else:
            # Clean all patterns
            self._perform_cleanup()
            return {"message": "Full cleanup performed", "stats": self.stats}

    def emergency_cleanup(self, max_memory_mb: int = 256) -> Dict:
        """Emergency cleanup to reduce memory usage below threshold"""
        logger.warning(
            f"🚨 Emergency cleanup triggered - target memory: {max_memory_mb}MB"
        )

        memory_before = self._get_memory_info()["used_memory_mb"]
        keys_deleted = 0

        # More aggressive cleanup - reduce TTLs
        emergency_ttl = 60  # 1 minute TTL for emergency

        for category, patterns in self.key_patterns.items():
            if memory_before > max_memory_mb:
                for pattern in patterns:
                    keys = self.redis_client.keys(pattern)
                    for key in keys[:1000]:  # Limit to prevent timeout
                        try:
                            self.redis_client.expire(key, emergency_ttl)
                            keys_deleted += 1
                        except Exception as e:
                            logger.debug(f"Error in emergency cleanup for {key}: {e}")

        memory_after = self._get_memory_info()["used_memory_mb"]

        return {
            "memory_before_mb": memory_before,
            "memory_after_mb": memory_after,
            "keys_deleted": keys_deleted,
            "memory_freed_mb": memory_before - memory_after,
        }


def create_redis_cleaner(
    redis_config: Dict, cleanup_config: Dict = None
) -> RedisCleanerService:
    """Factory function to create Redis cleaner service"""
    return RedisCleanerService(redis_config, cleanup_config)


if __name__ == "__main__":
    # Test the Redis cleaner service
    logging.basicConfig(level=logging.INFO)

    redis_config = {"host": "localhost", "port": 6380, "db": 0}

    # Test configuration
    cleanup_config = {
        "market_data_ttl_seconds": 300,  # 5 minutes for testing
        "cleanup_interval_seconds": 30,  # 30 seconds for testing
        "memory_threshold_mb": 100,  # Lower threshold for testing
    }

    cleaner = RedisCleanerService(redis_config, cleanup_config)

    try:
        # Start the service
        if cleaner.start():
            print("✅ Redis cleaner started successfully")

            # Run for a short time
            time.sleep(60)

            # Get status
            status = cleaner.get_status()
            print(f"📊 Status: {json.dumps(status, indent=2, default=str)}")

        else:
            print("❌ Failed to start Redis cleaner")

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")

    finally:
        cleaner.stop()
        print("✅ Redis cleaner stopped")
