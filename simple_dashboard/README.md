# Simple Market Data Dashboard

A minimal Django dashboard for monitoring and controlling the 495-stock recording system.

## Quick Start

1. **Start the Dashboard**
   ```bash
   cd simple_dashboard
   python manage.py runserver
   ```
   Access at: http://localhost:8000/

2. **Dashboard Features**

   - **System Status**: Real-time monitoring of Redis, ClickHouse, Kafka, and recording process
   - **Recording Control**: Start/stop recording 495 stocks with L1, L2, and tick data
   - **Simulation Control**: Run synthetic data or replay historical data on separate Kafka topics
   - **Kafka Topics**: Monitor topic health and message offsets
   - **Lag Graph**: Visual representation of network, processing, and total lag over 30 minutes

## How to Use

### Recording Control
- **Start Recording**: Launches `start_495_stock_recording.py` to record 495 stocks
- **Stop Recording**: Terminates the recording process
- Status shows green checkmark when running with PID

### Simulation Options
- **Synthetic Data**: Generates fake market data for testing (AAPL, TSLA, MSFT, NVDA, GOOGL)
- **Replay Historical**: Replays data from a specific date
- Both stream to the 'simulation' Kafka topic (separate from production)

### Monitoring
- **Auto-refresh**: Dashboard updates every 5 seconds (can be disabled)
- **Lag Graph**: Shows average and max lag over time to identify bottlenecks
  - Blue: Network lag (IQFeed to reception)
  - Green: Processing lag (reception to processing)
  - Red: Total lag (end-to-end)
  - Orange: Maximum lag spike

### Health Indicators
- ✅ Green = Service healthy
- ❌ Red = Service down
- Record counts show data accumulation in ClickHouse

## API Endpoints

- `/api/status/` - Get system status
- `/api/recording/` - Control recording (POST: {"action": "start|stop"})
- `/api/simulation/` - Control simulation (POST: {"action": "start|stop", "type": "synthetic|replay"})
- `/api/kafka-check/` - Get Kafka topic details
- `/api/lag-stats/` - Get lag statistics for graph

## Prerequisites

Ensure Docker services are running:
```bash
cd ../infrastructure
docker-compose up -d
```

## Configuration

Edit `dashboard/settings.py` for service endpoints:
- Redis: localhost:6380 (Docker)
- ClickHouse: localhost:8123
- Kafka: localhost:9092