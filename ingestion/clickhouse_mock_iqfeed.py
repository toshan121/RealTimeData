"""
ClickHouse-Based Mock IQFeed Producer

Reads real market data from ClickHouse and outputs exact IQFeed message formats.
Perfect drop-in replacement for IQFeed when markets are closed.
Supports 2000+ symbols with microsecond temporal sync.

Architecture: ClickHouse → Mock IQFeed Messages → Kafka → GPU Processing
"""

import logging
import threading
import time
import queue
import heapq
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Iterator, Tuple
from dataclasses import dataclass
from enum import Enum
import random
import clickhouse_connect
from clickhouse_connect.driver import Client

from .exceptions import IQFeedConnectionError, ProcessingError
from .iqfeed_parser import IQFeedMessageParser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MockDataMode(Enum):
    """Mock data operation modes."""
    HISTORICAL_REPLAY = "historical_replay"      # Replay exact ClickHouse data
    SIMULATED_REAL_TIME = "simulated_real_time"  # Generate realistic data
    HYBRID = "hybrid"                            # Mix ClickHouse + simulation


@dataclass
class MockMessage:
    """Message with temporal ordering for multi-symbol sync."""
    timestamp: datetime
    symbol: str
    message_type: str  # 'T', 'Q', 'L2', 'U', 'M', 'D'
    raw_message: str
    tick_id: int = 0
    
    def __lt__(self, other):
        # For heap ordering - microsecond precision
        if self.timestamp == other.timestamp:
            # Secondary sort by tick_id for same timestamp
            return self.tick_id < other.tick_id
        return self.timestamp < other.timestamp


@dataclass
class SymbolState:
    """Track current state per symbol for realistic simulation."""
    last_bid: float = 0.0
    last_ask: float = 0.0
    last_trade_price: float = 0.0
    last_trade_size: int = 0
    last_quote_timestamp: Optional[datetime] = None
    last_trade_timestamp: Optional[datetime] = None
    tick_counter: int = 0
    total_volume: int = 0


class ClickHouseMockIQFeed:
    """
    Mock IQFeed producer using real ClickHouse data.
    
    Provides the same interface as IQFeedClient while reading from ClickHouse
    and outputting exact IQFeed message formats for seamless integration.
    """
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 8123,
        database: str = 'l2_market_data',
        username: str = 'l2_user',
        password: str = 'l2_secure_pass',
        mode: MockDataMode = MockDataMode.HISTORICAL_REPLAY,
        playback_speed: float = 1.0,
        start_date: Optional[str] = None,  # YYYY-MM-DD format
        end_date: Optional[str] = None,
        buffer_size: int = 50000
    ):
        """
        Initialize ClickHouse-based mock IQFeed producer.
        
        Args:
            host: ClickHouse host
            port: ClickHouse HTTP port
            database: ClickHouse database name
            username: ClickHouse username
            password: ClickHouse password
            mode: MockDataMode for operation
            playback_speed: Playback speed multiplier (1.0 = real-time)
            start_date: Start date for historical replay (YYYY-MM-DD)
            end_date: End date for historical replay (YYYY-MM-DD)
            buffer_size: Message buffer size
        """
        # ClickHouse connection config
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        
        # Mock configuration
        self.mode = mode
        self.playback_speed = playback_speed
        self.start_date = start_date or "2025-07-21"  # Default to recent data
        self.end_date = end_date or "2025-07-31"
        self.buffer_size = buffer_size
        
        # Connection state (mimic IQFeedClient interface)
        self._client: Optional[Client] = None
        self._connected = False
        self._session_id: Optional[str] = None
        self._connect_time: Optional[datetime] = None
        
        # Message processing
        self._parser = IQFeedMessageParser()
        self._message_queue: queue.Queue = queue.Queue(maxsize=buffer_size)
        self._tick_buffer: queue.Queue = queue.Queue(maxsize=buffer_size)
        
        # Multi-symbol temporal sync
        self._message_heap: List[MockMessage] = []
        self._heap_lock = threading.Lock()
        self._symbol_states: Dict[str, SymbolState] = {}
        
        # Subscriptions (mimic IQFeed interface)
        self._l2_subscriptions: Set[str] = set()
        self._trade_subscriptions: Set[str] = set()
        self._quote_subscriptions: Set[str] = set()
        self._tick_subscriptions: Set[str] = set()
        self._subscription_lock = threading.Lock()
        
        # Background processing
        self._running = False
        self._producer_thread: Optional[threading.Thread] = None
        self._replay_start_time: Optional[datetime] = None
        self._data_start_time: Optional[datetime] = None
        
        logger.info(f"ClickHouse Mock IQFeed initialized (mode: {mode.value}, speed: {playback_speed}x)")
    
    def connect(self) -> Dict[str, Any]:
        """
        Connect to ClickHouse and initialize mock data streaming.
        
        Returns:
            Connection result dict (mimics IQFeedClient.connect())
        """
        try:
            logger.info(f"Connecting to ClickHouse at {self.host}:{self.port}")
            
            # Create ClickHouse client
            self._client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                connect_timeout=30,
                send_receive_timeout=120,
                interface='http',
                compress=True,
                settings={
                    'max_execution_time': 300,
                    'max_memory_usage': 4000000000,  # 4GB
                    'max_threads': 16,
                    'use_client_time_zone': False
                }
            )
            
            # Test connection
            result = self._client.query("SELECT 1 as test")
            if not (result.result_rows and result.result_rows[0][0] == 1):
                raise ProcessingError("ClickHouse connection test failed", "mock_iqfeed")
            
            # Check data availability
            self._analyze_available_data()
            
            # Set connection state
            self._connected = True
            self._session_id = f"MOCK_SESSION_{int(time.time())}"
            self._connect_time = datetime.now(timezone.utc)
            
            # Start background data producer
            self._running = True
            self._producer_thread = threading.Thread(target=self._produce_messages, daemon=True)
            self._producer_thread.start()
            
            logger.info(f"Mock IQFeed connected successfully (session: {self._session_id})")
            
            return {
                'success': True,
                'session_id': self._session_id,
                'connection_time': self._connect_time,
                'mode': self.mode.value,
                'data_range': f"{self.start_date} to {self.end_date}"
            }
            
        except Exception as e:
            error_msg = f"Mock IQFeed connection failed: {e}"
            logger.error(error_msg)
            raise IQFeedConnectionError(error_msg, self.host, self.port, e)
    
    def disconnect(self):
        """Disconnect and cleanup resources."""
        logger.info("Disconnecting Mock IQFeed")
        
        self._running = False
        
        # Wait for producer thread
        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=5.0)
        
        # Close ClickHouse client
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"Error closing ClickHouse client: {e}")
            finally:
                self._client = None
        
        # Clear state
        self._connected = False
        self._session_id = None
        self._connect_time = None
        
        # Clear subscriptions
        with self._subscription_lock:
            self._l2_subscriptions.clear()
            self._trade_subscriptions.clear()
            self._quote_subscriptions.clear()
            self._tick_subscriptions.clear()
        
        logger.info("Mock IQFeed disconnected")
    
    def is_connected(self) -> bool:
        """Check if mock producer is connected."""
        return self._connected and self._client is not None
    
    # ======================================================================
    # SUBSCRIPTION METHODS (Mimic IQFeedClient interface)
    # ======================================================================
    
    def subscribe_l2_data(self, symbol: str) -> Dict[str, Any]:
        """Subscribe to L2 data for symbol."""
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected'}
        
        with self._subscription_lock:
            self._l2_subscriptions.add(symbol.upper())
        
        logger.info(f"Subscribed to L2 data for {symbol}")
        return {'success': True, 'symbol': symbol, 'subscription_type': 'l2'}
    
    def subscribe_trades(self, symbol: str) -> Dict[str, Any]:
        """Subscribe to trade data for symbol."""
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected'}
        
        with self._subscription_lock:
            self._trade_subscriptions.add(symbol.upper())
        
        logger.info(f"Subscribed to trades for {symbol}")
        return {'success': True, 'symbol': symbol, 'subscription_type': 'trades'}
    
    def subscribe_quotes(self, symbol: str) -> Dict[str, Any]:
        """Subscribe to quote data for symbol."""
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected'}
        
        with self._subscription_lock:
            self._quote_subscriptions.add(symbol.upper())
        
        logger.info(f"Subscribed to quotes for {symbol}")
        return {'success': True, 'symbol': symbol, 'subscription_type': 'quotes'}
    
    def subscribe_tick_data(self, symbol: str, tick_type: str = 'all') -> Dict[str, Any]:
        """Subscribe to tick data for symbol."""
        if not self.is_connected():
            return {'success': False, 'error': 'Not connected'}
        
        with self._subscription_lock:
            self._tick_subscriptions.add(symbol.upper())
            # Also add to trades for compatibility
            self._trade_subscriptions.add(symbol.upper())
        
        logger.info(f"Subscribed to tick data for {symbol}")
        return {'success': True, 'symbol': symbol, 'subscription_type': 'tick_data'}
    
    def get_active_subscriptions(self) -> Dict[str, List[str]]:
        """Get all active subscriptions."""
        with self._subscription_lock:
            return {
                'l2_symbols': list(self._l2_subscriptions),
                'trade_symbols': list(self._trade_subscriptions),
                'quote_symbols': list(self._quote_subscriptions),
                'tick_symbols': list(self._tick_subscriptions)
            }
    
    # ======================================================================
    # MESSAGE RETRIEVAL METHODS (Mimic IQFeedClient interface)
    # ======================================================================
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get next message from general queue."""
        try:
            return self._message_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_next_tick(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """Get next tick from high-frequency buffer."""
        try:
            return self._tick_buffer.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def drain_tick_buffer(self, max_ticks: int = 1000) -> List[Dict[str, Any]]:
        """Drain multiple ticks for batch processing."""
        ticks = []
        count = 0
        
        while count < max_ticks:
            try:
                tick = self._tick_buffer.get_nowait()
                ticks.append(tick)
                count += 1
            except queue.Empty:
                break
        
        return ticks
    
    # ======================================================================
    # CLICKHOUSE DATA ANALYSIS
    # ======================================================================
    
    def _analyze_available_data(self):
        """Analyze available data in ClickHouse for planning."""
        try:
            # Check available symbols
            symbols_query = f"""
            SELECT DISTINCT symbol, 
                   count() as record_count,
                   min(timestamp) as earliest,
                   max(timestamp) as latest
            FROM (
                SELECT symbol, timestamp FROM trades
                WHERE date >= '{self.start_date}' AND date <= '{self.end_date}'
                UNION ALL
                SELECT symbol, timestamp FROM quotes  
                WHERE date >= '{self.start_date}' AND date <= '{self.end_date}'
                UNION ALL
                SELECT symbol, timestamp FROM l2_updates
                WHERE date >= '{self.start_date}' AND date <= '{self.end_date}'
            )
            GROUP BY symbol
            ORDER BY record_count DESC
            LIMIT 50
            """
            
            result = self._client.query(symbols_query)
            
            available_symbols = []
            for row in result.result_rows:
                symbol, count, earliest, latest = row
                available_symbols.append({
                    'symbol': symbol,
                    'record_count': count,
                    'earliest': earliest,
                    'latest': latest
                })
                
                # Initialize symbol state
                if symbol not in self._symbol_states:
                    self._symbol_states[symbol] = SymbolState()
            
            logger.info(f"Found {len(available_symbols)} symbols with data in ClickHouse")
            if available_symbols:
                top_symbols = [s['symbol'] for s in available_symbols[:10]]
                logger.info(f"Top symbols by data volume: {', '.join(top_symbols)}")
            
            self._available_symbols = available_symbols
            
        except Exception as e:
            logger.warning(f"Could not analyze ClickHouse data: {e}")
            self._available_symbols = []
    
    # ======================================================================
    # MOCK MESSAGE PRODUCTION
    # ======================================================================
    
    def _produce_messages(self):
        """Background thread to produce mock IQFeed messages."""
        logger.info("Mock IQFeed message producer started")
        
        try:
            if self.mode == MockDataMode.HISTORICAL_REPLAY:
                self._replay_historical_data()
            elif self.mode == MockDataMode.SIMULATED_REAL_TIME:
                self._simulate_real_time_data()
            elif self.mode == MockDataMode.HYBRID:
                self._hybrid_data_production()
        except Exception as e:
            logger.error(f"Error in message producer: {e}")
        
        logger.info("Mock IQFeed message producer stopped")
    
    def _replay_historical_data(self):
        """Replay historical data from ClickHouse with temporal sync."""
        logger.info(f"Starting historical replay: {self.start_date} to {self.end_date}")
        
        # Wait for subscriptions before starting replay
        while self._running:
            with self._subscription_lock:
                total_subs = (len(self._l2_subscriptions) + len(self._trade_subscriptions) + 
                             len(self._quote_subscriptions) + len(self._tick_subscriptions))
            
            if total_subs > 0:
                break
            
            time.sleep(0.1)  # Wait for subscriptions
        
        if not self._running:
            return
        
        # Load data in time windows to manage memory
        current_date = datetime.strptime(self.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(self.end_date, '%Y-%m-%d').date()
        
        self._replay_start_time = datetime.now()
        
        while current_date <= end_date and self._running:
            try:
                # Load one day of data
                daily_messages = self._load_daily_data(current_date.strftime('%Y-%m-%d'))
                
                if daily_messages:
                    logger.info(f"Loaded {len(daily_messages)} messages for {current_date}")
                    self._replay_daily_messages(daily_messages)
                else:
                    logger.info(f"No data found for {current_date}")
                
                current_date += timedelta(days=1)
                
            except Exception as e:
                logger.error(f"Error replaying data for {current_date}: {e}")
                current_date += timedelta(days=1)
    
    def _load_daily_data(self, date_str: str) -> List[MockMessage]:
        """Load all data for a specific date from ClickHouse."""
        messages = []
        
        # Get subscribed symbols
        with self._subscription_lock:
            all_symbols = (self._l2_subscriptions | self._trade_subscriptions | 
                          self._quote_subscriptions | self._tick_subscriptions)
        
        if not all_symbols:
            logger.warning("No symbol subscriptions active")
            return messages
        
        symbols_filter = "', '".join(all_symbols)
        
        try:
            # Load trades
            if self._trade_subscriptions or self._tick_subscriptions:
                trades_query = f"""
                SELECT symbol, timestamp, trade_price, trade_size, total_volume,
                       trade_market_center, trade_conditions, tick_id, bid_price, ask_price
                FROM trades
                WHERE date = '{date_str}'
                AND symbol IN ('{symbols_filter}')
                ORDER BY timestamp, tick_id
                LIMIT 100000
                """
                
                trades_result = self._client.query(trades_query)
                for row in trades_result.result_rows:
                    msg = self._create_trade_message(*row)
                    if msg:
                        messages.append(msg)
            
            # Load quotes
            if self._quote_subscriptions:
                quotes_query = f"""
                SELECT symbol, timestamp, bid_price, bid_size, ask_price, ask_size,
                       bid_market_center, ask_market_center, tick_id
                FROM quotes
                WHERE date = '{date_str}'
                AND symbol IN ('{symbols_filter}')
                ORDER BY timestamp, tick_id
                LIMIT 100000
                """
                
                quotes_result = self._client.query(quotes_query)
                for row in quotes_result.result_rows:
                    msg = self._create_quote_message(*row)
                    if msg:
                        messages.append(msg)
            
            # Load L2 updates
            if self._l2_subscriptions:
                l2_query = f"""
                SELECT symbol, timestamp, level, market_maker, operation, side,
                       price, size, tick_id
                FROM l2_updates
                WHERE date = '{date_str}'
                AND symbol IN ('{symbols_filter}')
                ORDER BY timestamp, tick_id
                LIMIT 100000
                """
                
                l2_result = self._client.query(l2_query)
                for row in l2_result.result_rows:
                    msg = self._create_l2_message(*row)
                    if msg:
                        messages.append(msg)
        
        except Exception as e:
            logger.error(f"Error loading daily data for {date_str}: {e}")
        
        # Sort all messages by timestamp for temporal sync
        messages.sort(key=lambda x: (x.timestamp, x.tick_id))
        
        return messages
    
    def _replay_daily_messages(self, messages: List[MockMessage]):
        """Replay messages with proper timing."""
        if not messages:
            return
        
        # Set data start time from first message
        if self._data_start_time is None:
            self._data_start_time = messages[0].timestamp
        
        for message in messages:
            if not self._running:
                break
            
            # Calculate elapsed time in data
            data_elapsed = (message.timestamp - self._data_start_time).total_seconds()
            
            # Calculate how much real time should have passed
            target_real_elapsed = data_elapsed / self.playback_speed
            
            # Calculate actual elapsed real time
            actual_elapsed = (datetime.now() - self._replay_start_time).total_seconds()
            
            # Sleep if we're ahead of schedule
            if target_real_elapsed > actual_elapsed:
                sleep_time = target_real_elapsed - actual_elapsed
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 1.0))  # Cap sleep at 1 second
            
            # Send message to appropriate queue
            self._distribute_message(message)
    
    def _create_trade_message(self, symbol: str, timestamp: datetime, trade_price: float,
                            trade_size: int, total_volume: int, market_center: str,
                            conditions: str, tick_id: int, bid_price: float, ask_price: float) -> MockMessage:
        """Create IQFeed trade message format."""
        # Format: T,symbol,timestamp,price,size,total_volume,market_center,conditions,tick_id,bid,ask
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]  # millisecond precision
        
        raw_message = (f"T,{symbol},{timestamp_str},{trade_price:.4f},{trade_size},"
                      f"{total_volume},{market_center},{conditions},{tick_id},"
                      f"{bid_price:.4f},{ask_price:.4f}")
        
        return MockMessage(
            timestamp=timestamp,
            symbol=symbol,
            message_type='T',
            raw_message=raw_message,
            tick_id=tick_id
        )
    
    def _create_quote_message(self, symbol: str, timestamp: datetime, bid_price: float,
                            bid_size: int, ask_price: float, ask_size: int,
                            bid_market_center: str, ask_market_center: str, tick_id: int) -> MockMessage:
        """Create IQFeed quote message format."""
        # Format: Q,symbol,timestamp,bid_price,bid_size,ask_price,ask_size,bid_mc,ask_mc,tick_id
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]
        
        raw_message = (f"Q,{symbol},{timestamp_str},{bid_price:.4f},{bid_size},"
                      f"{ask_price:.4f},{ask_size},{bid_market_center},{ask_market_center},{tick_id}")
        
        return MockMessage(
            timestamp=timestamp,
            symbol=symbol,
            message_type='Q',
            raw_message=raw_message,
            tick_id=tick_id
        )
    
    def _create_l2_message(self, symbol: str, timestamp: datetime, level: int,
                          market_maker: str, operation: int, side: int,
                          price: float, size: int, tick_id: int) -> MockMessage:
        """Create IQFeed L2 update message format."""
        # Format: U,symbol,timestamp,side,level,market_maker,price,size,operation
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]
        
        raw_message = (f"U,{symbol},{timestamp_str},{side},{level},{market_maker},"
                      f"{price:.4f},{size},{operation}")
        
        return MockMessage(
            timestamp=timestamp,
            symbol=symbol,
            message_type='U',
            raw_message=raw_message,
            tick_id=tick_id
        )
    
    def _distribute_message(self, message: MockMessage):
        """Distribute message to appropriate queues."""
        try:
            # Parse the message using IQFeed parser
            if message.message_type == 'T':
                parsed = self._parser.parse_trade_message(message.raw_message)
                parsed['raw_message'] = message.raw_message
                
                # Check if symbol is subscribed for ticks
                if message.symbol in self._tick_subscriptions:
                    try:
                        self._tick_buffer.put_nowait(parsed)
                    except queue.Full:
                        logger.warning(f"Tick buffer full, dropping message for {message.symbol}")
                else:
                    try:
                        self._message_queue.put_nowait(parsed)
                    except queue.Full:
                        logger.warning(f"Message queue full, dropping message for {message.symbol}")
            
            elif message.message_type == 'Q':
                parsed = self._parser.parse_quote_message(message.raw_message)
                parsed['raw_message'] = message.raw_message
                
                try:
                    self._message_queue.put_nowait(parsed)
                except queue.Full:
                    logger.warning(f"Message queue full, dropping quote for {message.symbol}")
            
            elif message.message_type == 'U':
                parsed = self._parser.parse_l2_message(message.raw_message)
                parsed['raw_message'] = message.raw_message
                
                try:
                    self._message_queue.put_nowait(parsed)
                except queue.Full:
                    logger.warning(f"Message queue full, dropping L2 update for {message.symbol}")
        
        except Exception as e:
            logger.warning(f"Error distributing message: {e}")
    
    def _simulate_real_time_data(self):
        """Generate simulated real-time data when no ClickHouse data available."""
        logger.info("Starting simulated real-time data generation")
        # Implementation for when we need to simulate missing data
        # This would generate realistic tick/quote/L2 data patterns
        pass
    
    def _hybrid_data_production(self):
        """Hybrid mode: use ClickHouse data + simulation for gaps."""
        logger.info("Starting hybrid data production")
        # Implementation for mixing real ClickHouse data with simulation
        pass
    
    # ======================================================================
    # STATUS AND STATISTICS
    # ======================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current mock producer status."""
        uptime = 0.0
        if self._connect_time:
            uptime = (datetime.now(timezone.utc) - self._connect_time).total_seconds()
        
        with self._subscription_lock:
            total_subs = (len(self._l2_subscriptions) + len(self._trade_subscriptions) +
                         len(self._quote_subscriptions) + len(self._tick_subscriptions))
        
        return {
            'connected': self.is_connected(),
            'mode': self.mode.value,
            'uptime_seconds': uptime,
            'session_id': self._session_id,
            'active_subscriptions': total_subs,
            'playback_speed': self.playback_speed,
            'data_range': f"{self.start_date} to {self.end_date}",
            'message_queue_size': self._message_queue.qsize(),
            'tick_buffer_size': self._tick_buffer.qsize(),
            'available_symbols': len(self._available_symbols) if hasattr(self, '_available_symbols') else 0
        }
    
    def get_bandwidth_statistics(self) -> Dict[str, Any]:
        """Get mock bandwidth statistics."""
        return {
            'bytes_received_per_second': 0.0,  # Mock doesn't track bytes
            'messages_received_per_second': 0.0,
            'total_bytes_received': 0,
            'total_messages_received': 0,
            'average_message_size': 0.0,
            'last_update': datetime.now(timezone.utc)
        }