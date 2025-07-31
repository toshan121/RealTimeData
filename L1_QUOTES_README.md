# L1 Quotes System

Simple, professional-grade Level 1 quotes display for the Django trading system.

## Features

- **Live L1 Quotes**: Real-time bid/ask/spread display from Redis cache
- **Bloomberg-style UI**: Professional dark theme with color-coded quotes
- **Watchlist Management**: Simple session-based watchlist with CRUD operations
- **Market Status**: Live market hours detection and data availability status
- **Quote Quality**: Data aging and spread analysis indicators
- **Real-time Updates**: Auto-refresh every 2 seconds with manual refresh option
- **Market Replay**: Basic integration with historical data replay system

## Quick Start

### 1. Start the Django Server

```bash
cd ui/
python manage.py runserver 8000
```

### 2. Generate Test Data

```bash
# Generate sample L1 quotes in Redis
python test_l1_data_generator.py generate 1

# Start continuous data generation (for testing)
python test_l1_data_generator.py continuous
```

### 3. Access the L1 Quotes Dashboard

Open your browser to: `http://localhost:8000/monitor/l1-quotes/`

## API Endpoints

### Live Quotes
```
GET /monitor/api/downloader/l1-quotes/live_quotes/?symbols=AAPL,GOOGL,MSFT
```

### Watchlist Management
```
GET /monitor/api/downloader/l1-quotes/watchlist/
POST /monitor/api/downloader/l1-quotes/update_watchlist/
```

### Market Status
```
GET /monitor/api/downloader/l1-quotes/market_status/
```

### Historical Quotes
```
GET /monitor/api/downloader/l1-quotes/historical_quotes/?symbol=AAPL&date=2025-07-29
```

### Real-time Stream (SSE)
```
GET /monitor/api/downloader/l1-quotes/stream_quotes/?symbols=AAPL,GOOGL
```

### Market Replay Control
```
GET /monitor/api/downloader/l1-quotes/replay_control/?action=status
GET /monitor/api/downloader/l1-quotes/replay_control/?action=start&date=2025-07-29&speed=2.0
GET /monitor/api/downloader/l1-quotes/replay_control/?action=stop
```

## Data Format

### L1 Quote Structure
```json
{
  "symbol": "AAPL",
  "bid": 150.25,
  "ask": 150.30,
  "bid_size": 100,
  "ask_size": 200,
  "spread": 0.05,
  "spread_pct": 0.033,
  "last_price": 150.28,
  "last_size": 50,
  "timestamp": "2025-07-29T10:30:00Z",
  "age_seconds": 1.5,
  "data_quality": "tight_spread"
}
```

## Redis Keys

L1 quotes are stored in Redis with keys:
```
market:l1:{SYMBOL}:latest
```

Example:
```
market:l1:AAPL:latest
market:l1:GOOGL:latest
```

## UI Features

### Quote Grid
- **Symbol**: Stock symbol in cyan
- **Bid/Ask**: Green bid, red ask prices
- **Sizes**: Bid/ask sizes in gray
- **Spread**: Absolute and percentage spread
- **Last Trade**: Yellow last trade price and size
- **Age**: Quote freshness indicator
- **Quality**: Color-coded data quality indicator

### Color Coding
- **Green**: Good data, tight spreads, fresh quotes
- **Yellow**: Warning conditions, normal spreads, slightly stale
- **Red**: Error conditions, wide spreads, old quotes
- **Gray**: No data available

### Controls
- **Watchlist Input**: Comma-separated symbols (e.g., "AAPL,GOOGL,MSFT")
- **Auto Refresh**: Toggle automatic updates (2-second interval)
- **Manual Refresh**: Force immediate update

## Testing

### Run Unit Tests
```bash
cd ui/
python manage.py test monitor.test_l1_quotes
```

### Generate Test Data
```bash
# Generate one-time test data
python test_l1_data_generator.py generate 1

# Show current data in Redis
python test_l1_data_generator.py show

# Clear test data
python test_l1_data_generator.py clear
```

## Integration Points

### Redis Cache Manager
Uses the existing `RedisCacheManager` from `/home/tcr1n15/PycharmProjects/RealTimeData/processing/redis_cache_manager.py`

### ClickHouse Historical API  
Integrates with `ClickHouseHistoricalAPI` for historical quote data

### Market Replay System
Basic integration with the historical replayer in `/home/tcr1n15/PycharmProjects/RealTimeData/realtime/replay/`

## Architecture 

```
Browser (L1 UI) 
    ↕ 
Django L1 Views/APIs
    ↕
Redis (Live Data) + ClickHouse (Historical)
    ↕
Market Data Pipeline (IQFeed/Kafka/Processing)
```

## Dependencies

- Django 5.0+
- Django REST Framework
- Redis (port 6380)
- ClickHouse (optional, for historical data)
- Modern browser with SSE support

## Development Notes

This system follows the "keep it simple" principle:

- **No overengineering**: Simple, direct API endpoints
- **Session-based watchlists**: No complex user models
- **Basic SSE**: Simple real-time updates without WebSockets
- **Mock replay**: Placeholder integration for market replay
- **Minimal dependencies**: Uses existing Redis/ClickHouse infrastructure

The focus is on providing a clean, professional L1 quotes display that integrates seamlessly with the existing trading system infrastructure.