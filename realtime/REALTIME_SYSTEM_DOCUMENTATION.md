# Real-time Trading System Documentation

## Overview

This document provides comprehensive documentation for the L2 Real-time Trading System, a production-grade microstructure analysis platform designed for detecting stealthy pre-pump accumulation patterns using IQFeed real-time Level 2 data.

**CRITICAL PRINCIPLE**: This system prioritizes **EXCELLENT DATA INTEGRITY AND RELIABILITY** over raw speed. Money is on the line - no fakes, no mocks, all real data validation.

## System Architecture

### Core Data Flow
```
IQFeed Real-time → OUR IQFeed Client → Kafka Streaming → Redis Cache → UI Components
                                   ↓
                         ClickHouse Storage (Persistent)
```

### Key Design Principles
1. **Data Integrity First**: Every component validates real data, no simulation shortcuts
2. **Backend Independence**: UI system works completely standalone for testing
3. **Production Ready**: Built for real money trading with comprehensive error handling
4. **Weekend Testing**: Historical replay enables continuous development without live markets

## Directory Structure

```
realtime/
├── core/                    # Core system components
│   ├── iqfeed_realtime_client.py    # Primary IQFeed interface
│   ├── kafka_producer.py            # High-performance Kafka producer
│   ├── redis_metrics.py             # Redis connection and metrics
│   └── clickhouse_client.py         # ClickHouse storage interface
├── ui/                      # User interface system
│   ├── components/          # Modular UI components
│   │   ├── historical_simulator.py      # Backend-independent replay control
│   │   ├── l1_tape_display.py           # Real-time L1 quotes and tape
│   │   ├── candlestick_chart.py         # Professional charting
│   │   ├── data_downloader.py           # Historical data management
│   │   ├── clickhouse_viewer.py         # Data validation and browsing
│   │   ├── redis_monitor.py             # Redis monitoring and cleanup
│   │   └── kafka_stream_viewer.py       # Live Kafka message streams
│   ├── pages/               # Streamlit page modules
│   │   ├── 2_📥_Data_Manager.py         # Data download and validation
│   │   ├── 3_📊_Live_Trading.py         # Professional trading interface
│   │   └── 4_🔧_System_Monitor.py       # System health monitoring
│   ├── services/            # Background services
│   │   ├── redis_cleaner.py             # Redis memory management
│   │   └── kafka_consumer.py            # Kafka to Redis bridge
│   └── 🏠_Home.py           # Main application entry point
├── scripts/                 # Standalone scripts
│   └── historical_data_replay.py    # Historical data replay system
├── monitoring/              # System monitoring
│   └── network_monitor.py           # Network performance monitoring
└── tests/                   # Comprehensive test suite
    └── test_*.py            # Unit tests with REAL data only
```

## Core Components

### 1. IQFeed Real-time Client (`core/iqfeed_realtime_client.py`)

**Purpose**: Primary interface to IQFeed data with production-grade reliability

**Key Features**:
- Real-time L1 and L2 data streaming
- Auto-downloader integration with data existence validation
- Comprehensive error handling and reconnection logic
- Latency measurement (IQFeed timestamp vs system timestamp)
- ClickHouse storage integration

**Data Integrity Measures**:
- Validates every message timestamp
- Checks data completeness before storage
- Implements backpressure handling
- Logs all connection issues for debugging

**Example Usage**:
```python
config = {
    'iqfeed': {'host': '127.0.0.1', 'ports': {'level1': 5009, 'level2': 5010}},
    'clickhouse': {'host': 'localhost', 'port': 8123, 'database': 'l2_market_data'}
}
client = IQFeedRealTimeClient(config)
success = client.download_historical_data('AAPL', '20250724')
```

### 2. Historical Data Replay System (`scripts/historical_data_replay.py`)

**Purpose**: Backend-independent replay of recorded market data for continuous testing

**Key Features**:
- Multi-symbol simultaneous replay
- Temporal synchronization preservation
- Speed control (0.1x to 100x real-time)
- L1 and tick data streaming
- L2 reconstruction from tick+L1 data (highly realistic)

**Data Integrity Focus**:
- Preserves original timestamps exactly
- Maintains inter-message timing relationships
- Validates data completeness before replay
- Real data only - no synthetic generation

**Replay Capabilities**:
```bash
# Multi-symbol real-time replay
python realtime/scripts/historical_data_replay.py --symbols AAPL TSLA MSFT --date 20250724 --speed 1.0

# High-speed testing
python realtime/scripts/historical_data_replay.py --symbols AAPL --date 20250724 --speed 50.0 --max-messages 10000

# List available data
python realtime/scripts/historical_data_replay.py --list-data
```

**Technical Details**:
- Combines tick and L1 data chronologically
- Sends to `market_ticks` and `market_l1s` Kafka topics
- Supports message limiting and batching
- Implements proper Kafka producer flushing

### 3. Professional Trading UI System (`ui/`)

**Purpose**: ThinkOrSwim-grade interface for system validation and monitoring

#### Historical Simulator Component (`ui/components/historical_simulator.py`)
- **Backend Independence**: Complete replay control from UI
- **Quick Presets**: Popular stocks, speed tests, multi-symbol configurations
- **Advanced Configuration**: Symbol selection, timeframes, concurrent controls
- **Session Management**: Real-time progress tracking, pause/resume/stop
- **Data Browser**: File analysis, coverage metrics, size statistics

#### L1 + Tape Display Component (`ui/components/l1_tape_display.py`)
- **Real-time Quotes**: Live bid/ask/last with color-coded price changes
- **Time & Sales Tape**: Scrolling trade prints with direction indicators
- **Multi-symbol Monitoring**: Dynamic symbol addition/removal
- **Professional Layout**: ThinkOrSwim-style appearance and functionality
- **Price History**: Charts and trend analysis with technical indicators

#### Candlestick Chart Component (`ui/components/candlestick_chart.py`)
- **Professional Charting**: Multiple timeframes (1m, 5m, 15m, 1h, 4h, 1d)
- **Technical Indicators**: SMA, EMA, RSI, VWAP with real-time calculation
- **Volume Analysis**: Color-coded bars with session statistics
- **OHLC Construction**: Real-time bar building from tick data
- **Interactive Features**: Zoom, pan, crosshair functionality

### 4. Data Storage and Validation

#### ClickHouse Integration
- **Database**: `l2_market_data` 
- **Credentials**: `l2_user` / `l2_secure_pass`
- **Port**: 8123 (HTTP interface)
- **Tables**: `market_ticks`, `market_l1`, `market_l2`, `market_trades`, `market_bars_*`

#### Redis Caching System
- **Port**: 6380
- **TTL Management**: Automatic cleanup to prevent memory growth
- **Key Patterns**: `l1:{symbol}`, `ticks:{symbol}`, `market_*:{symbol}`
- **Data Types**: JSON serialized market data with timestamps

#### Kafka Streaming
- **Topics**: `market_ticks`, `market_l1s`, `market_l2`, `live-*`, `realtime-*`
- **Partitioning**: By symbol for ordered processing
- **Producer Settings**: High-throughput, reliable delivery
- **Consumer Groups**: UI components, storage services

## Data Integrity and Reliability

### Real Data Validation
**NO MOCKS, NO FAKES, NO SIMULATION** - All tests use real market data:

1. **Historical Data**: Real tick and L1 data from IQFeed
2. **Timestamps**: Original market timestamps preserved
3. **Volume**: Actual trade volumes and sizes
4. **Prices**: Real bid/ask/trade prices
5. **Timing**: Authentic inter-message timing relationships

### Error Handling
- **Connection Failures**: Automatic reconnection with exponential backoff
- **Data Validation**: Schema and range validation for all messages
- **Storage Failures**: Retry logic with dead letter queues
- **UI Resilience**: Graceful degradation when backend unavailable

### Performance Monitoring
- **Latency Tracking**: IQFeed timestamp vs system processing time
- **Throughput Metrics**: Messages per second, bytes per second
- **Memory Usage**: Redis cache size, cleanup effectiveness
- **Error Rates**: Connection drops, message failures, parsing errors

## Testing Strategy

### Unit Test Requirements
**CRITICAL**: All unit tests MUST use real data - no mocks, no fakes, money is on the line.

#### Test Data Sources
1. **Historical CSV Files**: Real market data in `/data/raw_ticks/`, `/data/raw_l1/`
2. **Live Connection Tests**: Real IQFeed connections during market hours
3. **Replay Validation**: Historical replay accuracy against original data
4. **Storage Validation**: ClickHouse round-trip data integrity

#### Test Categories
1. **Connection Tests**: Real IQFeed connectivity and data reception
2. **Data Processing Tests**: Tick processing, L1 quote handling, storage
3. **Replay Tests**: Historical replay accuracy and timing
4. **UI Tests**: Component integration with real data flows
5. **Storage Tests**: ClickHouse/Redis data integrity
6. **Performance Tests**: Latency and throughput under real conditions

### Example Test Structure
```python
def test_historical_replay_data_integrity():
    """Test that historical replay preserves exact data integrity"""
    # Use REAL recorded data
    original_data = load_real_tick_data('AAPL', '20250724')
    
    # Replay through system
    replayed_data = replay_and_capture('AAPL', '20250724')
    
    # Validate exact match
    assert_timestamps_preserved(original_data, replayed_data)
    assert_prices_exact_match(original_data, replayed_data)
    assert_volumes_exact_match(original_data, replayed_data)
    assert_temporal_order_preserved(replayed_data)
```

## Production Deployment Considerations

### Hardware Requirements
- **GPU**: NVIDIA K1 or newer (CUDA 10.x/9.x compatibility)
- **Memory**: 8GB+ RAM for 2000 symbol processing
- **Storage**: SSD recommended for ClickHouse performance
- **Network**: Low-latency connection to IQFeed servers

### Software Dependencies
- **CUDA**: Version 10.x or 9.x (K1 compatibility)
- **Numba**: Version 0.53.1 or compatible
- **Python**: 3.8+ with specific package versions
- **Docker**: For Kafka, Redis, ClickHouse services

### Security Considerations
- **Credentials**: IQFeed credentials in `.env` only
- **Network**: No external connections from UI components
- **Logging**: Sensitive data excluded from logs
- **Validation**: All inputs sanitized and validated

## Operational Procedures

### Daily Operations
1. **Market Open**: Verify IQFeed connection and data flow
2. **Monitoring**: Check Redis memory usage and Kafka lag
3. **Data Validation**: Spot-check data quality and completeness
4. **Performance**: Monitor latency and throughput metrics

### Weekend Testing
1. **Historical Replay**: Use recorded data for system validation
2. **UI Testing**: Verify all components work without live data
3. **Strategy Development**: Test new algorithms on historical data
4. **Performance Tuning**: Optimize system parameters

### Troubleshooting
1. **Connection Issues**: Check IQFeed client status and restart if needed
2. **Memory Growth**: Run Redis cleanup service or manual cleanup
3. **Data Gaps**: Validate IQFeed connection and re-download if needed
4. **Performance Issues**: Check Kafka consumer lag and partition balancing

## API Reference

### Core Classes

#### IQFeedRealTimeClient
```python
class IQFeedRealTimeClient:
    def download_historical_data(symbol: str, date: str, save_to_clickhouse: bool = True) -> bool
    def start_realtime_stream(symbols: List[str]) -> None
    def stop_realtime_stream() -> None
    def get_connection_status() -> Dict[str, bool]
```

#### HistoricalDataReplayer
```python
class HistoricalDataReplayer:
    def replay_multiple_symbols(symbols: List[str], date: str, replay_speed: float, max_messages_per_symbol: int) -> Dict
    def list_available_data() -> Dict[str, List[str]]
    def stop_replay() -> None
```

### UI Components

#### Historical Simulator
- `render_historical_simulator()`: Main component rendering
- Quick replay presets for common testing scenarios
- Advanced configuration with full parameter control
- Session monitoring with real-time progress updates

#### L1 + Tape Display
- `render_l1_tape_display()`: Professional quotes and tape interface
- Multi-symbol monitoring with dynamic updates
- Price change visualization with color coding
- Historical price tracking and charting

#### Candlestick Charts
- `render_candlestick_chart()`: Professional-grade real-time charting
- Multiple timeframe support with automatic OHLC construction
- Technical indicator overlays (SMA, EMA, RSI, VWAP)
- Volume analysis with session statistics

## Performance Targets

### Latency Requirements
- **L2 Book Updates**: < 10μs per update across 2000 symbols
- **Feature Calculation**: < 100μs for all 5 signals per symbol
- **Kafka Latency**: < 5ms end-to-end processing
- **UI Responsiveness**: < 100ms for user interactions

### Throughput Targets
- **Message Processing**: 1000+ messages/second sustained
- **Symbol Coverage**: 2000 symbols simultaneous processing
- **Data Storage**: 10GB+ daily data volume handling
- **Memory Usage**: < 1GB Redis cache size

### Reliability Targets
- **System Uptime**: > 99% during market hours
- **Data Completeness**: > 99.9% message capture rate
- **Error Recovery**: < 5 second reconnection time
- **Data Integrity**: 100% accuracy in historical replay

## Conclusion

This real-time trading system is built with **PRODUCTION-GRADE DATA INTEGRITY** as the primary concern. Every component has been designed and tested with real market data to ensure reliability when money is on the line.

The system provides complete backend independence for testing while maintaining the highest standards of data accuracy and temporal precision. The comprehensive UI system enables professional-level validation and monitoring comparable to established trading platforms like ThinkOrSwim.

**Remember**: No fakes, no mocks, no shortcuts. Real data, real validation, real reliability.