# Minimal ClickHouse Data Viewer

Ultra-simple interface for viewing stored market data from ClickHouse database. Built with ultrathinking philosophy to avoid over-engineering.

## What It Does (Keep It Simple)

✅ **Connects to ClickHouse successfully**  
✅ **Shows stored market data in table**  
✅ **Has basic symbol/date filters**  
✅ **Displays data without crashing**  
✅ **Can export results to CSV**  

## What It Does NOT Do (Anti-Over-Engineering)

❌ Complex SQL query builder interface  
❌ Advanced data visualization/charts  
❌ Real-time analytics dashboards  
❌ Performance optimization for big data  
❌ Complex data transformation features  
❌ Multi-database join capabilities  

## Quick Start

1. **Start ClickHouse:**
   ```bash
   cd infrastructure
   docker-compose up -d clickhouse
   ```

2. **Test Connection:**
   ```bash
   python test_clickhouse_connection.py
   ```

3. **Add Sample Data (if needed):**
   ```bash
   python populate_sample_data.py
   ```

4. **Demo the Data Viewer:**
   ```bash
   python demo_data_viewer.py
   ```

5. **Run Streamlit UI:**
   ```bash
   streamlit run minimal_clickhouse_viewer.py
   ```

## Available Tables

- `l2_updates`: Level 2 order book updates
- `trades`: Trade executions  
- `quotes`: NBBO quotes
- `features`: Calculated market features with signals
- `backtest_trades`: Backtesting results

## Basic Filters

- **Symbol**: Filter by specific stock symbol (e.g., AAPL)
- **Date Range**: Start and end dates for data
- **Record Limit**: Maximum rows to display (100-5000)

## Files

- `minimal_clickhouse_viewer.py` - Main Streamlit interface
- `test_clickhouse_connection.py` - Test ClickHouse connection
- `populate_sample_data.py` - Add sample data for testing
- `demo_data_viewer.py` - Command-line demo

## Connection Configuration

```python
config = {
    'host': 'localhost',
    'port': 8123,
    'database': 'l2_market_data', 
    'username': 'l2_user',
    'password': 'l2_secure_pass'
}
```

## Example Usage

```python
from minimal_clickhouse_viewer import MinimalClickHouseViewer

viewer = MinimalClickHouseViewer()
viewer.connect()

# Get recent trades for AAPL
df = viewer.get_data(
    table='trades',
    symbol='AAPL',
    limit=100
)

# Export to CSV
csv_data = df.to_csv(index=False)
```

## Success Criteria Met

✅ Connects to ClickHouse database  ✅ Displays historical market data in table format  ✅ Basic filtering by symbol and date range  ✅ Simple pagination with record limits  ✅ CSV export functionality  

This viewer focuses on the core requirement: **view stored market data from database**. Nothing more, nothing less.