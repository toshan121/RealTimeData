"""
Multi-Symbol Temporal Orchestrator

Coordinates temporal replay across 2000+ symbols with microsecond precision.
Handles memory-efficient loading, cross-symbol synchronization, and high-throughput streaming.

Architecture: ClickHouse → Temporal Orchestrator → Mock IQFeed Messages → Kafka

Key Features:
- Memory-efficient streaming with sliding time windows
- Perfect temporal sync across all symbols (microsecond precision)
- Configurable playback speed (1x, 10x, 100x real-time)
- Backpressure handling for downstream consumers
- Comprehensive statistics and monitoring
"""

import logging
import threading
import time
import heapq
import gc
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Iterator, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import concurrent.futures
from queue import Queue, Empty, Full
import clickhouse_connect
from clickhouse_connect.driver import Client

from .clickhouse_mock_iqfeed import MockMessage, ClickHouseMockIQFeed
from .exceptions import ProcessingError, DataValidationError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OrchestratorMode(Enum):
    """Orchestrator operation modes."""
    HISTORICAL_REPLAY = "historical_replay"      # Replay exact historical data
    BURST_REPLAY = "burst_replay"               # High-speed replay for testing
    SYNCHRONIZED_REPLAY = "synchronized_replay"  # Cross-symbol synchronized replay


@dataclass
class TemporalWindow:
    """Temporal window for efficient memory management."""
    start_time: datetime
    end_time: datetime
    window_size_minutes: int = 5
    symbols: Set[str] = field(default_factory=set)
    message_count: int = 0
    loaded: bool = False
    
    def contains_time(self, timestamp: datetime) -> bool:
        """Check if timestamp falls within this window."""
        return self.start_time <= timestamp < self.end_time
    
    def __lt__(self, other):
        """For heap ordering by start time."""
        return self.start_time < other.start_time


@dataclass 
class SymbolMetrics:
    """Per-symbol processing metrics."""
    symbol: str
    messages_processed: int = 0
    last_timestamp: Optional[datetime] = None
    bytes_processed: int = 0
    processing_lag_ms: float = 0.0
    queue_depth: int = 0


@dataclass
class OrchestratorStatistics:
    """Comprehensive orchestrator statistics."""
    total_symbols: int = 0
    active_symbols: int = 0
    messages_processed: int = 0
    messages_per_second: float = 0.0
    total_bytes_processed: int = 0
    memory_usage_mb: float = 0.0
    playback_speed: float = 1.0
    temporal_drift_ms: float = 0.0
    queue_utilization: float = 0.0
    symbol_metrics: Dict[str, SymbolMetrics] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    current_time: Optional[datetime] = None
    uptime_seconds: float = 0.0


class MultiSymbolTemporalOrchestrator:
    """
    Orchestrates temporal replay across 2000+ symbols with perfect synchronization.
    
    Uses sliding time windows and memory-efficient processing to handle large-scale
    historical data replay while maintaining microsecond temporal precision.
    """
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 8123,
        database: str = 'l2_market_data',
        username: str = 'l2_user',
        password: str = 'l2_secure_pass',
        mode: OrchestratorMode = OrchestratorMode.HISTORICAL_REPLAY,
        playback_speed: float = 1.0,
        window_size_minutes: int = 5,
        max_memory_mb: int = 2048,
        output_queue_size: int = 100000,
        worker_threads: int = 8
    ):
        """
        Initialize multi-symbol temporal orchestrator.
        
        Args:
            host: ClickHouse host
            port: ClickHouse port
            database: Database name
            username: Database username
            password: Database password
            mode: Orchestrator mode
            playback_speed: Playback speed multiplier
            window_size_minutes: Time window size for memory management
            max_memory_mb: Maximum memory usage limit
            output_queue_size: Output message queue size
            worker_threads: Number of worker threads for data loading
        """
        # Connection config
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        
        # Orchestrator config
        self.mode = mode
        self.playback_speed = playback_speed
        self.window_size_minutes = window_size_minutes
        self.max_memory_mb = max_memory_mb
        self.output_queue_size = output_queue_size
        self.worker_threads = worker_threads
        
        # ClickHouse client
        self._client: Optional[Client] = None
        self._connected = False
        
        # Temporal coordination
        self._time_windows: List[TemporalWindow] = []
        self._current_window_index: int = 0
        self._message_heap: List[MockMessage] = []
        self._heap_lock = threading.Lock()
        
        # Output streaming
        self._output_queue: Queue = Queue(maxsize=output_queue_size)
        self._running = False
        self._orchestrator_thread: Optional[threading.Thread] = None
        
        # Worker pool for parallel data loading
        self._worker_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._loading_queue: Queue = Queue(maxsize=worker_threads * 2)
        
        # Statistics and monitoring  
        self._stats = OrchestratorStatistics()
        self._stats_lock = threading.Lock()
        self._last_stats_update = time.time()
        
        # Symbol management
        self._target_symbols: Set[str] = set()
        self._symbol_last_message: Dict[str, datetime] = {}
        
        # Replay timing
        self._replay_start_time: Optional[datetime] = None
        self._data_start_time: Optional[datetime] = None
        
        logger.info(f"Multi-symbol temporal orchestrator initialized (mode: {mode.value}, speed: {playback_speed}x)")
    
    def connect(self) -> bool:
        """Connect to ClickHouse and initialize orchestrator."""
        try:
            logger.info(f"Connecting orchestrator to ClickHouse at {self.host}:{self.port}")
            
            # Create ClickHouse client
            self._client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                connect_timeout=30,
                send_receive_timeout=300,
                interface='http',
                compress=True,
                settings={
                    'max_execution_time': 600,
                    'max_memory_usage': self.max_memory_mb * 1024 * 1024,
                    'max_threads': self.worker_threads,
                    'use_client_time_zone': False
                }
            )
            
            # Test connection
            result = self._client.query("SELECT 1 as test")
            if not (result.result_rows and result.result_rows[0][0] == 1):
                raise ProcessingError("Connection test failed", "orchestrator_connection")
            
            self._connected = True
            
            # Initialize worker pool
            self._worker_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.worker_threads,
                thread_name_prefix="orchestrator-worker"
            )
            
            logger.info("Multi-symbol orchestrator connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect orchestrator: {e}")
            return False
    
    def disconnect(self):
        """Disconnect and cleanup resources."""
        logger.info("Disconnecting multi-symbol orchestrator")
        
        # Stop orchestrator
        self.stop()
        
        # Shutdown worker pool
        if self._worker_pool:
            self._worker_pool.shutdown(wait=True)
            self._worker_pool = None
        
        # Close ClickHouse client
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"Error closing ClickHouse client: {e}")
            finally:
                self._client = None
                self._connected = False
        
        logger.info("Multi-symbol orchestrator disconnected")
    
    def setup_replay(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        data_types: List[str] = ['trades', 'quotes', 'l2_updates']
    ) -> bool:
        """
        Setup temporal replay for specified symbols and date range.
        
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
            
            self._target_symbols = set(symbols)
            
            # Create temporal windows
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            
            self._time_windows = []
            current_time = start_dt
            
            while current_time < end_dt:
                window_end = min(current_time + timedelta(minutes=self.window_size_minutes), end_dt)
                
                window = TemporalWindow(
                    start_time=current_time,
                    end_time=window_end,
                    window_size_minutes=self.window_size_minutes,
                    symbols=self._target_symbols.copy()
                )
                
                self._time_windows.append(window)
                current_time = window_end
            
            logger.info(f"Created {len(self._time_windows)} temporal windows")
            
            # Initialize statistics
            with self._stats_lock:
                self._stats.total_symbols = len(symbols)
                self._stats.playback_speed = self.playback_speed
                self._stats.start_time = datetime.now(timezone.utc)
                
                # Initialize symbol metrics
                for symbol in symbols:
                    self._stats.symbol_metrics[symbol] = SymbolMetrics(symbol=symbol)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup replay: {e}")
            return False
    
    def start(self) -> bool:
        """Start the temporal orchestrator."""
        if not self._connected:
            logger.error("Cannot start orchestrator: not connected to ClickHouse")
            return False
        
        if not self._time_windows:
            logger.error("Cannot start orchestrator: no temporal windows configured")
            return False
        
        logger.info("Starting multi-symbol temporal orchestrator")
        
        self._running = True
        self._current_window_index = 0
        self._replay_start_time = datetime.now()
        
        # Start orchestrator thread
        self._orchestrator_thread = threading.Thread(
            target=self._orchestrator_loop,
            name="temporal-orchestrator",
            daemon=True
        )
        self._orchestrator_thread.start()
        
        logger.info("Multi-symbol temporal orchestrator started")
        return True
    
    def stop(self):
        """Stop the temporal orchestrator."""
        logger.info("Stopping multi-symbol temporal orchestrator")
        
        self._running = False
        
        # Wait for orchestrator thread
        if self._orchestrator_thread and self._orchestrator_thread.is_alive():
            self._orchestrator_thread.join(timeout=10.0)
        
        # Clear queues and heaps
        try:
            while not self._output_queue.empty():
                self._output_queue.get_nowait()
        except Empty:
            pass
        
        with self._heap_lock:
            self._message_heap.clear()
        
        logger.info("Multi-symbol temporal orchestrator stopped")
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get next temporally-ordered message from orchestrator."""
        try:
            return self._output_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive orchestrator statistics."""
        with self._stats_lock:
            current_time = datetime.now(timezone.utc)
            if self._stats.start_time:
                self._stats.uptime_seconds = (current_time - self._stats.start_time).total_seconds()
            
            # Calculate messages per second
            if self._stats.uptime_seconds > 0:
                self._stats.messages_per_second = self._stats.messages_processed / self._stats.uptime_seconds
            
            # Calculate queue utilization
            self._stats.queue_utilization = self._output_queue.qsize() / self.output_queue_size
            
            # Count active symbols
            self._stats.active_symbols = len([
                metric for metric in self._stats.symbol_metrics.values()
                if metric.last_timestamp and 
                (current_time - metric.last_timestamp.replace(tzinfo=timezone.utc)).total_seconds() < 60
            ])
            
            return {
                'total_symbols': self._stats.total_symbols,
                'active_symbols': self._stats.active_symbols,
                'messages_processed': self._stats.messages_processed,
                'messages_per_second': self._stats.messages_per_second,
                'total_bytes_processed': self._stats.total_bytes_processed,
                'memory_usage_mb': self._stats.memory_usage_mb,
                'playback_speed': self._stats.playback_speed,
                'temporal_drift_ms': self._stats.temporal_drift_ms,
                'queue_utilization': self._stats.queue_utilization,
                'uptime_seconds': self._stats.uptime_seconds,
                'current_window': self._current_window_index,
                'total_windows': len(self._time_windows),
                'heap_size': len(self._message_heap),
                'output_queue_size': self._output_queue.qsize(),
                'running': self._running
            }
    
    def _orchestrator_loop(self):
        """Main orchestrator loop for temporal coordination."""
        logger.info("Temporal orchestrator loop started")
        
        try:
            while self._running and self._current_window_index < len(self._time_windows):
                # Load current window if needed
                current_window = self._time_windows[self._current_window_index]
                
                if not current_window.loaded:
                    self._load_window_data(current_window)
                    current_window.loaded = True
                
                # Process messages from heap
                messages_processed = self._process_message_heap()
                
                if messages_processed == 0:
                    # Move to next window
                    self._current_window_index += 1
                    
                    # Preload next window
                    if self._current_window_index < len(self._time_windows):
                        next_window = self._time_windows[self._current_window_index]
                        if not next_window.loaded:
                            self._preload_window_async(next_window)
                    
                    # Garbage collect to free memory
                    gc.collect()
                
                # Update statistics periodically
                if time.time() - self._last_stats_update > 1.0:
                    self._update_statistics()
                    self._last_stats_update = time.time()
                
                # Small sleep to prevent busy waiting
                if messages_processed == 0:
                    time.sleep(0.001)
        
        except Exception as e:
            logger.error(f"Error in orchestrator loop: {e}")
        
        logger.info("Temporal orchestrator loop stopped")
    
    def _load_window_data(self, window: TemporalWindow):
        """Load data for a temporal window."""
        try:
            logger.info(f"Loading window {window.start_time} to {window.end_time}")
            
            start_time = time.time()
            messages_loaded = 0
            
            # Load data for each symbol in parallel
            futures = []
            
            for symbol in window.symbols:
                if self._running:
                    future = self._worker_pool.submit(
                        self._load_symbol_window_data,
                        symbol,
                        window.start_time,
                        window.end_time
                    )
                    futures.append(future)
            
            # Collect results
            for future in concurrent.futures.as_completed(futures, timeout=60.0):
                try:
                    symbol_messages = future.result()
                    messages_loaded += len(symbol_messages)
                    
                    # Add to heap with proper ordering
                    with self._heap_lock:
                        for message in symbol_messages:
                            heapq.heappush(self._message_heap, message)
                
                except Exception as e:
                    logger.warning(f"Failed to load symbol data: {e}")
            
            load_time = time.time() - start_time
            window.message_count = messages_loaded
            
            logger.info(f"Loaded {messages_loaded} messages for window in {load_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Failed to load window data: {e}")
    
    def _load_symbol_window_data(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[MockMessage]:
        """Load data for a single symbol within a time window."""
        messages = []
        
        try:
            # Create a separate ClickHouse client for this thread
            client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                connect_timeout=30,
                send_receive_timeout=300,
                interface='http',
                compress=True
            )
            
            # Query ClickHouse for symbol data in time window
            date_filter = f"date >= '{start_time.date()}' AND date <= '{end_time.date()}'"
            time_filter = f"timestamp >= '{start_time}' AND timestamp < '{end_time}'"
            
            # Load trades
            trades_query = f"""
                SELECT symbol, timestamp, trade_price, trade_size, total_volume,
                       trade_market_center, trade_conditions, tick_id, bid_price, ask_price
                FROM trades
                WHERE symbol = '{symbol}'
                AND {date_filter}
                AND {time_filter}
                ORDER BY timestamp, tick_id
                LIMIT 50000
            """
            
            trades_result = client.query(trades_query)
            for row in trades_result.result_rows:
                timestamp_str = row[1].strftime('%Y%m%d%H%M%S%f')[:-3]
                raw_message = (f"T,{row[0]},{timestamp_str},{row[2]:.4f},{row[3]},"
                              f"{row[4]},{row[5]},{row[6]},{row[7]},{row[8]:.4f},{row[9]:.4f}")
                
                messages.append(MockMessage(
                    timestamp=row[1],
                    symbol=row[0],
                    message_type='T',
                    raw_message=raw_message,
                    tick_id=row[7]
                ))
            
            # Load quotes
            quotes_query = f"""
                SELECT symbol, timestamp, bid_price, bid_size, ask_price, ask_size,
                       bid_market_center, ask_market_center, tick_id
                FROM quotes
                WHERE symbol = '{symbol}'
                AND {date_filter}
                AND {time_filter}
                ORDER BY timestamp, tick_id
                LIMIT 50000
            """
            
            quotes_result = client.query(quotes_query)
            for row in quotes_result.result_rows:
                timestamp_str = row[1].strftime('%Y%m%d%H%M%S%f')[:-3]
                raw_message = (f"Q,{row[0]},{timestamp_str},{row[2]:.4f},{row[3]},"
                              f"{row[4]:.4f},{row[5]},{row[6]},{row[7]},{row[8]}")
                
                messages.append(MockMessage(
                    timestamp=row[1],
                    symbol=row[0],
                    message_type='Q',
                    raw_message=raw_message,
                    tick_id=row[8]
                ))
            
            # Load L2 updates
            l2_query = f"""
                SELECT symbol, timestamp, level, market_maker, operation, side,
                       price, size, tick_id
                FROM l2_updates
                WHERE symbol = '{symbol}'
                AND {date_filter}
                AND {time_filter}
                ORDER BY timestamp, tick_id
                LIMIT 50000
            """
            
            l2_result = client.query(l2_query)
            for row in l2_result.result_rows:
                timestamp_str = row[1].strftime('%Y%m%d%H%M%S%f')[:-3]
                raw_message = (f"U,{row[0]},{timestamp_str},{row[5]},{row[2]},{row[3]},"
                              f"{row[6]:.4f},{row[7]},{row[4]}")
                
                messages.append(MockMessage(
                    timestamp=row[1],
                    symbol=row[0],
                    message_type='U',
                    raw_message=raw_message,
                    tick_id=row[8]
                ))
            
            # Close the per-thread client
            client.close()
            
            # Sort messages by timestamp for this symbol
            messages.sort(key=lambda x: (x.timestamp, x.tick_id))
            
        except Exception as e:
            logger.warning(f"Failed to load data for {symbol}: {e}")
        
        return messages
    
    def _process_message_heap(self) -> int:
        """Process messages from the temporal heap."""
        messages_processed = 0
        
        with self._heap_lock:
            while self._message_heap and self._running:
                # Peek at next message
                next_message = self._message_heap[0]
                
                # Calculate timing for temporal sync
                if self._data_start_time is None:
                    self._data_start_time = next_message.timestamp
                
                # Check if it's time to send this message
                data_elapsed = (next_message.timestamp - self._data_start_time).total_seconds()
                target_real_elapsed = data_elapsed / self.playback_speed
                actual_elapsed = (datetime.now() - self._replay_start_time).total_seconds()
                
                if target_real_elapsed > actual_elapsed:
                    # Too early - wait
                    break
                
                # Pop message from heap
                message = heapq.heappop(self._message_heap)
                
                # Create output message
                output_message = {
                    'timestamp': message.timestamp.isoformat(),
                    'symbol': message.symbol,
                    'message_type': message.message_type,
                    'raw_message': message.raw_message,
                    'tick_id': message.tick_id
                }
                
                # Try to put in output queue
                try:
                    self._output_queue.put_nowait(output_message)
                    messages_processed += 1
                    
                    # Update symbol metrics
                    with self._stats_lock:
                        self._stats.messages_processed += 1
                        if message.symbol in self._stats.symbol_metrics:
                            metric = self._stats.symbol_metrics[message.symbol]
                            metric.messages_processed += 1
                            metric.last_timestamp = message.timestamp
                            metric.bytes_processed += len(message.raw_message)
                
                except Full:
                    # Queue full - put message back and break
                    heapq.heappush(self._message_heap, message)
                    break
        
        return messages_processed
    
    def _preload_window_async(self, window: TemporalWindow):
        """Asynchronously preload next window data."""
        if self._worker_pool:
            self._worker_pool.submit(self._load_window_data, window)
    
    def _update_statistics(self):
        """Update comprehensive statistics."""
        with self._stats_lock:
            # Update memory usage estimate
            heap_size_mb = len(self._message_heap) * 0.001  # Rough estimate
            self._stats.memory_usage_mb = heap_size_mb
            
            # Calculate temporal drift
            if self._data_start_time and self._replay_start_time:
                expected_time = self._replay_start_time + timedelta(
                    seconds=(datetime.now() - self._replay_start_time).total_seconds() * self.playback_speed
                )
                if self._stats.current_time:
                    drift = (expected_time - self._stats.current_time).total_seconds() * 1000
                    self._stats.temporal_drift_ms = drift
    
    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._running
    
    def get_symbol_metrics(self) -> Dict[str, Any]:
        """Get detailed per-symbol metrics."""
        with self._stats_lock:
            return {
                symbol: {
                    'messages_processed': metric.messages_processed,
                    'last_timestamp': metric.last_timestamp.isoformat() if metric.last_timestamp else None,
                    'bytes_processed': metric.bytes_processed,
                    'processing_lag_ms': metric.processing_lag_ms,
                    'queue_depth': metric.queue_depth
                }
                for symbol, metric in self._stats.symbol_metrics.items()
            }


def main():
    """Test the multi-symbol temporal orchestrator."""
    logger.info("Testing Multi-Symbol Temporal Orchestrator")
    
    # Create orchestrator
    orchestrator = MultiSymbolTemporalOrchestrator(
        playback_speed=10.0,  # 10x speed for testing
        window_size_minutes=1,  # Small windows for testing
        max_memory_mb=512
    )
    
    # Connect
    if not orchestrator.connect():
        logger.error("Failed to connect to ClickHouse")
        return
    
    try:
        # Setup replay for a few test symbols
        test_symbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
        success = orchestrator.setup_replay(
            symbols=test_symbols,
            start_date='2025-07-29',
            end_date='2025-07-29'
        )
        
        if not success:
            logger.error("Failed to setup replay")
            return
        
        # Start orchestrator
        if not orchestrator.start():
            logger.error("Failed to start orchestrator")
            return
        
        # Process messages for testing
        message_count = 0
        start_time = time.time()
        
        while orchestrator.is_running() and message_count < 1000:
            message = orchestrator.get_next_message(timeout=0.1)
            if message:
                message_count += 1
                if message_count % 100 == 0:
                    stats = orchestrator.get_statistics()
                    logger.info(f"Processed {message_count} messages, "
                              f"Speed: {stats['messages_per_second']:.1f} msg/s, "
                              f"Queue: {stats['output_queue_size']}")
        
        # Print final statistics
        stats = orchestrator.get_statistics()
        logger.info(f"Final statistics: {stats}")
        
        # Print symbol metrics
        symbol_metrics = orchestrator.get_symbol_metrics()
        for symbol, metrics in list(symbol_metrics.items())[:5]:
            logger.info(f"Symbol {symbol}: {metrics}")
    
    finally:
        orchestrator.disconnect()


if __name__ == "__main__":
    main()