# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Advanced microstructure analysis system for detecting stealthy pre-pump accumulation patterns using IQFeed real-time Level 2 data, GPU acceleration, and event-driven backtesting.

### Key Architecture Components

1. **Data Pipeline**: IQFeed → Kafka → Microstructure Analysis → Redis/ClickHouse
2. **GPU Processing**: Numba CUDA kernels for parallel L2 order book reconstruction across 2000 stocks
3. **Signal Detection**: Five unique accumulation patterns based on order flow, spread dynamics, and dark pool inference
4. **Backtesting**: Event-driven engine with realistic slippage/commission modeling

## Critical Constraints

- **IQFeed Trial**: Limited to 2-3 days of historical data from current date
- **GPU Hardware**: NVIDIA K1 (GK107, Kepler) - requires CUDA 10.x or 9.x, incompatible with modern RAPIDS
- **Stock Universe**: 2000 symbols defined in `config/stock_universe.json`
- **Python Stack**: Numba (@cuda.jit), older PyTorch/TensorFlow versions for CUDA 10.x compatibility

## Development Commands

### Infrastructure Setup
```bash
# Start Docker services
cd infrastructure
docker-compose up -d

# Create Kafka topics
./scripts/create-topics.sh

# Check health of all services
./scripts/health-check.sh

# Return to project root
cd ..
```

### Testing
```bash
# Run all tests
pytest tests/ -v

# Run specific test categories
pytest tests/microstructure_analysis/ -v
pytest tests/backtesting/ -v
pytest tests/ingestion/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run GPU-specific tests (requires CUDA environment)
pytest tests/microstructure_analysis/gpu/ -v -m gpu

# Run comprehensive data sanity checks
pytest tests/data_sanity/ -v

# Run Django UI tests with Playwright
pytest tests/ui/ -v --browser=chromium
pytest tests/ui/ -v --browser=firefox --headed  # For debugging
```

### UI Testing (Playwright)
```bash
# Run comprehensive Django UI tests
pytest tests/ui/test_django_playwright_comprehensive.py -v

# Run specific UI test suites
pytest tests/ui/ -v -k "dashboard"     # Dashboard functionality
pytest tests/ui/ -v -k "api"          # API integration
pytest tests/ui/ -v -k "performance"  # Performance testing

# Run with different browsers
pytest tests/ui/ -v --browser=chromium
pytest tests/ui/ -v --browser=firefox
pytest tests/ui/ -v --browser=webkit

# Debug with headed browser (visual)
pytest tests/ui/ -v --browser=chromium --headed --slowmo=1000

# Run individual test categories
pytest tests/ui/test_django_playwright_comprehensive.py::TestHedgeFundDashboardUI -v
pytest tests/ui/test_api_integration_playwright.py::TestHedgeFundAPIIntegration -v
```

### Data Ingestion
```bash
# Download historical data (2-3 days from IQFeed)
python ingestion/download_historical.py --days=3 --symbols=config/stock_universe.json

# Start real-time data stream
python ingestion/iqfeed_client.py --mode=realtime --kafka=true

# Validate data pipeline end-to-end
python validate_data_pipeline.py
```

### Backtesting
```bash
# Run backtest with default strategy
python run_backtest.py --strategy=dilution_play --start=2025-07-21 --end=2025-07-23

# Run with specific signal thresholds
python run_backtest.py --config=config/strategy_params.yaml

# Generate performance report
python analysis/metrics_dashboard.py --results=data/backtest_results/
```

## Core Signal Detection Logic

### 1. Sustained Bid-Side Absorption
- Monitor trades hitting bid without price dropping
- Track bid depth replenishment (iceberg behavior)
- Validate spread stability/narrowing

### 2. Controlled Price Creep
- Detect slow mid-price increases (< 0.05%/sec)
- Low volume-to-price-change ratio
- Small aggressive orders lifting offers

### 3. Dark Pool Inference
- Compare consolidated tape volume vs lit exchange volume
- Detect price movement without corresponding lit market activity

### 4. Liquidity Sinkhole
- Persistent bid depth across multiple levels
- High trade volume vs low depth depletion
- Price near recent lows

### 5. Micro-Volatility Contraction
- Unusually tight spreads vs historical average
- Decreasing mid-price standard deviation
- Combined with upward price bias

## Test-Driven Development Approach

1. **Unit Tests First**: Write tests for each microstructure feature calculation
2. **Integration Tests**: Validate Kafka→Processing→Storage pipeline
3. **Backtest Validation**: Compare results against known market scenarios
4. **GPU Tests**: Separate test suite for CUDA kernels with CPU fallback verification
5. **Data Sanity Tests**: Comprehensive validation of data integrity and consistency
6. **UI Tests**: End-to-end Django UI testing with Playwright browser automation

## Comprehensive Test Categories

### Core System Tests
- **Microstructure Analysis**: L2 order book processing, signal detection algorithms
- **Backtesting Engine**: Event-driven backtesting with realistic market conditions
- **Data Ingestion**: IQFeed client, Kafka producers, data pipeline validation
- **Storage Systems**: Redis caching, ClickHouse time-series data validation

### Data Quality & Integrity Tests
- **Historical Data Quality**: File structure, tick data integrity, L1 quote validation
- **Real-time Data Consistency**: Redis freshness, Kafka message consistency, pipeline latency
- **Message Integrity**: Kafka topic configuration, message ordering, durability testing
- **Database Consistency**: Cross-database validation between Redis and ClickHouse
- **System Health Monitoring**: Resource validation, service connectivity, filesystem health

### UI & User Experience Tests
- **Dashboard Functionality**: System metrics display, trading API status, alert management
- **API Integration**: Health endpoints, status validation, error handling
- **Performance Testing**: Page load times, concurrent user handling, resource usage
- **Responsive Design**: Cross-browser compatibility, viewport adaptation
- **Real-time Updates**: WebSocket connections, auto-refresh mechanisms, AJAX validation

## Security & Compliance (per RULES.md)

- IQFeed credentials in `.env` - NEVER commit
- All inputs validated before processing
- No hardcoded credentials in code
- Logging excludes sensitive data values
- Error messages include remediation paths

## GPU Development Notes

### Environment Setup
```bash
# Check CUDA version
nvidia-smi
nvcc --version

# Install compatible Numba for CUDA 10.x
pip install numba==0.53.1 cudatoolkit=10.2

# Test GPU availability
python -c "from numba import cuda; print(cuda.gpus)"
```

### Numba CUDA Pattern
```python
# CPU/GPU hybrid approach
@numba.jit(nopython=True)  # CPU version
def calculate_ofi_cpu(trades, book_state):
    # Implementation

@cuda.jit  # GPU version
def calculate_ofi_gpu(trades, book_state, output):
    # CUDA kernel implementation
```

## Common Pitfalls to Avoid

1. **IQFeed Connection**: Ensure IQConnect.exe is running before Python client
2. **Timestamp Ordering**: All data must be chronologically sorted
3. **GPU Memory**: K1 has limited memory - batch processing required
4. **Kafka Partitioning**: Use symbol as key for ordered processing per stock
5. **ClickHouse Schema**: Define proper sorting keys for time-series queries

## Performance Optimization Targets

- L2 book updates: < 10μs per update across 2000 symbols
- Feature calculation: < 100μs for all 5 signals per symbol
- Kafka latency: < 5ms end-to-end
- Backtest speed: > 100x real-time for 2000 symbols

## Directory Structure Highlights

- `infrastructure/`: All Docker services (Kafka, Redis, ClickHouse) and scripts
- `ingestion/`: IQFeed client and Kafka producers
- `microstructure_analysis/`: Core L2 processing and feature generation
- `microstructure_analysis/gpu_accelerators/`: CUDA kernels
- `backtesting/`: Event-driven engine
- `strategies/`: Signal interpretation and trading logic
- `data/raw_iqfeed/`: Historical data in IQFeed format
- `realtime/ui/`: Django web interface for production monitoring
- `tests/`: Comprehensive test suite following TDD
  - `tests/microstructure_analysis/`: Core algorithm tests
  - `tests/backtesting/`: Backtesting engine validation
  - `tests/ingestion/`: Data ingestion pipeline tests
  - `tests/data_sanity/`: Data quality and integrity validation
  - `tests/ui/`: Playwright browser automation tests

## Debugging & Monitoring

```bash
# Monitor Kafka lag
docker exec -it kafka kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups

# Check ClickHouse queries
docker exec -it clickhouse clickhouse-client -q "SHOW PROCESSLIST"

# GPU utilization
nvidia-smi dmon -s u

# Application logs
tail -f logs/microstructure_analysis.log
```