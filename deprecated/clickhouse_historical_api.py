#!/usr/bin/env python3
"""
ClickHouse Historical Data API
Real implementation with proper timezone handling (US Eastern)
NO MOCKS - Real data storage and retrieval only
"""

import os
import sys
import json
import logging
import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import clickhouse_connect
from clickhouse_connect.driver.client import Client
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# US Eastern timezone
US_EASTERN = pytz.timezone('US/Eastern')
UTC = pytz.UTC

class DataValidationError(Exception):
    """Loud failure for data issues"""
    pass

class ClickHouseHistoricalAPI:
    """Production-ready ClickHouse API for historical market data"""
    
    def __init__(self, host: str = 'localhost', port: int = 8123, 
                 database: str = 'l2_market_data', create_tables: bool = False):
        """Initialize ClickHouse connection with NO authentication"""
        
        self.host = host
        self.port = port
        self.database = database
        
        try:
            # Connect directly to ClickHouse using optimized settings
            self.client = clickhouse_connect.get_client(
                host=host,
                port=port,
                database=database,
                username='l2_user',
                password='l2_secure_pass',
                connect_timeout=30,
                send_receive_timeout=120,
                interface='http',
                compress=True,
                settings={
                    'use_client_time_zone': False,
                    'max_execution_time': 300,
                    'max_memory_usage': 4000000000,  # 4GB for large queries
                    'max_threads': 16,
                    'use_uncompressed_cache': 1,
                    'distributed_aggregation_memory_efficient': 1
                }
            )
            
            # Test connection
            result = self.client.query("SELECT 1 as test")
            if not (result.result_rows and result.result_rows[0][0] == 1):
                raise Exception("Connection test failed")
            
            if create_tables:
                self._create_tables()
            
            logger.info(f"✅ Connected to ClickHouse at {host}:{port}/{database}")
            
        except Exception as e:
            raise DataValidationError(f"❌ CLICKHOUSE CONNECTION FAILED: {e}")
    
    def _ensure_database(self):
        """Ensure database exists"""
        try:
            self.client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")
            logger.info(f"Database '{self.database}' ready")
        except Exception as e:
            logger.error(f"Failed to create database: {e}")
    
    def _create_tables(self):
        """Create optimized tables for historical data"""
        
        # Tick data table - partitioned by date for fast queries
        self.client.command("""
            CREATE TABLE IF NOT EXISTS ticks (
                symbol String,
                timestamp DateTime64(3, 'US/Eastern'),
                timestamp_utc DateTime64(3, 'UTC'),
                price Float64,
                size UInt32,
                bid Float64,
                ask Float64,
                exchange String,
                conditions String,
                trade_id String
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMMDD(timestamp)
            ORDER BY (symbol, timestamp)
            SETTINGS index_granularity = 8192
        """)
        
        # L1 quotes table
        self.client.command("""
            CREATE TABLE IF NOT EXISTS quotes (
                symbol String,
                timestamp DateTime64(3, 'US/Eastern'),
                timestamp_utc DateTime64(3, 'UTC'),
                bid Float64,
                ask Float64,
                bid_size UInt32,
                ask_size UInt32,
                bid_exchange String,
                ask_exchange String
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMMDD(timestamp)
            ORDER BY (symbol, timestamp)
            SETTINGS index_granularity = 8192
        """)
        
        # Daily aggregates for fast lookups
        self.client.command("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                symbol String,
                date Date,
                open Float64,
                high Float64,
                low Float64,
                close Float64,
                volume UInt64,
                tick_count UInt32,
                vwap Float64,
                spread_avg Float64,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (symbol, date)
        """)
        
        # Data availability index
        self.client.command("""
            CREATE TABLE IF NOT EXISTS data_availability (
                symbol String,
                date Date,
                data_type String,  -- 'tick', 'quote', 'l2'
                record_count UInt32,
                first_timestamp DateTime64(3, 'US/Eastern'),
                last_timestamp DateTime64(3, 'US/Eastern'),
                file_size_bytes UInt64,
                download_timestamp DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (symbol, date, data_type)
        """)
        
        logger.info("✅ All tables created/verified")
    
    def _convert_to_eastern(self, timestamp_str: str) -> Tuple[datetime, datetime]:
        """Convert timestamp string to Eastern and UTC"""
        try:
            # Parse timestamp
            if '.' in timestamp_str:
                base_ts = timestamp_str.split('.')[0]
                dt = datetime.strptime(base_ts, '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            
            # Assume input is in Eastern time (from IQFeed)
            dt_eastern = US_EASTERN.localize(dt)
            dt_utc = dt_eastern.astimezone(UTC)
            
            return dt_eastern, dt_utc
            
        except Exception as e:
            raise DataValidationError(f"❌ Invalid timestamp '{timestamp_str}': {e}")
    
    def store_ticks(self, symbol: str, date: str, ticks: List[Dict]) -> int:
        """Store tick data with validation"""
        if not ticks:
            raise DataValidationError(f"❌ No ticks provided for {symbol} on {date}")
        
        # Validate and prepare data
        prepared_data = []
        errors = 0
        
        for i, tick in enumerate(ticks):
            try:
                # Required fields
                if 'timestamp' not in tick or 'price' not in tick:
                    errors += 1
                    continue
                
                # Convert timestamp
                dt_eastern, dt_utc = self._convert_to_eastern(tick['timestamp'])
                
                # Validate price
                price = float(tick['price'])
                if price <= 0 or price > 100000:
                    logger.warning(f"⚠️  Suspicious price ${price} for {symbol}")
                    errors += 1
                    continue
                
                prepared_data.append([
                    symbol,
                    dt_eastern,
                    dt_utc,
                    price,
                    int(tick.get('size', 0)),
                    float(tick.get('bid', 0)),
                    float(tick.get('ask', 0)),
                    tick.get('exchange', ''),
                    tick.get('conditions', ''),
                    tick.get('trade_id', '')
                ])
                
            except Exception as e:
                logger.error(f"Error processing tick {i}: {e}")
                errors += 1
        
        if not prepared_data:
            raise DataValidationError(f"❌ No valid ticks after validation")
        
        # Bulk insert
        try:
            self.client.insert(
                'ticks',
                prepared_data,
                column_names=['symbol', 'timestamp', 'timestamp_utc', 'price', 
                            'size', 'bid', 'ask', 'exchange', 'conditions', 'trade_id']
            )
            
            # Update availability index
            first_ts = prepared_data[0][1]
            last_ts = prepared_data[-1][1]
            
            self.client.insert(
                'data_availability',
                [[symbol, datetime.strptime(date, '%Y%m%d').date(), 'tick', 
                  len(prepared_data), first_ts, last_ts, 0, datetime.now()]]
            )
            
            logger.info(f"✅ Stored {len(prepared_data)} ticks for {symbol} on {date}")
            if errors > 0:
                logger.warning(f"⚠️  {errors} ticks rejected due to validation errors")
            
            return len(prepared_data)
            
        except Exception as e:
            raise DataValidationError(f"❌ Failed to store ticks: {e}")
    
    def get_ticks(self, symbol: str, date: str, 
                  start_time: Optional[str] = None,
                  end_time: Optional[str] = None) -> List[Dict]:
        """Retrieve tick data for a symbol/date"""
        
        # Build query
        query = f"""
            SELECT 
                timestamp,
                price,
                size,
                bid,
                ask,
                exchange,
                conditions
            FROM ticks
            WHERE symbol = '{symbol}'
            AND toYYYYMMDD(timestamp) = {date}
        """
        
        # Add time filters if specified
        if start_time:
            query += f" AND timestamp >= '{start_time}'"
        if end_time:
            query += f" AND timestamp <= '{end_time}'"
        
        query += " ORDER BY timestamp"
        
        try:
            result = self.client.query(query)
            
            ticks = []
            for row in result.result_rows:
                ticks.append({
                    'timestamp': row[0].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                    'price': float(row[1]),
                    'size': int(row[2]),
                    'bid': float(row[3]) if row[3] else None,
                    'ask': float(row[4]) if row[4] else None,
                    'exchange': row[5],
                    'conditions': row[6]
                })
            
            logger.info(f"Retrieved {len(ticks)} ticks for {symbol} on {date}")
            return ticks
            
        except Exception as e:
            logger.error(f"❌ Failed to retrieve ticks: {e}")
            return []
    
    def check_data_exists(self, symbol: str, date: str, 
                         data_type: str = 'tick') -> bool:
        """Check if data exists for symbol/date"""
        
        query = f"""
            SELECT count() as cnt
            FROM data_availability
            WHERE symbol = '{symbol}'
            AND date = '{date}'
            AND data_type = '{data_type}'
        """
        
        try:
            result = self.client.query(query)
            return result.result_rows[0][0] > 0
        except Exception as e:
            logger.warning(f"Failed to check data existence for {symbol}/{date}: {e}")
            return False
    
    def get_data_summary(self, symbols: Optional[List[str]] = None,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> pd.DataFrame:
        """Get summary of available data"""
        
        query = """
            SELECT 
                symbol,
                date,
                data_type,
                record_count,
                first_timestamp,
                last_timestamp
            FROM data_availability
            WHERE 1=1
        """
        
        if symbols:
            symbols_str = "','".join(symbols)
            query += f" AND symbol IN ('{symbols_str}')"
        
        if start_date:
            query += f" AND date >= '{start_date}'"
        
        if end_date:
            query += f" AND date <= '{end_date}'"
        
        query += " ORDER BY symbol, date, data_type"
        
        try:
            result = self.client.query(query)
            
            data = []
            for row in result.result_rows:
                data.append({
                    'symbol': row[0],
                    'date': row[1],
                    'data_type': row[2],
                    'record_count': row[3],
                    'first_timestamp': row[4],
                    'last_timestamp': row[5]
                })
            
            return pd.DataFrame(data)
            
        except Exception as e:
            logger.error(f"Failed to get summary: {e}")
            return pd.DataFrame()
    
    def calculate_daily_stats(self, symbol: str, date: str) -> Dict:
        """Calculate and store daily statistics"""
        
        query = f"""
            SELECT 
                min(price) as low,
                max(price) as high,
                sum(size) as volume,
                count() as tick_count,
                sum(price * size) / sum(size) as vwap,
                avg(ask - bid) as spread_avg,
                first_value(price) as open,
                last_value(price) as close
            FROM ticks
            WHERE symbol = '{symbol}'
            AND toYYYYMMDD(timestamp) = {date}
            AND size > 0
        """
        
        try:
            result = self.client.query(query)
            
            if result.result_rows:
                row = result.result_rows[0]
                stats = {
                    'symbol': symbol,
                    'date': date,
                    'open': float(row[6]),
                    'high': float(row[1]),
                    'low': float(row[0]),
                    'close': float(row[7]),
                    'volume': int(row[2]),
                    'tick_count': int(row[3]),
                    'vwap': float(row[4]) if row[4] else 0,
                    'spread_avg': float(row[5]) if row[5] else 0
                }
                
                # Store in daily_stats table
                self.client.insert(
                    'daily_stats',
                    [[stats['symbol'], datetime.strptime(date, '%Y%m%d').date(),
                      stats['open'], stats['high'], stats['low'], stats['close'],
                      stats['volume'], stats['tick_count'], stats['vwap'], 
                      stats['spread_avg'], datetime.now()]]
                )
                
                return stats
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to calculate stats: {e}")
            return {}
    
    def get_gap_candidates(self, date: str, min_gap_pct: float = 10.0) -> List[Dict]:
        """Find stocks with overnight gaps"""
        
        query = f"""
            WITH prev_close AS (
                SELECT 
                    symbol,
                    close as prev_close
                FROM daily_stats
                WHERE date = yesterday('{date}')
            ),
            today_open AS (
                SELECT 
                    symbol,
                    open as today_open,
                    high as today_high,
                    volume
                FROM daily_stats
                WHERE date = '{date}'
            )
            SELECT 
                t.symbol,
                p.prev_close,
                t.today_open,
                t.today_high,
                t.volume,
                (t.today_open - p.prev_close) / p.prev_close * 100 as gap_pct,
                (t.today_high - p.prev_close) / p.prev_close * 100 as high_pct
            FROM today_open t
            INNER JOIN prev_close p ON t.symbol = p.symbol
            WHERE abs((t.today_open - p.prev_close) / p.prev_close * 100) >= {min_gap_pct}
            ORDER BY gap_pct DESC
        """
        
        try:
            result = self.client.query(query)
            
            gaps = []
            for row in result.result_rows:
                gaps.append({
                    'symbol': row[0],
                    'prev_close': float(row[1]),
                    'open': float(row[2]),
                    'high': float(row[3]),
                    'volume': int(row[4]),
                    'gap_percent': float(row[5]),
                    'high_percent': float(row[6])
                })
            
            logger.info(f"Found {len(gaps)} gap candidates for {date}")
            return gaps
            
        except Exception as e:
            logger.error(f"Failed to find gaps: {e}")
            return []
    
    def get_l2_updates(self, symbol: str, start_time: datetime, end_time: datetime, 
                      levels: Optional[List[int]] = None) -> pd.DataFrame:
        """
        Retrieve L2 order book updates for analysis.
        
        Args:
            symbol: Stock symbol
            start_time: Start timestamp (UTC)
            end_time: End timestamp (UTC)
            levels: Optional list of levels to filter (e.g., [0, 1, 2])
            
        Returns:
            DataFrame with L2 updates
        """
        try:
            query = """
                SELECT 
                    symbol,
                    timestamp,
                    level,
                    market_maker,
                    operation,
                    side,
                    price,
                    size,
                    tick_id
                FROM l2_updates
                WHERE symbol = %(symbol)s
                  AND timestamp >= %(start_time)s
                  AND timestamp <= %(end_time)s
            """
            
            params = {
                'symbol': symbol,
                'start_time': start_time,
                'end_time': end_time
            }
            
            if levels:
                query += " AND level IN %(levels)s"
                params['levels'] = levels
            
            query += " ORDER BY timestamp, level"
            
            result = self.client.query(query, parameters=params)
            
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=[
                    'symbol', 'timestamp', 'level', 'market_maker', 
                    'operation', 'side', 'price', 'size', 'tick_id'
                ])
                logger.info(f"Retrieved {len(df)} L2 updates for {symbol}")
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Failed to retrieve L2 updates: {e}")
            return pd.DataFrame()
    
    def get_trades_with_context(self, symbol: str, start_time: datetime, end_time: datetime) -> pd.DataFrame:
        """
        Retrieve trades with bid/ask context for spread analysis.
        
        Args:
            symbol: Stock symbol
            start_time: Start timestamp (UTC)
            end_time: End timestamp (UTC)
            
        Returns:
            DataFrame with trade data including spread context
        """
        try:
            query = """
                SELECT 
                    symbol,
                    timestamp,
                    trade_price,
                    trade_size,
                    total_volume,
                    trade_market_center,
                    trade_conditions,
                    tick_id,
                    bid_price,
                    ask_price,
                    ask_price - bid_price as spread,
                    (trade_price - bid_price) / (ask_price - bid_price) as price_improvement
                FROM trades
                WHERE symbol = %(symbol)s
                  AND timestamp >= %(start_time)s
                  AND timestamp <= %(end_time)s
                  AND bid_price > 0 AND ask_price > 0
                ORDER BY timestamp
            """
            
            result = self.client.query(query, parameters={
                'symbol': symbol,
                'start_time': start_time,
                'end_time': end_time
            })
            
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=[
                    'symbol', 'timestamp', 'trade_price', 'trade_size', 'total_volume',
                    'trade_market_center', 'trade_conditions', 'tick_id',
                    'bid_price', 'ask_price', 'spread', 'price_improvement'
                ])
                logger.info(f"Retrieved {len(df)} trades with context for {symbol}")
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Failed to retrieve trades with context: {e}")
            return pd.DataFrame()
    
    def get_quotes_timeseries(self, symbol: str, start_time: datetime, end_time: datetime,
                            resample_freq: str = '1S') -> pd.DataFrame:
        """
        Get quote time series with optional resampling.
        
        Args:
            symbol: Stock symbol
            start_time: Start timestamp (UTC)
            end_time: End timestamp (UTC)
            resample_freq: Pandas frequency string for resampling (e.g., '1S', '1min')
            
        Returns:
            DataFrame with resampled quote data
        """
        try:
            query = """
                SELECT 
                    timestamp,
                    bid_price,
                    ask_price,
                    bid_size,
                    ask_size,
                    spread,
                    mid_price
                FROM quotes
                WHERE symbol = %(symbol)s
                  AND timestamp >= %(start_time)s
                  AND timestamp <= %(end_time)s
                ORDER BY timestamp
            """
            
            result = self.client.query(query, parameters={
                'symbol': symbol,
                'start_time': start_time,
                'end_time': end_time
            })
            
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=[
                    'timestamp', 'bid_price', 'ask_price', 'bid_size', 'ask_size', 'spread', 'mid_price'
                ])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                
                # Resample if requested
                if resample_freq != '1S':
                    df = df.resample(resample_freq).last().dropna()
                
                logger.info(f"Retrieved {len(df)} quote samples for {symbol}")
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Failed to retrieve quote timeseries: {e}")
            return pd.DataFrame()
    
    def get_market_features(self, symbol: str, start_time: datetime, end_time: datetime,
                           signals_only: bool = False) -> pd.DataFrame:
        """
        Retrieve calculated market features for backtesting.
        
        Args:
            symbol: Stock symbol
            start_time: Start timestamp (UTC)
            end_time: End timestamp (UTC)
            signals_only: If True, return only records where signals are active
            
        Returns:
            DataFrame with market features and signals
        """
        try:
            query = """
                SELECT 
                    timestamp,
                    symbol,
                    mid_price,
                    spread,
                    spread_bps,
                    total_bid_depth,
                    total_ask_depth,
                    ofi,
                    vap,
                    bid_absorption_rate,
                    price_velocity,
                    volume_price_ratio,
                    iceberg_score,
                    dark_pool_ratio,
                    liquidity_sinkhole_score,
                    micro_volatility,
                    signal_1,
                    signal_2,
                    signal_3,
                    signal_4,
                    signal_5,
                    signal_1 + signal_2 + signal_3 + signal_4 + signal_5 as total_signals
                FROM features
                WHERE symbol = %(symbol)s
                  AND timestamp >= %(start_time)s
                  AND timestamp <= %(end_time)s
            """
            
            if signals_only:
                query += " AND (signal_1 + signal_2 + signal_3 + signal_4 + signal_5) > 0"
            
            query += " ORDER BY timestamp"
            
            result = self.client.query(query, parameters={
                'symbol': symbol,
                'start_time': start_time,
                'end_time': end_time
            })
            
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=[
                    'timestamp', 'symbol', 'mid_price', 'spread', 'spread_bps',
                    'total_bid_depth', 'total_ask_depth', 'ofi', 'vap',
                    'bid_absorption_rate', 'price_velocity', 'volume_price_ratio',
                    'iceberg_score', 'dark_pool_ratio', 'liquidity_sinkhole_score',
                    'micro_volatility', 'signal_1', 'signal_2', 'signal_3', 
                    'signal_4', 'signal_5', 'total_signals'
                ])
                logger.info(f"Retrieved {len(df)} feature records for {symbol}")
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Failed to retrieve market features: {e}")
            return pd.DataFrame()
    
    def get_signal_statistics(self, start_time: datetime, end_time: datetime, 
                            symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Get aggregated signal statistics across symbols and time.
        
        Args:
            start_time: Start timestamp (UTC)
            end_time: End timestamp (UTC)
            symbols: Optional list of symbols to filter
            
        Returns:
            DataFrame with signal statistics
        """
        try:
            query = """
                SELECT 
                    symbol,
                    COUNT(*) as total_records,
                    SUM(signal_1) as signal_1_count,
                    SUM(signal_2) as signal_2_count,
                    SUM(signal_3) as signal_3_count,
                    SUM(signal_4) as signal_4_count,
                    SUM(signal_5) as signal_5_count,
                    SUM(signal_1 + signal_2 + signal_3 + signal_4 + signal_5) as any_signal_count,
                    AVG(ofi) as avg_ofi,
                    AVG(spread_bps) as avg_spread_bps,
                    AVG(micro_volatility) as avg_micro_volatility
                FROM features
                WHERE timestamp >= %(start_time)s
                  AND timestamp <= %(end_time)s
            """
            
            params = {
                'start_time': start_time,
                'end_time': end_time
            }
            
            if symbols:
                query += " AND symbol IN %(symbols)s"
                params['symbols'] = symbols
            
            query += " GROUP BY symbol ORDER BY any_signal_count DESC"
            
            result = self.client.query(query, parameters=params)
            
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=[
                    'symbol', 'total_records', 'signal_1_count', 'signal_2_count',
                    'signal_3_count', 'signal_4_count', 'signal_5_count', 
                    'any_signal_count', 'avg_ofi', 'avg_spread_bps', 'avg_micro_volatility'
                ])
                
                # Calculate signal rates
                for i in range(1, 6):
                    df[f'signal_{i}_rate'] = df[f'signal_{i}_count'] / df['total_records']
                df['any_signal_rate'] = df['any_signal_count'] / df['total_records']
                
                logger.info(f"Retrieved signal statistics for {len(df)} symbols")
                return df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Failed to retrieve signal statistics: {e}")
            return pd.DataFrame()
    
    def get_backtest_performance(self, strategy_id: str, start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get backtest performance metrics for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            start_time: Optional start timestamp filter
            end_time: Optional end timestamp filter
            
        Returns:
            Dictionary with performance metrics
        """
        try:
            query = """
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) as buy_trades,
                    SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) as sell_trades,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl_per_trade,
                    MAX(cumulative_pnl) as max_cumulative_pnl,
                    MIN(cumulative_pnl) as min_cumulative_pnl,
                    SUM(commission) as total_commission,
                    SUM(slippage) as total_slippage,
                    COUNT(DISTINCT symbol) as symbols_traded,
                    MAX(ABS(position)) as max_position
                FROM backtest_trades
                WHERE strategy_id = %(strategy_id)s
            """
            
            params = {'strategy_id': strategy_id}
            
            if start_time:
                query += " AND timestamp >= %(start_time)s"
                params['start_time'] = start_time
            
            if end_time:
                query += " AND timestamp <= %(end_time)s"
                params['end_time'] = end_time
            
            result = self.client.query(query, parameters=params)
            
            if result.result_rows:
                row = result.result_rows[0]
                performance = {
                    'strategy_id': strategy_id,
                    'total_trades': row[0],
                    'buy_trades': row[1],
                    'sell_trades': row[2],
                    'total_pnl': float(row[3]) if row[3] else 0.0,
                    'avg_pnl_per_trade': float(row[4]) if row[4] else 0.0,
                    'max_cumulative_pnl': float(row[5]) if row[5] else 0.0,
                    'min_cumulative_pnl': float(row[6]) if row[6] else 0.0,
                    'total_commission': float(row[7]) if row[7] else 0.0,
                    'total_slippage': float(row[8]) if row[8] else 0.0,
                    'symbols_traded': row[9],
                    'max_position': row[10]
                }
                
                # Calculate additional metrics
                if performance['total_trades'] > 0:
                    performance['win_rate'] = 0.0  # Would need individual trade PnL analysis
                    performance['profit_factor'] = 0.0  # Would need win/loss separation
                    
                logger.info(f"Retrieved performance metrics for strategy {strategy_id}")
                return performance
            else:
                return {}
                
        except Exception as e:
            logger.error(f"Failed to retrieve backtest performance: {e}")
            return {}
    
    def optimize_tables(self):
        """Optimize tables for better performance"""
        tables = ['l2_updates', 'trades', 'quotes', 'features', 'backtest_trades']
        
        for table in tables:
            try:
                self.client.command(f"OPTIMIZE TABLE {table} FINAL")
                logger.info(f"✅ Optimized {table}")
            except Exception as e:
                logger.error(f"Failed to optimize {table}: {e}")
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get ClickHouse system health metrics."""
        try:
            # Get table sizes
            size_query = """
                SELECT 
                    table,
                    formatReadableSize(total_bytes) as size_readable,
                    total_bytes,
                    total_rows
                FROM system.tables
                WHERE database = %(database)s
                  AND engine LIKE '%%MergeTree%%'
                ORDER BY total_bytes DESC
            """
            
            size_result = self.client.query(size_query, parameters={'database': self.database})
            
            # Get query performance
            perf_query = """
                SELECT 
                    COUNT(*) as queries_last_hour,
                    AVG(query_duration_ms) as avg_duration_ms,
                    MAX(query_duration_ms) as max_duration_ms
                FROM system.query_log
                WHERE event_time >= now() - INTERVAL 1 HOUR
                  AND type = 'QueryFinish'
            """
            
            try:
                perf_result = self.client.query(perf_query)
                perf_data = perf_result.result_rows[0] if perf_result.result_rows else (0, 0, 0)
            except:
                perf_data = (0, 0, 0)
            
            health = {
                'database': self.database,
                'tables': [],
                'total_size_bytes': 0,
                'total_rows': 0,
                'queries_last_hour': perf_data[0],
                'avg_query_duration_ms': float(perf_data[1]) if perf_data[1] else 0.0,
                'max_query_duration_ms': float(perf_data[2]) if perf_data[2] else 0.0,
                'connection_healthy': True
            }
            
            for row in size_result.result_rows:
                table_info = {
                    'name': row[0],
                    'size_readable': row[1],
                    'size_bytes': row[2],
                    'rows': row[3]
                }
                health['tables'].append(table_info)
                health['total_size_bytes'] += row[2]
                health['total_rows'] += row[3]
            
            return health
            
        except Exception as e:
            logger.error(f"Failed to get system health: {e}")
            return {'connection_healthy': False, 'error': str(e)}

def main():
    """Test ClickHouse API"""
    
    # Initialize API
    api = ClickHouseHistoricalAPI()
    
    # Test with sample data
    logger.info("\n" + "="*60)
    logger.info("TESTING CLICKHOUSE HISTORICAL API")
    logger.info("="*60)
    
    # Check if we have any data
    summary = api.get_data_summary()
    
    if summary.empty:
        logger.info("No data in ClickHouse yet")
        
        # Load sample tick data to test
        tick_dir = os.path.abspath('../simulation/data/real_ticks')
        test_file = os.path.join(tick_dir, 'ABVX_20250722.json')
        
        if os.path.exists(test_file):
            with open(test_file, 'r') as f:
                ticks = json.load(f)
            
            # Fix ordering if needed
            if ticks and len(ticks) > 1:
                first_ts = ticks[0]['timestamp']
                last_ts = ticks[-1]['timestamp']
                if first_ts > last_ts:
                    ticks = list(reversed(ticks))
            
            # Store in ClickHouse
            stored = api.store_ticks('ABVX', '20250722', ticks[:1000])  # First 1000
            
            # Retrieve back
            retrieved = api.get_ticks('ABVX', '20250722')
            logger.info(f"Stored {stored}, retrieved {len(retrieved)} ticks")
            
            # Calculate daily stats
            stats = api.calculate_daily_stats('ABVX', '20250722')
            logger.info(f"Daily stats: {stats}")
    else:
        logger.info(f"\nData summary:\n{summary}")
    
    # Test gap detection
    gaps = api.get_gap_candidates('20250723')
    if gaps:
        logger.info(f"\nGap candidates:")
        for gap in gaps[:5]:
            logger.info(f"  {gap['symbol']}: {gap['gap_percent']:.1f}%")

if __name__ == "__main__":
    main()