#!/usr/bin/env python3
"""Check actual ClickHouse data quality."""

import clickhouse_connect

client = clickhouse_connect.get_client(
    host='localhost', port=8123, database='l2_market_data',
    username='l2_user', password='l2_secure_pass'
)

print("CLICKHOUSE DATA QUALITY CHECK")
print("="*60)

# Check price ranges
result = client.query("""
    SELECT 
        symbol,
        MIN(trade_price) as min_price,
        MAX(trade_price) as max_price,
        AVG(trade_price) as avg_price,
        COUNT(*) as trade_count
    FROM trades 
    WHERE date = '2025-07-29'
    GROUP BY symbol
    ORDER BY symbol
""")

print("\nPrice Ranges by Symbol:")
for row in result.result_rows:
    symbol, min_p, max_p, avg_p, count = row
    range_pct = (float(max_p) - float(min_p)) / float(avg_p) * 100
    print(f'{symbol}: ${float(min_p):.2f} - ${float(max_p):.2f} '
          f'(range: {range_pct:.1f}%, trades: {count})')

# Check for data anomalies
print("\nChecking for anomalies...")

# Check GOOGL specifically
result = client.query("""
    SELECT 
        MIN(trade_price) as min_price,
        MAX(trade_price) as max_price,
        percentile(0.01)(trade_price) as p1,
        percentile(0.99)(trade_price) as p99
    FROM trades 
    WHERE symbol = 'GOOGL' AND date = '2025-07-29'
""")

if result.result_rows:
    min_p, max_p, p1, p99 = result.result_rows[0]
    print(f"\nGOOGL detailed:")
    print(f"  Absolute min/max: ${float(min_p):.2f} - ${float(max_p):.2f}")
    print(f"  1st/99th percentile: ${float(p1):.2f} - ${float(p99):.2f}")
    
    # The extreme values might be outliers
    range_99pct = (float(p99) - float(p1)) / ((float(p99) + float(p1))/2) * 100
    print(f"  99% range: {range_99pct:.1f}%")

client.close()