#!/usr/bin/env python3
"""
High-Performance Redis Cache Manager for Financial Real-Time Data

Optimized for:
- Microsecond-level performance requirements
- High-frequency financial data caching
- Connection pooling and fault tolerance
- Pub/sub for real-time data distribution
- TTL management and memory optimization
- Comprehensive error handling and monitoring
"""

import redis
import redis.sentinel
import json
import time
import threading
import logging
import asyncio
from typing import Dict, List, Optional, Any, Callable, Union, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
import statistics
from contextlib import contextmanager
import hashlib
import pickle
import gzip
import weakref

logger = logging.getLogger(__name__)


@dataclass
class CacheKey:
    """Structured cache key with namespace and metadata."""
    namespace: str
    key: str
    data_type: str
    symbol: Optional[str] = None
    timestamp: Optional[float] = None
    
    def __str__(self) -> str:
        """Generate Redis key string."""
        parts = [self.namespace, self.data_type]
        if self.symbol:
            parts.append(self.symbol)
        parts.append(self.key)
        return ":".join(parts)
    
    def ttl_key(self) -> str:
        """Generate TTL tracking key."""
        return f"ttl:{self}"


@dataclass
class CacheConfig:
    """Redis cache configuration."""
    # Connection settings
    host: str = 'localhost'
    port: int = 6380
    db: int = 0
    password: Optional[str] = None
    
    # Connection pool settings
    max_connections: int = 50
    connection_pool_timeout: int = 20
    socket_connect_timeout: int = 5
    socket_timeout: int = 5
    
    # Performance settings
    pipeline_batch_size: int = 100
    compression_threshold: int = 1024  # Compress data > 1KB
    use_compression: bool = True
    
    # TTL settings
    default_ttl: int = 3600  # 1 hour
    l1_data_ttl: int = 30    # 30 seconds for L1 quotes
    l2_data_ttl: int = 60    # 1 minute for L2 order book
    tick_data_ttl: int = 300  # 5 minutes for tick data
    metrics_ttl: int = 1800   # 30 minutes for metrics
    
    # Memory management
    memory_threshold_mb: int = 512
    cleanup_interval: int = 300  # 5 minutes
    max_keys_per_pattern: int = 10000
    
    # Pub/Sub settings
    pubsub_pool_size: int = 10
    subscription_timeout: int = 1.0


class RedisConnectionPool:
    """Thread-safe Redis connection pool with health monitoring."""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self.pool = None
        self.sentinel_pool = None
        self._health_check_thread = None
        self._health_check_running = False
        self.last_health_check = 0
        self.connection_errors = 0
        self.lock = threading.RLock()
        
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize Redis connection pool."""
        try:
            # Primary Redis pool
            self.pool = redis.ConnectionPool(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                password=self.config.password,
                max_connections=self.config.max_connections,
                socket_connect_timeout=self.config.socket_connect_timeout,
                socket_timeout=self.config.socket_timeout,
                decode_responses=True,
                health_check_interval=30
            )
            
            # Test connection
            test_client = redis.Redis(connection_pool=self.pool)
            test_client.ping()
            
            logger.info(f"✓ Redis connection pool initialized: {self.config.host}:{self.config.port}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection pool: {e}")
            raise
    
    def get_client(self) -> redis.Redis:
        """Get Redis client from pool."""
        try:
            return redis.Redis(connection_pool=self.pool)
        except Exception as e:
            self.connection_errors += 1
            logger.error(f"Failed to get Redis client: {e}")
            raise
    
    @contextmanager
    def pipeline(self, transaction: bool = True):
        """Get Redis pipeline with context manager."""
        client = self.get_client()
        pipe = client.pipeline(transaction=transaction)
        try:
            yield pipe
        finally:
            pipe.reset()
    
    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        try:
            client = self.get_client()
            start_time = time.time()
            
            # Basic connectivity
            client.ping()
            ping_latency = (time.time() - start_time) * 1000
            
            # Memory info
            memory_info = client.info('memory')
            
            # Connection info
            client_info = client.info('clients')
            
            self.last_health_check = time.time()
            
            return {
                'status': 'healthy',
                'ping_latency_ms': ping_latency,
                'connected_clients': client_info.get('connected_clients', 0),
                'used_memory_mb': memory_info.get('used_memory', 0) / (1024 * 1024),
                'connection_errors': self.connection_errors,
                'last_check': self.last_health_check
            }
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {
                'status': 'unhealthy',
                'error': str(e),
                'connection_errors': self.connection_errors,
                'last_check': time.time()
            }


class RedisCompression:
    """High-performance compression for Redis values."""
    
    @staticmethod
    def compress(data: Any, threshold: int = 1024) -> bytes:
        """Compress data if above threshold."""
        # Serialize data
        if isinstance(data, (dict, list)):
            serialized = json.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            serialized = data.encode('utf-8')
        else:
            serialized = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        
        # Compress if above threshold
        if len(serialized) > threshold:
            compressed = gzip.compress(serialized, compresslevel=1)  # Fast compression
            return b'GZIP:' + compressed
        
        return b'RAW:' + serialized
    
    @staticmethod
    def decompress(data: bytes) -> Any:
        """Decompress Redis data."""
        if data.startswith(b'GZIP:'):
            # Decompress
            compressed_data = data[5:]  # Remove 'GZIP:' prefix
            decompressed = gzip.decompress(compressed_data)
            
            # Try JSON first, then pickle
            try:
                return json.loads(decompressed.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return pickle.loads(decompressed)
        
        elif data.startswith(b'RAW:'):
            # Raw data
            raw_data = data[4:]  # Remove 'RAW:' prefix
            
            # Try JSON first, then pickle
            try:
                return json.loads(raw_data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return pickle.loads(raw_data)
        
        # Legacy support - assume JSON string
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        
        return data


class RedisPubSubManager:
    """High-performance Redis Pub/Sub manager."""
    
    def __init__(self, connection_pool: RedisConnectionPool):
        self.connection_pool = connection_pool
        self.pubsub_clients = {}
        self.subscribers = defaultdict(list)
        self.publisher_client = None
        self.lock = threading.RLock()
        self.running = False
        
    def start(self):
        """Start pub/sub manager."""
        self.publisher_client = self.connection_pool.get_client()
        self.running = True
        logger.info("✓ Redis Pub/Sub manager started")
    
    def stop(self):
        """Stop pub/sub manager."""
        self.running = False
        
        # Close all pubsub clients
        for client in self.pubsub_clients.values():
            try:
                client.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub client: {e}")
        
        self.pubsub_clients.clear()
        self.subscribers.clear()
        
        if self.publisher_client:
            try:
                self.publisher_client.close()
            except Exception:
                pass
        
        logger.info("✓ Redis Pub/Sub manager stopped")
    
    def publish(self, channel: str, data: Any) -> int:
        """Publish data to channel."""
        if not self.running or not self.publisher_client:
            return 0
        
        try:
            # Compress data if needed
            compressed_data = RedisCompression.compress(data)
            
            # Publish
            result = self.publisher_client.publish(channel, compressed_data)
            logger.debug(f"Published to {channel}: {result} subscribers")
            return result
            
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            return 0
    
    def subscribe(self, channel: str, callback: Callable[[str, Any], None]) -> bool:
        """Subscribe to channel with callback."""
        if not self.running:
            return False
        
        try:
            with self.lock:
                # Add callback to subscribers
                self.subscribers[channel].append(callback)
                
                # Create pubsub client if not exists
                if channel not in self.pubsub_clients:
                    client = self.connection_pool.get_client()
                    pubsub = client.pubsub(ignore_subscribe_messages=True)
                    pubsub.subscribe(channel)
                    
                    # Start listening thread
                    thread = threading.Thread(
                        target=self._listen_thread,
                        args=(channel, pubsub),
                        daemon=True
                    )
                    thread.start()
                    
                    self.pubsub_clients[channel] = pubsub
                
                logger.debug(f"Subscribed to channel: {channel}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to subscribe to {channel}: {e}")
            return False
    
    def _listen_thread(self, channel: str, pubsub):
        """Background thread for listening to channel."""
        logger.debug(f"Started listener for channel: {channel}")
        
        try:
            for message in pubsub.listen():
                if not self.running:
                    break
                
                if message['type'] == 'message':
                    try:
                        # Decompress data
                        data = RedisCompression.decompress(message['data'])
                        
                        # Call all subscribers
                        for callback in self.subscribers[channel]:
                            try:
                                callback(channel, data)
                            except Exception as e:
                                logger.error(f"Subscriber callback error: {e}")
                    
                    except Exception as e:
                        logger.error(f"Error processing message on {channel}: {e}")
        
        except Exception as e:
            logger.error(f"Listener thread error for {channel}: {e}")
        
        finally:
            logger.debug(f"Stopped listener for channel: {channel}")


class RedisPerformanceMonitor:
    """Monitor Redis performance and latency."""
    
    def __init__(self):
        self.operation_times = defaultdict(deque)
        self.error_counts = defaultdict(int)
        self.start_time = time.time()
        self.lock = threading.RLock()
    
    def record_operation(self, operation: str, duration_ms: float, success: bool = True):
        """Record operation timing."""
        with self.lock:
            if success:
                self.operation_times[operation].append(duration_ms)
                # Keep only last 1000 measurements
                while len(self.operation_times[operation]) > 1000:
                    self.operation_times[operation].popleft()
            else:
                self.error_counts[operation] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        with self.lock:
            stats = {
                'uptime_seconds': time.time() - self.start_time,
                'operations': {},
                'total_errors': sum(self.error_counts.values())
            }
            
            for operation, times in self.operation_times.items():
                if times:
                    stats['operations'][operation] = {
                        'count': len(times),
                        'avg_ms': statistics.mean(times),
                        'min_ms': min(times),
                        'max_ms': max(times),
                        'p95_ms': statistics.quantiles(times, n=20)[18] if len(times) > 20 else max(times),
                        'p99_ms': statistics.quantiles(times, n=100)[98] if len(times) > 100 else max(times),
                        'errors': self.error_counts[operation]
                    }
            
            return stats


class RedisCacheManager:
    """
    High-performance Redis cache manager for financial real-time data.
    
    Features:
    - Connection pooling with health monitoring
    - High-performance compression
    - Pub/Sub for real-time distribution
    - TTL management and memory optimization
    - Performance monitoring
    - Fault tolerance and error handling
    """
    
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        
        # Core components
        self.connection_pool = RedisConnectionPool(self.config)
        self.pubsub_manager = RedisPubSubManager(self.connection_pool)
        self.performance_monitor = RedisPerformanceMonitor()
        
        # State
        self.running = False
        self.cleanup_thread = None
        self.stats_thread = None
        
        # Metrics
        self.cache_hits = 0
        self.cache_misses = 0
        self.operations_count = 0
        
    def start(self) -> bool:
        """Start cache manager."""
        try:
            # Start pub/sub manager
            self.pubsub_manager.start()
            
            # Start background cleanup
            self.running = True
            self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
            self.cleanup_thread.start()
            
            logger.info("✓ Redis cache manager started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start cache manager: {e}")
            return False
    
    def stop(self):
        """Stop cache manager."""
        self.running = False
        
        # Stop pub/sub
        self.pubsub_manager.stop()
        
        # Wait for threads
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        
        logger.info("✓ Redis cache manager stopped")
    
    # Cache Operations
    
    def set(self, key: Union[str, CacheKey], value: Any, ttl: Optional[int] = None, 
           compress: bool = None) -> bool:
        """Set cache value with optional compression and TTL."""
        start_time = time.time()
        
        try:
            cache_key = str(key) if isinstance(key, CacheKey) else key
            
            # Determine TTL
            if ttl is None:
                ttl = self._get_default_ttl(key)
            
            # Compression
            use_compression = compress if compress is not None else self.config.use_compression
            
            if use_compression:
                data = RedisCompression.compress(value, self.config.compression_threshold)
            else:
                data = json.dumps(value) if not isinstance(value, (str, bytes)) else value
            
            # Set with TTL
            client = self.connection_pool.get_client()
            result = client.setex(cache_key, ttl, data)
            
            # Publish change notification
            self.pubsub_manager.publish(f"cache:set:{cache_key}", {
                'key': cache_key,
                'ttl': ttl,
                'timestamp': time.time()
            })
            
            self.operations_count += 1
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('set', duration_ms, True)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('set', duration_ms, False)
            logger.error(f"Cache set failed for key {key}: {e}")
            return False
    
    def get(self, key: Union[str, CacheKey], decompress: bool = None) -> Optional[Any]:
        """Get cache value with optional decompression."""
        start_time = time.time()
        
        try:
            cache_key = str(key) if isinstance(key, CacheKey) else key
            
            client = self.connection_pool.get_client()
            data = client.get(cache_key)
            
            if data is None:
                self.cache_misses += 1
                duration_ms = (time.time() - start_time) * 1000
                self.performance_monitor.record_operation('get_miss', duration_ms, True)
                return None
            
            # Decompression
            use_decompression = decompress if decompress is not None else self.config.use_compression
            
            if use_decompression:
                if isinstance(data, str):
                    # Convert string back to bytes for decompression
                    data_bytes = data.encode('utf-8')
                    result = RedisCompression.decompress(data_bytes)
                elif isinstance(data, bytes):
                    result = RedisCompression.decompress(data)
                else:
                    result = data
            else:
                # Try JSON decode
                try:
                    result = json.loads(data) if isinstance(data, str) else data
                except json.JSONDecodeError:
                    result = data
            
            self.cache_hits += 1
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('get_hit', duration_ms, True)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('get', duration_ms, False)
            logger.error(f"Cache get failed for key {key}: {e}")
            return None
    
    def mget(self, keys: List[Union[str, CacheKey]]) -> Dict[str, Any]:
        """Get multiple cache values efficiently."""
        start_time = time.time()
        
        try:
            cache_keys = [str(k) if isinstance(k, CacheKey) else k for k in keys]
            
            client = self.connection_pool.get_client()
            values = client.mget(cache_keys)
            
            result = {}
            for key, value in zip(cache_keys, values):
                if value is not None:
                    if self.config.use_compression:
                        if isinstance(value, str):
                            # Convert string back to bytes for decompression
                            value_bytes = value.encode('utf-8')
                            result[key] = RedisCompression.decompress(value_bytes)
                        elif isinstance(value, bytes):
                            result[key] = RedisCompression.decompress(value)
                        else:
                            result[key] = value
                    else:
                        try:
                            result[key] = json.loads(value) if isinstance(value, str) else value
                        except json.JSONDecodeError:
                            result[key] = value
                    self.cache_hits += 1
                else:
                    self.cache_misses += 1
            
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('mget', duration_ms, True)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('mget', duration_ms, False)
            logger.error(f"Cache mget failed: {e}")
            return {}
    
    def pipeline_set(self, data: Dict[Union[str, CacheKey], Any], ttl: Optional[int] = None) -> int:
        """Set multiple values using pipeline for high performance."""
        start_time = time.time()
        
        try:
            with self.connection_pool.pipeline() as pipe:
                for key, value in data.items():
                    cache_key = str(key) if isinstance(key, CacheKey) else key
                    key_ttl = ttl if ttl is not None else self._get_default_ttl(key)
                    
                    # Compress if needed
                    if self.config.use_compression:
                        compressed_value = RedisCompression.compress(value, self.config.compression_threshold)
                    else:
                        compressed_value = json.dumps(value) if not isinstance(value, (str, bytes)) else value
                    
                    pipe.setex(cache_key, key_ttl, compressed_value)
                
                results = pipe.execute()
                successful = sum(1 for r in results if r)
                
                self.operations_count += len(data)
                duration_ms = (time.time() - start_time) * 1000
                self.performance_monitor.record_operation('pipeline_set', duration_ms, True)
                
                return successful
                
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.performance_monitor.record_operation('pipeline_set', duration_ms, False)
            logger.error(f"Pipeline set failed: {e}")
            return 0
    
    # Financial Data Specific Methods
    
    def cache_l1_data(self, symbol: str, l1_data: Dict[str, Any]) -> bool:
        """Cache L1 market data with optimized TTL."""
        key = CacheKey(
            namespace='market',
            data_type='l1',
            symbol=symbol,
            key='latest',
            timestamp=time.time()
        )
        
        return self.set(key, l1_data, ttl=self.config.l1_data_ttl)
    
    def cache_l2_data(self, symbol: str, l2_data: Dict[str, Any]) -> bool:
        """Cache L2 order book data with optimized TTL."""
        key = CacheKey(
            namespace='market',
            data_type='l2',
            symbol=symbol,
            key='orderbook',
            timestamp=time.time()
        )
        
        return self.set(key, l2_data, ttl=self.config.l2_data_ttl)
    
    def cache_tick_data(self, symbol: str, tick_data: Dict[str, Any]) -> bool:
        """Cache tick data with list append."""
        try:
            key = f"market:ticks:{symbol}"
            
            client = self.connection_pool.get_client()
            with client.pipeline() as pipe:
                # Add to list
                pipe.lpush(key, json.dumps(tick_data))
                # Keep only recent ticks
                pipe.ltrim(key, 0, 999)  # Last 1000 ticks
                # Set TTL
                pipe.expire(key, self.config.tick_data_ttl)
                pipe.execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to cache tick data for {symbol}: {e}")
            return False
    
    def get_latest_l1(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get latest L1 data for symbol."""
        key = f"market:l1:{symbol}:latest"
        return self.get(key)
    
    def get_latest_l2(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get latest L2 data for symbol."""
        key = f"market:l2:{symbol}:orderbook"
        return self.get(key)
    
    def get_recent_ticks(self, symbol: str, count: int = 100) -> List[Dict[str, Any]]:
        """Get recent tick data for symbol."""
        try:
            key = f"market:ticks:{symbol}"
            client = self.connection_pool.get_client()
            
            raw_ticks = client.lrange(key, 0, count - 1)
            ticks = []
            
            for raw_tick in raw_ticks:
                try:
                    tick = json.loads(raw_tick)
                    ticks.append(tick)
                except json.JSONDecodeError:
                    continue
            
            return ticks
            
        except Exception as e:
            logger.error(f"Failed to get recent ticks for {symbol}: {e}")
            return []
    
    # Pub/Sub Methods
    
    def publish_market_update(self, symbol: str, data_type: str, data: Any) -> int:
        """Publish market data update."""
        channel = f"market:{data_type}:{symbol}"
        return self.pubsub_manager.publish(channel, data)
    
    def subscribe_market_updates(self, symbol: str, data_type: str, 
                                callback: Callable[[str, Any], None]) -> bool:
        """Subscribe to market data updates."""
        channel = f"market:{data_type}:{symbol}"
        return self.pubsub_manager.subscribe(channel, callback)
    
    # Utility Methods
    
    def _get_default_ttl(self, key: Union[str, CacheKey]) -> int:
        """Get default TTL based on key type."""
        if isinstance(key, CacheKey):
            if key.data_type == 'l1':
                return self.config.l1_data_ttl
            elif key.data_type == 'l2':
                return self.config.l2_data_ttl
            elif key.data_type == 'ticks':
                return self.config.tick_data_ttl
            elif key.data_type == 'metrics':
                return self.config.metrics_ttl
        
        # String key analysis
        key_str = str(key).lower()
        if ':l1:' in key_str:
            return self.config.l1_data_ttl
        elif ':l2:' in key_str:
            return self.config.l2_data_ttl
        elif ':tick' in key_str:
            return self.config.tick_data_ttl
        elif ':metric' in key_str:
            return self.config.metrics_ttl
        
        return self.config.default_ttl
    
    def _cleanup_worker(self):
        """Background cleanup worker."""
        while self.running:
            try:
                time.sleep(self.config.cleanup_interval)
                
                if not self.running:
                    break
                
                # Memory check
                health = self.connection_pool.health_check()
                if health.get('used_memory_mb', 0) > self.config.memory_threshold_mb:
                    logger.warning(f"High memory usage: {health['used_memory_mb']:.1f}MB")
                    self._emergency_cleanup()
                
                # Regular cleanup
                self._cleanup_expired_keys()
                
            except Exception as e:
                logger.error(f"Cleanup worker error: {e}")
    
    def _cleanup_expired_keys(self):
        """Clean up expired keys."""
        try:
            client = self.connection_pool.get_client()
            
            # Get sample of keys
            sample_keys = client.randomkey() 
            if sample_keys:
                # Check TTL and clean if needed
                ttl = client.ttl(sample_keys)
                if ttl == 0:  # Expired
                    client.delete(sample_keys)
                    
        except Exception as e:
            logger.debug(f"Cleanup error: {e}")
    
    def _emergency_cleanup(self):
        """Emergency memory cleanup."""
        try:
            client = self.connection_pool.get_client()
            
            # Delete oldest tick data first
            pattern = "market:ticks:*"
            keys = client.keys(pattern)
            
            # Delete up to 1000 keys
            if keys:
                with client.pipeline() as pipe:
                    for key in keys[:1000]:
                        pipe.delete(key)
                    pipe.execute()
                
                logger.info(f"Emergency cleanup: deleted {min(len(keys), 1000)} tick keys")
                
        except Exception as e:
            logger.error(f"Emergency cleanup failed: {e}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        stats = self.performance_monitor.get_stats()
        
        # Add cache-specific stats
        stats.update({
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate': self.cache_hits / (self.cache_hits + self.cache_misses) if (self.cache_hits + self.cache_misses) > 0 else 0,
            'operations_count': self.operations_count,
            'connection_pool_health': self.connection_pool.health_check()
        })
        
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check."""
        return {
            'status': 'healthy' if self.running else 'stopped',
            'connection_pool': self.connection_pool.health_check(),
            'pubsub_active': self.pubsub_manager.running,
            'performance': self.get_performance_stats(),
            'config': asdict(self.config)
        }


# Singleton instance for global access
_cache_manager_instance = None
_cache_manager_lock = threading.Lock()


def get_cache_manager(config: CacheConfig = None) -> RedisCacheManager:
    """Get singleton cache manager instance."""
    global _cache_manager_instance
    
    with _cache_manager_lock:
        if _cache_manager_instance is None:
            _cache_manager_instance = RedisCacheManager(config)
        
        return _cache_manager_instance


# Convenience functions for common operations

def cache_l1_quote(symbol: str, bid: float, ask: float, bid_size: int, ask_size: int, 
                  timestamp: float = None) -> bool:
    """Cache L1 quote data."""
    manager = get_cache_manager()
    
    l1_data = {
        'symbol': symbol,
        'bid': bid,
        'ask': ask,
        'bid_size': bid_size,
        'ask_size': ask_size,
        'spread': ask - bid,
        'timestamp': timestamp or time.time()
    }
    
    return manager.cache_l1_data(symbol, l1_data)


def cache_trade_tick(symbol: str, price: float, size: int, side: str, 
                    timestamp: float = None) -> bool:
    """Cache trade tick data."""
    manager = get_cache_manager()
    
    tick_data = {
        'symbol': symbol,
        'price': price,
        'size': size,
        'side': side,
        'timestamp': timestamp or time.time()
    }
    
    return manager.cache_tick_data(symbol, tick_data)


if __name__ == "__main__":
    # Example usage and testing
    logging.basicConfig(level=logging.INFO)
    
    # Initialize cache manager
    config = CacheConfig(
        host='localhost',
        port=6380,
        max_connections=20,
        use_compression=True
    )
    
    cache = RedisCacheManager(config)
    
    try:
        # Start cache manager
        if cache.start():
            print("✓ Cache manager started")
            
            # Test caching operations
            test_data = {
                'symbol': 'AAPL',
                'price': 150.25,
                'volume': 1000,
                'timestamp': time.time()
            }
            
            # Set cache
            success = cache.set('test:data', test_data, ttl=60)
            print(f"Set operation: {'✓' if success else '✗'}")
            
            # Get cache
            retrieved = cache.get('test:data')
            print(f"Get operation: {'✓' if retrieved else '✗'}")
            print(f"Retrieved data: {retrieved}")
            
            # Test L1 caching
            success = cache_l1_quote('AAPL', 150.20, 150.25, 100, 200)
            print(f"L1 cache: {'✓' if success else '✗'}")
            
            # Test performance stats
            stats = cache.get_performance_stats()
            print(f"Performance stats: {stats}")
            
            time.sleep(2)
            
        else:
            print("✗ Failed to start cache manager")
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    
    finally:
        cache.stop()
        print("✓ Cache manager stopped")