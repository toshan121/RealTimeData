"""
ClickHouse Data Writer for Market Data Persistence

Following PROJECT_ROADMAP.md Phase 4: Real-time data persistence with high throughput
Following RULES.md: Structured error handling, loud failures, real data only

Implements high-performance batch writing to ClickHouse for:
- L2 order book updates
- Trade executions  
- NBBO quotes
- Calculated market features
- Backtest results

NO MOCKS - Only real ClickHouse connections and data validation.
LOUD FAILURES - Every write error must be visible with recovery guidance.
"""

import os
import logging
import threading
import time
import random
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum
import json
from dotenv import load_dotenv
from collections import defaultdict
from decimal import Decimal

import clickhouse_connect
from clickhouse_connect.driver import Client

from processing.order_book import OrderBookSnapshot
from processing.feature_calculators import MarketFeatures
from ingestion.exceptions import (
    ProcessingError,
    DataValidationError
)

# Load environment variables
load_dotenv()

# Configure logging for loud failures
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TableType(Enum):
    """Database table types for data routing."""
    L2_UPDATES = "l2_updates"
    TRADES = "trades"
    QUOTES = "quotes"
    FEATURES = "features"
    BACKTEST_TRADES = "backtest_trades"


@dataclass
class WriteResult:
    """Result of ClickHouse write operation."""
    success: bool
    table: str
    rows_written: int = 0
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    recovery_hint: Optional[str] = None


@dataclass
class WriterStatistics:
    """ClickHouse writer performance statistics."""
    total_writes: int = 0
    total_rows: int = 0
    total_bytes: int = 0
    successful_writes: int = 0
    failed_writes: int = 0
    l2_rows: int = 0
    trade_rows: int = 0
    quote_rows: int = 0
    feature_rows: int = 0
    last_write_time: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate write success rate."""
        return self.successful_writes / self.total_writes if self.total_writes > 0 else 0.0


class ClickHouseWriter:
    """
    High-performance ClickHouse writer for market data.
    
    Implements batched writes with automatic error recovery
    as specified in PROJECT_ROADMAP.md Phase 4.
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        batch_size: int = 10000,
        flush_interval_seconds: int = 5
    ):
        """
        Initialize ClickHouse writer.
        
        Args:
            host: ClickHouse host
            port: ClickHouse port
            database: Database name
            username: Username for authentication
            password: Password for authentication
            batch_size: Maximum batch size before automatic flush
            flush_interval_seconds: Maximum seconds between flushes
        """
        # Connection configuration
        self.host = host or os.getenv('CLICKHOUSE_HOST', 'localhost')
        self.port = port or int(os.getenv('CLICKHOUSE_PORT', '8123'))
        self.database = database or os.getenv('CLICKHOUSE_DATABASE', 'l2_market_data')
        self.username = username or os.getenv('CLICKHOUSE_USER', 'l2_user')
        self.password = password or os.getenv('CLICKHOUSE_PASSWORD', 'l2_secure_pass')
        
        # Batch configuration
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        
        # Client and connection
        self._client: Optional[Client] = None
        self._connected = False
        
        # Batching system
        self._batches: Dict[TableType, List[Dict[str, Any]]] = defaultdict(list)
        self._batch_lock = threading.Lock()
        self._last_flush = time.time()
        
        # Background flush thread
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Statistics and monitoring
        self._stats = WriterStatistics()
        self._stats_lock = threading.Lock()
        
        # Schema mapping for data validation - aligned with optimized ClickHouse schema
        self._table_schemas = {
            TableType.L2_UPDATES: {
                'required_fields': ['symbol', 'timestamp', 'level', 'market_maker', 'operation', 'side', 'price', 'size', 'tick_id'],
                'field_types': {
                    'symbol': str,
                    'timestamp': datetime,
                    'level': int,
                    'market_maker': str,
                    'operation': int,  # 0=Insert, 1=Update, 2=Delete
                    'side': int,       # 0=Ask, 1=Bid
                    'price': (int, float, str),  # Support Decimal64(8) conversion
                    'size': int,
                    'tick_id': int
                }
            },
            TableType.TRADES: {
                'required_fields': ['symbol', 'timestamp', 'trade_price', 'trade_size', 'tick_id'],
                'field_types': {
                    'symbol': str,
                    'timestamp': datetime,
                    'trade_price': (int, float, str),
                    'trade_size': int,
                    'total_volume': int,
                    'trade_market_center': str,
                    'trade_conditions': str,
                    'tick_id': int,
                    'bid_price': (int, float, str),
                    'ask_price': (int, float, str)
                }
            },
            TableType.QUOTES: {
                'required_fields': ['symbol', 'timestamp', 'bid_price', 'bid_size', 'ask_price', 'ask_size', 'tick_id'],
                'field_types': {
                    'symbol': str,
                    'timestamp': datetime,
                    'bid_price': (int, float, str),
                    'bid_size': int,
                    'ask_price': (int, float, str),
                    'ask_size': int,
                    'bid_market_center': str,
                    'ask_market_center': str,
                    'tick_id': int
                }
            },
            TableType.FEATURES: {
                'required_fields': ['symbol', 'timestamp', 'mid_price', 'spread'],
                'field_types': {
                    'symbol': str,
                    'timestamp': datetime,
                    'mid_price': (int, float, str),
                    'spread': (int, float, str),
                    'spread_bps': int,
                    'total_bid_depth': int,
                    'total_ask_depth': int,
                    'ofi': (int, float),
                    'vap': (int, float),
                    'bid_absorption_rate': (int, float),
                    'price_velocity': (int, float),
                    'volume_price_ratio': (int, float),
                    'iceberg_score': (int, float),
                    'dark_pool_ratio': (int, float),
                    'liquidity_sinkhole_score': (int, float),
                    'micro_volatility': (int, float),
                    'signal_1': int,
                    'signal_2': int,
                    'signal_3': int,
                    'signal_4': int,
                    'signal_5': int
                }
            },
            TableType.BACKTEST_TRADES: {
                'required_fields': ['strategy_id', 'symbol', 'timestamp', 'side', 'quantity', 'price'],
                'field_types': {
                    'strategy_id': str,
                    'symbol': str,
                    'timestamp': datetime,
                    'side': str,  # 'BUY' or 'SELL'
                    'quantity': int,
                    'price': (int, float, str),
                    'commission': (int, float, str),
                    'slippage': (int, float, str),
                    'pnl': (int, float, str),
                    'cumulative_pnl': (int, float, str),
                    'position': int,
                    'signal_triggered': str,
                    'metadata': str
                }
            }
        }
        
        logger.info(f"ClickHouse writer initialized (host: {self.host}:{self.port}, db: {self.database})")
    
    def connect(self, max_retries: int = 3, retry_delay: float = 1.0) -> WriteResult:
        """
        Connect to ClickHouse database with retry logic.
        
        Args:
            max_retries: Maximum number of connection attempts
            retry_delay: Delay between retry attempts in seconds
            
        Returns:
            WriteResult indicating connection success
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # Exponential backoff with jitter
                    delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    logger.info(f"Retrying ClickHouse connection in {delay:.1f}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(delay)
                
                logger.info(f"Connecting to ClickHouse at {self.host}:{self.port} (attempt {attempt + 1})")
                
                # Create ClickHouse client with optimized settings
                self._client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    username=self.username,
                    password=self.password,
                    connect_timeout=30,
                    send_receive_timeout=60,
                    interface='http',  # HTTP interface on port 8123
                    compress=True,     # Enable compression for better performance
                    query_retries=3,   # Built-in query retry
                    settings={
                        'max_execution_time': 60,
                        'max_memory_usage': 2000000000,  # 2GB memory limit
                        'max_threads': 8,
                        'use_uncompressed_cache': 1,
                        'distributed_aggregation_memory_efficient': 1
                    }
                )
                
                # Test connection with a simple query
                result = self._client.query("SELECT 1 as test")
                if result.result_rows and result.result_rows[0][0] == 1:
                    self._connected = True
                    
                    # Verify database and tables exist
                    try:
                        tables = self._client.query("SHOW TABLES FROM l2_market_data")
                        required_tables = {'l2_updates', 'trades', 'quotes', 'features'}
                        existing_tables = {row[0] for row in tables.result_rows}
                        
                        if not required_tables.issubset(existing_tables):
                            missing = required_tables - existing_tables
                            logger.warning(f"Missing tables in ClickHouse: {missing}")
                    except Exception as table_check_error:
                        logger.warning(f"Could not verify table existence: {table_check_error}")
                    
                    # Start background flush thread
                    self._running = True
                    self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
                    self._flush_thread.start()
                    
                    logger.info("ClickHouse connection established successfully")
                    return WriteResult(
                        success=True, 
                        table="connection", 
                        recovery_hint="Connection established successfully"
                    )
                else:
                    raise ProcessingError("Connection test query returned unexpected result", "clickhouse_connection")
                    
            except Exception as e:
                last_error = e
                error_msg = f"Connection attempt {attempt + 1} failed: {e}"
                logger.warning(error_msg)
                
                # Clean up failed client
                if self._client:
                    try:
                        self._client.close()
                    except:
                        pass
                    self._client = None
                
                # If this was the last attempt, break and return error
                if attempt == max_retries:
                    break
        
        # All connection attempts failed
        final_error_msg = f"Failed to connect to ClickHouse after {max_retries + 1} attempts. Last error: {last_error}"
        logger.error(final_error_msg)
        
        return WriteResult(
            success=False,
            table="connection",
            error_message=final_error_msg,
            recovery_hint=(
                "1. Check ClickHouse server is running (docker-compose up -d)\n"
                "2. Verify network connectivity to localhost:8123\n"
                "3. Check credentials: l2_user/l2_secure_pass\n"
                "4. Ensure database 'l2_market_data' exists\n"
                "5. Run infrastructure health check script"
            )
        )
    
    def disconnect(self):
        """Disconnect from ClickHouse and cleanup resources."""
        logger.info("Disconnecting from ClickHouse")
        
        # Stop background thread
        self._running = False
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=10.0)
        
        # Flush any remaining batches
        try:
            self.flush_all()
        except Exception as e:
            logger.warning(f"Error flushing final batches: {e}")
        
        # Close client connection
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"Error closing ClickHouse client: {e}")
            finally:
                self._client = None
                self._connected = False
        
        logger.info("ClickHouse writer disconnected")
    
    def write_l2_update(self, l2_message: Dict[str, Any]) -> WriteResult:
        """
        Write L2 order book update to ClickHouse.
        
        Args:
            l2_message: L2 update message
            
        Returns:
            WriteResult with write status
        """
        try:
            # Validate message structure
            validated_data = self._validate_and_prepare_data(l2_message, TableType.L2_UPDATES)
            
            # Add to batch
            return self._add_to_batch(TableType.L2_UPDATES, validated_data)
            
        except Exception as e:
            error_msg = f"Failed to write L2 update: {e}"
            logger.error(error_msg)
            
            with self._stats_lock:
                self._stats.failed_writes += 1
            
            return WriteResult(
                success=False,
                table="l2_updates",
                error_message=error_msg,
                recovery_hint="Verify L2 message format and ClickHouse connection"
            )
    
    def write_trade(self, trade_message: Dict[str, Any]) -> WriteResult:
        """
        Write trade execution to ClickHouse.
        
        Args:
            trade_message: Trade execution message
            
        Returns:
            WriteResult with write status
        """
        try:
            validated_data = self._validate_and_prepare_data(trade_message, TableType.TRADES)
            return self._add_to_batch(TableType.TRADES, validated_data)
            
        except Exception as e:
            error_msg = f"Failed to write trade: {e}"
            logger.error(error_msg)
            
            with self._stats_lock:
                self._stats.failed_writes += 1
            
            return WriteResult(
                success=False,
                table="trades",
                error_message=error_msg,
                recovery_hint="Verify trade message format and ClickHouse connection"
            )
    
    def write_quote(self, quote_message: Dict[str, Any]) -> WriteResult:
        """
        Write NBBO quote to ClickHouse.
        
        Args:
            quote_message: Quote message
            
        Returns:
            WriteResult with write status
        """
        try:
            validated_data = self._validate_and_prepare_data(quote_message, TableType.QUOTES)
            return self._add_to_batch(TableType.QUOTES, validated_data)
            
        except Exception as e:
            error_msg = f"Failed to write quote: {e}"
            logger.error(error_msg)
            
            with self._stats_lock:
                self._stats.failed_writes += 1
            
            return WriteResult(
                success=False,
                table="quotes",
                error_message=error_msg,
                recovery_hint="Verify quote message format and ClickHouse connection"
            )
    
    def write_features(self, features: MarketFeatures) -> WriteResult:
        """
        Write calculated market features to ClickHouse.
        
        Args:
            features: MarketFeatures object
            
        Returns:
            WriteResult with write status
        """
        try:
            # Convert MarketFeatures to dictionary
            features_dict = {
                'timestamp': features.timestamp,
                'symbol': features.symbol,
                'mid_price': features.mid_price,
                'spread': features.bid_ask_spread,
                'spread_bps': int(features.relative_spread * 10000),  # Convert to basis points
                'total_bid_depth': features.total_bid_volume,
                'total_ask_depth': features.total_ask_volume,
                'ofi': features.ofi_1s,
                'vap': 0.0,  # Placeholder - to be calculated
                'bid_absorption_rate': 0.0,  # Placeholder
                'price_velocity': features.price_momentum_5s,
                'volume_price_ratio': features.volume_imbalance,
                'iceberg_score': 0.0,  # Placeholder 
                'dark_pool_ratio': 0.0,  # Placeholder
                'liquidity_sinkhole_score': 0.0,  # Placeholder
                'micro_volatility': features.price_volatility_1min,
                'signal_1': 0,  # To be populated by signal calculations
                'signal_2': 0,
                'signal_3': 0,
                'signal_4': 0,
                'signal_5': 0
            }
            
            validated_data = self._validate_and_prepare_data(features_dict, TableType.FEATURES)
            return self._add_to_batch(TableType.FEATURES, validated_data)
            
        except Exception as e:
            error_msg = f"Failed to write features: {e}"
            logger.error(error_msg)
            
            with self._stats_lock:
                self._stats.failed_writes += 1
            
            return WriteResult(
                success=False,
                table="features",
                error_message=error_msg,
                recovery_hint="Verify features object and ClickHouse connection"
            )
    
    def write_features_with_signals(self, features: MarketFeatures, signals: Dict[str, float]) -> WriteResult:
        """
        Write market features with accumulation signals to ClickHouse.
        
        Args:
            features: MarketFeatures object
            signals: Dictionary of accumulation signals
            
        Returns:
            WriteResult with write status
        """
        try:
            # Convert signals to binary indicators (>0.5 threshold)
            signal_mapping = {
                'stealth_accumulation': 'signal_1',
                'mm_withdrawal': 'signal_2', 
                'ofi_momentum': 'signal_3',
                'iceberg_detection': 'signal_4',
                'depth_asymmetry': 'signal_5'
            }
            
            # Start with base features
            features_dict = {
                'timestamp': features.timestamp,
                'symbol': features.symbol,
                'mid_price': features.mid_price,
                'spread': features.bid_ask_spread,
                'spread_bps': int(features.relative_spread * 10000),
                'total_bid_depth': features.total_bid_volume,
                'total_ask_depth': features.total_ask_volume,
                'ofi': features.ofi_1s,
                'vap': 0.0,
                'bid_absorption_rate': 0.0,
                'price_velocity': features.price_momentum_5s,
                'volume_price_ratio': features.volume_imbalance,
                'iceberg_score': signals.get('iceberg_detection', 0.0),
                'dark_pool_ratio': 0.0,
                'liquidity_sinkhole_score': 0.0,
                'micro_volatility': features.price_volatility_1min,
                'signal_1': 0,
                'signal_2': 0,
                'signal_3': 0,
                'signal_4': 0,
                'signal_5': 0
            }
            
            # Add signal indicators
            for signal_name, column_name in signal_mapping.items():
                if signal_name in signals:
                    features_dict[column_name] = 1 if signals[signal_name] > 0.5 else 0
            
            validated_data = self._validate_and_prepare_data(features_dict, TableType.FEATURES)
            return self._add_to_batch(TableType.FEATURES, validated_data)
            
        except Exception as e:
            error_msg = f"Failed to write features with signals: {e}"
            logger.error(error_msg)
            
            with self._stats_lock:
                self._stats.failed_writes += 1
            
            return WriteResult(
                success=False,
                table="features",
                error_message=error_msg,
                recovery_hint="Verify features and signals data format"
            )
    
    def flush_all(self) -> List[WriteResult]:
        """
        Flush all pending batches to ClickHouse.
        
        Returns:
            List of WriteResult for each table flushed
        """
        results = []
        
        with self._batch_lock:
            for table_type, batch in self._batches.items():
                if batch:
                    result = self._flush_batch(table_type, batch)
                    results.append(result)
                    
                    if result.success:
                        self._batches[table_type].clear()
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get writer performance statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._stats_lock:
            return {
                'total_writes': self._stats.total_writes,
                'total_rows': self._stats.total_rows,
                'total_bytes': self._stats.total_bytes,
                'successful_writes': self._stats.successful_writes,
                'failed_writes': self._stats.failed_writes,
                'success_rate': self._stats.success_rate,
                'l2_rows': self._stats.l2_rows,
                'trade_rows': self._stats.trade_rows,
                'quote_rows': self._stats.quote_rows,
                'feature_rows': self._stats.feature_rows,
                'last_write_time': self._stats.last_write_time.isoformat() if self._stats.last_write_time else None,
                'connected': self._connected,
                'batch_sizes': {table_type.value: len(batch) for table_type, batch in self._batches.items()},
                'time_since_last_flush': time.time() - self._last_flush
            }
    
    def _validate_and_prepare_data(self, data: Dict[str, Any], table_type: TableType) -> Dict[str, Any]:
        """Validate and prepare data for database insertion with enhanced type handling."""
        schema = self._table_schemas.get(table_type)
        if not schema:
            raise DataValidationError(f"Unknown table type: {table_type}", data)
        
        # Check required fields
        for field in schema['required_fields']:
            if field not in data:
                raise DataValidationError(f"Missing required field: {field}", data)
        
        # Prepare data with type coercion and validation
        prepared = {}
        
        for field, value in data.items():
            if field in schema['field_types']:
                expected_types = schema['field_types'][field]
                
                # Handle timestamp conversion
                if field == 'timestamp':
                    if isinstance(value, str):
                        try:
                            prepared[field] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError as e:
                            raise DataValidationError(f"Invalid timestamp format: {e}", data)
                    elif isinstance(value, datetime):
                        # Ensure timezone awareness
                        if value.tzinfo is None:
                            prepared[field] = value.replace(tzinfo=timezone.utc)
                        else:
                            prepared[field] = value
                    else:
                        raise DataValidationError(f"Invalid timestamp type: {type(value)}", data)
                
                # Handle numeric fields that may come as strings or Decimal objects
                elif field in ['price', 'trade_price', 'bid_price', 'ask_price', 'mid_price', 'spread', 
                              'commission', 'slippage', 'pnl', 'cumulative_pnl']:
                    if isinstance(value, str):
                        try:
                            prepared[field] = float(value)
                        except ValueError:
                            raise DataValidationError(f"Cannot convert {field} to numeric: {value}", data)
                    elif isinstance(value, (int, float)):
                        prepared[field] = float(value)
                    elif isinstance(value, Decimal):
                        # Handle Decimal objects by converting to float
                        prepared[field] = float(value)
                    else:
                        raise DataValidationError(f"Invalid numeric type for {field}: {type(value)}", data)
                
                # Handle integer fields
                elif field in ['level', 'operation', 'side', 'size', 'trade_size', 'bid_size', 'ask_size',
                              'tick_id', 'total_volume', 'spread_bps', 'total_bid_depth', 'total_ask_depth',
                              'quantity', 'position', 'signal_1', 'signal_2', 'signal_3', 'signal_4', 'signal_5']:
                    if isinstance(value, str):
                        try:
                            prepared[field] = int(value)
                        except ValueError:
                            raise DataValidationError(f"Cannot convert {field} to integer: {value}", data)
                    elif isinstance(value, (int, float)):
                        prepared[field] = int(value)
                    else:
                        raise DataValidationError(f"Invalid integer type for {field}: {type(value)}", data)
                
                # Handle float fields
                elif field in ['ofi', 'vap', 'bid_absorption_rate', 'price_velocity', 'volume_price_ratio',
                              'iceberg_score', 'dark_pool_ratio', 'liquidity_sinkhole_score', 'micro_volatility']:
                    if isinstance(value, str):
                        try:
                            prepared[field] = float(value)
                        except ValueError:
                            raise DataValidationError(f"Cannot convert {field} to float: {value}", data)
                    elif isinstance(value, (int, float)):
                        prepared[field] = float(value)
                    else:
                        prepared[field] = 0.0  # Default for optional float fields
                
                # Handle string fields
                elif isinstance(expected_types, type) and expected_types == str:
                    prepared[field] = str(value) if value is not None else ''
                
                # Standard type validation for other fields
                else:
                    if not isinstance(value, expected_types):
                        raise DataValidationError(f"Invalid type for {field}: expected {expected_types}, got {type(value)}", data)
                    prepared[field] = value
            
            else:
                # Include additional fields that aren't in schema (may be optional)
                prepared[field] = value
        
        # Ensure all required fields are present in prepared data
        for field in schema['required_fields']:
            if field not in prepared:
                raise DataValidationError(f"Required field {field} missing after preparation", data)
        
        return prepared
    
    def _add_to_batch(self, table_type: TableType, data: Dict[str, Any]) -> WriteResult:
        """Add data to batch and trigger flush if needed."""
        with self._batch_lock:
            self._batches[table_type].append(data)
            batch_size = len(self._batches[table_type])
            
            # Check if batch is full
            if batch_size >= self.batch_size:
                batch_copy = self._batches[table_type].copy()
                self._batches[table_type].clear()
                
                # Flush outside the lock
                result = self._flush_batch(table_type, batch_copy)
                return result
        
        return WriteResult(success=True, table=table_type.value, rows_written=0)
    
    def _flush_batch(self, table_type: TableType, batch: List[Dict[str, Any]], max_retries: int = 2) -> WriteResult:
        """Flush a batch to ClickHouse with retry logic."""
        if not batch or not self._connected:
            return WriteResult(success=False, table=table_type.value, error_message="No data or not connected")
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()
                
                # Check connection health before write
                if not self.is_healthy():
                    logger.warning(f"Connection unhealthy, attempting reconnect before flush")
                    reconnect_result = self.connect(max_retries=1, retry_delay=0.5)
                    if not reconnect_result.success:
                        raise ProcessingError("Failed to reconnect before flush", "clickhouse_connection")
                
                # Insert batch into ClickHouse
                self._client.insert(table_type.value, batch)
                
                execution_time = (time.time() - start_time) * 1000  # Convert to ms
                
                # Update statistics
                with self._stats_lock:
                    self._stats.successful_writes += 1
                    self._stats.total_writes += 1
                    self._stats.total_rows += len(batch)
                    self._stats.last_write_time = datetime.now(timezone.utc)
                    
                    # Update table-specific counters
                    if table_type == TableType.L2_UPDATES:
                        self._stats.l2_rows += len(batch)
                    elif table_type == TableType.TRADES:
                        self._stats.trade_rows += len(batch)
                    elif table_type == TableType.QUOTES:
                        self._stats.quote_rows += len(batch)
                    elif table_type == TableType.FEATURES:
                        self._stats.feature_rows += len(batch)
                
                self._last_flush = time.time()
                
                logger.info(f"Flushed {len(batch)} rows to {table_type.value} in {execution_time:.2f}ms")
                
                return WriteResult(
                    success=True,
                    table=table_type.value,
                    rows_written=len(batch),
                    execution_time_ms=execution_time
                )
                
            except Exception as e:
                last_error = e
                logger.warning(f"Flush attempt {attempt + 1} failed for {table_type.value}: {e}")
                
                # If this is not the last attempt, wait a bit before retrying
                if attempt < max_retries:
                    retry_delay = 0.5 * (2 ** attempt) + random.uniform(0, 0.2)
                    time.sleep(retry_delay)
                    
                    # Try to reconnect for the next attempt
                    if not self.is_healthy():
                        logger.info(f"Attempting reconnection before retry {attempt + 2}")
                        self.connect(max_retries=1, retry_delay=0.1)
        
        # All attempts failed
        error_msg = f"Failed to flush batch to {table_type.value} after {max_retries + 1} attempts: {last_error}"
        logger.error(error_msg)
        
        with self._stats_lock:
            self._stats.failed_writes += 1
            self._stats.total_writes += 1
        
        return WriteResult(
            success=False,
            table=table_type.value,
            error_message=error_msg,
            recovery_hint=(
                f"1. Verify ClickHouse server is responsive\n"
                f"2. Check table '{table_type.value}' exists and schema matches\n"
                f"3. Verify network connectivity and authentication\n"
                f"4. Consider reducing batch size if memory issues\n"
                f"5. Check ClickHouse server logs for detailed errors"
            )
        )
    
    def _flush_loop(self):
        """Background thread for periodic batch flushing."""
        logger.info("ClickHouse flush thread started")
        
        while self._running:
            try:
                time.sleep(1)  # Check every second
                
                # Check if it's time to flush
                if time.time() - self._last_flush >= self.flush_interval_seconds:
                    results = self.flush_all()
                    
                    # Log any failures
                    for result in results:
                        if not result.success:
                            logger.warning(f"Periodic flush failed for {result.table}: {result.error_message}")
                
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
                if not self._running:
                    break
        
        logger.info("ClickHouse flush thread stopped")
    
    def is_healthy(self) -> bool:
        """Check if writer is healthy and operational."""
        if not self._connected or not self._client:
            return False
        
        try:
            # Test with simple query
            self._client.query("SELECT 1")
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False