-- Market Data Schema for ClickHouse - Unified Optimized Schema
-- High-performance time-series schema for L2 market microstructure analysis
-- Optimized for 2000 symbols with 10μs update latency requirement

-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS l2_market_data;
USE l2_market_data;

-- Create user and grant permissions
CREATE USER IF NOT EXISTS l2_user IDENTIFIED BY 'l2_secure_pass';
GRANT ALL ON l2_market_data.* TO l2_user;

-- ========================================================================
-- CORE MARKET DATA TABLES
-- ========================================================================

-- L2 Order Book Updates Table
-- Optimized for high-frequency L2 updates with proper partitioning
CREATE TABLE IF NOT EXISTS l2_updates (
    symbol String,
    timestamp DateTime64(6, 'UTC'),
    level UInt8,
    market_maker String,
    operation UInt8,  -- 0=Insert, 1=Update, 2=Delete
    side UInt8,       -- 0=Ask, 1=Bid
    price Decimal64(8),
    size UInt32,
    tick_id UInt64,
    ingestion_time DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    date Date MATERIALIZED toDate(timestamp),
    hour UInt8 MATERIALIZED toHour(timestamp)
) ENGINE = MergeTree()
PARTITION BY (date, intHash32(symbol) % 20)  -- 20 partitions per day for load balancing
ORDER BY (symbol, timestamp, tick_id)
SETTINGS index_granularity = 8192,
         merge_with_ttl_timeout = 300,
         parts_to_delay_insert = 300,
         parts_to_throw_insert = 500;

-- Trade Executions Table  
-- Optimized for tick-by-tick trade data
CREATE TABLE IF NOT EXISTS trades (
    symbol String,
    timestamp DateTime64(6, 'UTC'),
    trade_price Decimal64(8),
    trade_size UInt32,
    total_volume UInt64,
    trade_market_center String,
    trade_conditions String,
    tick_id UInt64,
    bid_price Decimal64(8),
    ask_price Decimal64(8),
    ingestion_time DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    date Date MATERIALIZED toDate(timestamp),
    hour UInt8 MATERIALIZED toHour(timestamp)
) ENGINE = MergeTree()
PARTITION BY (date, intHash32(symbol) % 20)
ORDER BY (symbol, timestamp, tick_id)
SETTINGS index_granularity = 8192,
         merge_with_ttl_timeout = 300;

-- NBBO Quotes Table
-- Optimized for Level 1 quote updates
CREATE TABLE IF NOT EXISTS quotes (
    symbol String,
    timestamp DateTime64(6, 'UTC'),
    bid_price Decimal64(8),
    bid_size UInt32,
    ask_price Decimal64(8),
    ask_size UInt32,
    bid_market_center String,
    ask_market_center String,
    tick_id UInt64,
    spread Decimal64(8) MATERIALIZED ask_price - bid_price,
    mid_price Decimal64(8) MATERIALIZED (bid_price + ask_price) / 2,
    ingestion_time DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    date Date MATERIALIZED toDate(timestamp),
    hour UInt8 MATERIALIZED toHour(timestamp)
) ENGINE = MergeTree()
PARTITION BY (date, intHash32(symbol) % 20)
ORDER BY (symbol, timestamp, tick_id)
SETTINGS index_granularity = 8192,
         merge_with_ttl_timeout = 300;

-- Market Features Table
-- Calculated microstructure features for backtesting and signal detection
CREATE TABLE IF NOT EXISTS features (
    symbol String,
    timestamp DateTime64(6, 'UTC'),
    mid_price Decimal64(8),
    spread Decimal64(8),
    spread_bps UInt16,                -- Spread in basis points
    total_bid_depth UInt64,
    total_ask_depth UInt64,
    ofi Float32,                      -- Order Flow Imbalance
    vap Float32,                      -- Volume at Price
    bid_absorption_rate Float32,
    price_velocity Float32,
    volume_price_ratio Float32,
    iceberg_score Float32,
    dark_pool_ratio Float32,
    liquidity_sinkhole_score Float32,
    micro_volatility Float32,
    signal_1 UInt8,                   -- Sustained Bid-Side Absorption
    signal_2 UInt8,                   -- Controlled Price Creep  
    signal_3 UInt8,                   -- Dark Pool Inference
    signal_4 UInt8,                   -- Liquidity Sinkhole
    signal_5 UInt8,                   -- Micro-Volatility Contraction
    ingestion_time DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    date Date MATERIALIZED toDate(timestamp),
    hour UInt8 MATERIALIZED toHour(timestamp)
) ENGINE = MergeTree()
PARTITION BY (date, intHash32(symbol) % 20)
ORDER BY (symbol, timestamp)
SETTINGS index_granularity = 8192,
         merge_with_ttl_timeout = 300;

-- Backtest Results Table
-- Store backtesting results for strategy evaluation
CREATE TABLE IF NOT EXISTS backtest_trades (
    strategy_id String,
    symbol String,
    timestamp DateTime64(6, 'UTC'),
    side String,                      -- 'BUY' or 'SELL'
    quantity UInt32,
    price Decimal64(8),
    commission Decimal64(8),
    slippage Decimal64(8),
    pnl Decimal64(8),
    cumulative_pnl Decimal64(8),
    position Int32,                   -- Can be negative for short positions
    signal_triggered String,
    metadata String,                  -- JSON metadata for additional info
    ingestion_time DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    date Date MATERIALIZED toDate(timestamp)
) ENGINE = MergeTree()
PARTITION BY (date, strategy_id)
ORDER BY (strategy_id, symbol, timestamp)
SETTINGS index_granularity = 8192;

-- ========================================================================
-- PERFORMANCE OPTIMIZED MATERIALIZED VIEWS
-- ========================================================================

-- Latest Quote View for Real-time Monitoring
-- Provides current market state for each symbol
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_latest_quotes
ENGINE = ReplacingMergeTree(ingestion_time)
PARTITION BY date
ORDER BY symbol
AS SELECT
    symbol,
    timestamp,
    bid_price,
    ask_price,
    bid_size,
    ask_size,
    spread,
    mid_price,
    ingestion_time,
    date
FROM quotes;

-- OHLCV Minute Bars from Trades
-- Real-time aggregation for charting and analysis
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_trades_ohlcv_1m
ENGINE = SummingMergeTree((volume, trade_count, total_notional))
PARTITION BY (date, symbol)
ORDER BY (symbol, minute)
AS SELECT
    symbol,
    toStartOfMinute(timestamp) as minute,
    toDate(timestamp) as date,
    argMin(trade_price, timestamp) as open,
    max(trade_price) as high,
    min(trade_price) as low,
    argMax(trade_price, timestamp) as close,
    sum(trade_size) as volume,
    count() as trade_count,
    sum(trade_price * trade_size) as total_notional,
    sum(trade_price * trade_size) / sum(trade_size) as vwap
FROM trades
GROUP BY symbol, minute, date;

-- Order Flow Imbalance Aggregation
-- Track OFI patterns for accumulation detection
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ofi_aggregated
ENGINE = SummingMergeTree((ofi_sum, update_count))
PARTITION BY (date, symbol)
ORDER BY (symbol, minute)
AS SELECT
    symbol,
    toStartOfMinute(timestamp) as minute,
    toDate(timestamp) as date,
    sum(ofi) as ofi_sum,
    count() as update_count,
    avg(ofi) as ofi_avg,
    max(ofi) as ofi_max,
    min(ofi) as ofi_min
FROM features
WHERE ofi != 0
GROUP BY symbol, minute, date;

-- ========================================================================
-- HIGH PERFORMANCE INDEXES
-- ========================================================================

-- Symbol indexes for fast filtering
CREATE INDEX IF NOT EXISTS idx_l2_symbol ON l2_updates (symbol) TYPE bloom_filter GRANULARITY 1;
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol) TYPE bloom_filter GRANULARITY 1;
CREATE INDEX IF NOT EXISTS idx_quotes_symbol ON quotes (symbol) TYPE bloom_filter GRANULARITY 1;
CREATE INDEX IF NOT EXISTS idx_features_symbol ON features (symbol) TYPE bloom_filter GRANULARITY 1;

-- Price range indexes for efficient range queries
CREATE INDEX IF NOT EXISTS idx_l2_price_range ON l2_updates (price) TYPE minmax GRANULARITY 8;
CREATE INDEX IF NOT EXISTS idx_trades_price_range ON trades (trade_price) TYPE minmax GRANULARITY 8;
CREATE INDEX IF NOT EXISTS idx_quotes_bid_range ON quotes (bid_price) TYPE minmax GRANULARITY 8;
CREATE INDEX IF NOT EXISTS idx_quotes_ask_range ON quotes (ask_price) TYPE minmax GRANULARITY 8;
CREATE INDEX IF NOT EXISTS idx_features_mid_range ON features (mid_price) TYPE minmax GRANULARITY 8;

-- Signal indexes for backtesting queries
CREATE INDEX IF NOT EXISTS idx_features_signals ON features (signal_1, signal_2, signal_3, signal_4, signal_5) TYPE bloom_filter GRANULARITY 1;

-- Time-based indexes for temporal queries
CREATE INDEX IF NOT EXISTS idx_l2_hour ON l2_updates (hour) TYPE set(0) GRANULARITY 1;
CREATE INDEX IF NOT EXISTS idx_trades_hour ON trades (hour) TYPE set(0) GRANULARITY 1;
CREATE INDEX IF NOT EXISTS idx_quotes_hour ON quotes (hour) TYPE set(0) GRANULARITY 1;

-- ========================================================================
-- VERIFY SCHEMA CREATION
-- ========================================================================

-- Insert test records to verify tables are working
INSERT INTO l2_updates (symbol, timestamp, level, market_maker, operation, side, price, size, tick_id) 
VALUES ('TEST', now64(6, 'UTC'), 0, 'TEST_MM', 0, 1, 100.00, 1000, 1);

INSERT INTO trades (symbol, timestamp, trade_price, trade_size, total_volume, trade_market_center, trade_conditions, tick_id, bid_price, ask_price)
VALUES ('TEST', now64(6, 'UTC'), 100.01, 500, 500, 'TEST', 'F', 2, 100.00, 100.02);

INSERT INTO quotes (symbol, timestamp, bid_price, bid_size, ask_price, ask_size, bid_market_center, ask_market_center, tick_id)
VALUES ('TEST', now64(6, 'UTC'), 100.00, 1000, 100.02, 800, 'TEST_BID', 'TEST_ASK', 3);

-- Verify all tables were created successfully
SELECT 'Tables created:' as status;
SHOW TABLES FROM l2_market_data;

SELECT 'Materialized views created:' as status;  
SELECT name FROM system.tables WHERE database = 'l2_market_data' AND engine LIKE '%Materialized%';

SELECT 'Schema validation complete' as status;