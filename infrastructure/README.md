# L2 Market Data Infrastructure

This directory contains the Docker infrastructure for the L2 market data analysis system, providing:

- **ClickHouse**: Time-series database for market data storage
- **Kafka**: Message streaming for real-time data processing  
- **Redis**: Real-time caching and metrics storage
- **Zookeeper**: Kafka coordination service
- **Kafka UI**: Web interface for Kafka management

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- At least 4GB RAM available for containers
- Ports 2181, 6380, 8080, 8123, 9000, 9092 available

### Setup and Startup

1. **Configure Environment** (optional):
   ```bash
   cp .env.template .env
   # Edit .env with your specific settings
   ```

2. **Start All Services**:
   ```bash
   docker-compose up -d
   ```

3. **Create Kafka Topics**:
   ```bash
   ./scripts/create-topics.sh
   ```

4. **Verify Health**:
   ```bash
   ./scripts/health-check.sh
   ```

## Service Details

### ClickHouse (Time-Series Database)
- **Ports**: 8123 (HTTP), 9000 (TCP)
- **Database**: `l2_market_data`
- **User**: `l2_user` / `l2_secure_pass`
- **Web Interface**: http://localhost:8123/play

### Kafka (Message Streaming)
- **Port**: 9092 (external), 29092 (internal)
- **Topics**: Automatically created for L2 data, trades, quotes
- **Configuration**: Optimized for financial data throughput

### Redis (Caching)
- **Port**: 6380 (mapped from 6379)
- **Memory**: 2GB max with LRU eviction
- **Persistence**: AOF enabled for durability

### Kafka UI (Management Interface)
- **Port**: 8080
- **URL**: http://localhost:8080
- **Features**: Topic management, consumer monitoring

## Data Schema

### ClickHouse Tables
- `market_ticks`: Tick-by-tick trade data
- `market_l1`: Level 1 quotes (NBBO)
- `market_l2`: Level 2 order book data
- `market_metrics`: System monitoring metrics

### Kafka Topics
- `iqfeed.l2.raw`: Raw Level 2 data from IQFeed
- `iqfeed.trades.raw`: Raw trade data
- `iqfeed.quotes.raw`: Raw quote data
- `trading.signals`: Processed trading signals
- `market.features`: Calculated market features

## Operations

### Health Monitoring
```bash
# Check all services
./scripts/health-check.sh

# Individual service checks
docker-compose ps
docker logs l2_kafka
docker logs l2_clickhouse
docker logs l2_redis
```

### Data Management
```bash
# Reset Kafka topics (WARNING: destroys data)
./scripts/reset-kafka.sh

# ClickHouse queries
docker exec -it l2_clickhouse clickhouse-client
```

### Performance Tuning
- ClickHouse: Configured for time-series with proper partitioning
- Kafka: Optimized for financial data with LZ4 compression
- Redis: LRU eviction policy for real-time caching

## Troubleshooting

### Common Issues

1. **Services not starting**: Check port conflicts
   ```bash
   netstat -tlnp | grep -E "(2181|6380|8080|8123|9000|9092)"
   ```

2. **Kafka connection issues**: Verify Zookeeper is healthy
   ```bash
   docker exec l2_zookeeper bash -c "echo ruok | nc localhost 2181"
   ```

3. **ClickHouse permission errors**: Check ulimits and file permissions
   ```bash
   docker logs l2_clickhouse
   ```

### Service Dependencies
Services start in this order:
1. Zookeeper
2. Kafka (waits for Zookeeper health)
3. ClickHouse, Redis (parallel)
4. Kafka UI (waits for Kafka health)

### Resource Requirements
- **Minimum**: 4GB RAM, 2 CPU cores
- **Recommended**: 8GB RAM, 4 CPU cores
- **Storage**: 50GB+ for data retention

## Security Notes
- Default passwords are used for development
- Change passwords in production environments
- Consider enabling SSL/TLS for production
- Redis and ClickHouse should not be exposed publicly

## Data Persistence

All data is persisted in Docker volumes:
- `kafka_data`
- `redis_data`
- `clickhouse_data`
- `zookeeper_data`
- `zookeeper_logs`

To completely reset, run:
```bash
docker-compose down -v
```

## Integration
This infrastructure integrates with:
- `ingestion/iqfeed_client.py`: Data ingestion
- `processing/`: Real-time data processing
- `storage/`: Data persistence layer
- `realtime/ui/`: Monitoring dashboard