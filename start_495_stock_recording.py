#!/usr/bin/env python3
"""
Load 495 stocks from CSV and start recording with verification.
Records L1, L2, and tick data with lag tracking to ClickHouse.
"""

import os
import sys
import pandas as pd
import time
import signal
from datetime import datetime, timezone
from pathlib import Path
import clickhouse_connect
import json
from collections import defaultdict
from typing import List, Dict, Any

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion.iqfeed_client import IQFeedClient
from ingestion.kafka_producer import IQFeedKafkaProducer
from processing.redis_cache_manager import RedisCacheManager, CacheConfig

# Signal handler
running = True

def signal_handler(sig, frame):
    global running
    print("\n⏹️  Stopping recording...")
    running = False

signal.signal(signal.SIGINT, signal_handler)

def load_and_filter_stocks(csv_path: str) -> List[str]:
    """Load CSV and filter stocks by price range."""
    print(f"📂 Loading stocks from {csv_path}")
    
    # Load CSV
    df = pd.read_csv(csv_path)
    print(f"   Total stocks in CSV: {len(df)}")
    
    # Check column names
    print(f"   Columns: {df.columns.tolist()}")
    
    # Look for price column (handle different naming conventions)
    price_col = None
    for col in ['Last Sale', 'Last', 'Price', 'Close', 'Last Price']:
        if col in df.columns:
            price_col = col
            break
    
    if not price_col:
        print("❌ No price column found!")
        return []
    
    # Clean price data (remove $ and convert to float)
    df[price_col] = df[price_col].astype(str).str.replace('$', '').str.replace(',', '')
    df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
    
    # Filter by price range
    filtered = df[(df[price_col] > 1.0) & (df[price_col] < 20.0)]
    print(f"   Stocks between $1-$20: {len(filtered)}")
    
    # Sort by price range (volatility proxy)
    if 'Market Cap' in df.columns:
        filtered = filtered.sort_values('Market Cap', ascending=False)
    else:
        filtered = filtered.sort_values(price_col, ascending=False)
    
    # Take top 495
    top_495 = filtered.head(495)
    
    # Get symbols
    symbol_col = 'Symbol' if 'Symbol' in df.columns else df.columns[0]
    symbols = top_495[symbol_col].tolist()
    
    print(f"\n✅ Selected {len(symbols)} stocks for recording")
    print(f"   Price range: ${top_495[price_col].min():.2f} - ${top_495[price_col].max():.2f}")
    
    return symbols

def write_to_clickhouse(client, table: str, messages: List[Dict[str, Any]]):
    """Write messages to ClickHouse table."""
    if not messages:
        return
    
    # Convert messages to proper format
    rows = []
    for msg in messages:
        row = {
            'symbol': msg.get('symbol'),
            'timestamp': msg.get('timestamp'),
            'date': datetime.now().date()
        }
        
        # Add lag metrics
        row['reception_timestamp'] = msg.get('reception_timestamp', datetime.now(timezone.utc).isoformat())
        row['network_lag_ms'] = msg.get('network_lag_ms', 0)
        row['processing_lag_ms'] = msg.get('processing_lag_ms', 0) 
        row['total_lag_ms'] = msg.get('total_lag_ms', 0)
        
        # Table-specific fields
        if table == 'trades':
            row.update({
                'trade_price': msg.get('trade_price', 0),
                'trade_size': msg.get('trade_size', 0),
                'total_volume': msg.get('total_volume', 0),
                'trade_market_center': msg.get('trade_market_center', ''),
                'trade_conditions': msg.get('trade_conditions', ''),
                'trade_aggressor': msg.get('trade_aggressor', 0),
                'trade_exchange_id': msg.get('trade_exchange_id', ''),
                'tick_direction': msg.get('tick_direction', 0)
            })
        elif table == 'quotes':
            row.update({
                'bid_price': msg.get('bid_price', 0),
                'bid_size': msg.get('bid_size', 0),
                'ask_price': msg.get('ask_price', 0),
                'ask_size': msg.get('ask_size', 0),
                'bid_exchange': msg.get('bid_exchange', ''),
                'ask_exchange': msg.get('ask_exchange', ''),
                'quote_condition': msg.get('quote_condition', 0),
                'nbbo_indicator': msg.get('nbbo_indicator', 0),
                'tick_id': msg.get('tick_id', 0)
            })
        elif table == 'order_book_updates':
            row.update({
                'side': msg.get('side', 0),
                'price_level': msg.get('level', 0),
                'market_maker_id': msg.get('market_maker_id', ''),
                'price': msg.get('price', 0),
                'size': msg.get('size', 0),
                'operation': msg.get('operation', 0),
                'order_count': msg.get('order_count', 0),
                'level_update_time': msg.get('timestamp')
            })
        
        rows.append(row)
    
    # Insert to ClickHouse
    client.insert(table, rows)

def setup_clickhouse_tables():
    """Ensure ClickHouse tables exist with lag tracking columns."""
    client = clickhouse_connect.get_client(
        host='localhost', port=8123, database='l2_market_data',
        username='l2_user', password='l2_secure_pass'
    )
    
    try:
        # Add lag tracking columns if they don't exist
        alter_queries = [
            """
            ALTER TABLE trades 
            ADD COLUMN IF NOT EXISTS reception_timestamp DateTime64(3),
            ADD COLUMN IF NOT EXISTS network_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS processing_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS total_lag_ms Float32
            """,
            """
            ALTER TABLE quotes 
            ADD COLUMN IF NOT EXISTS reception_timestamp DateTime64(3),
            ADD COLUMN IF NOT EXISTS network_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS processing_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS total_lag_ms Float32
            """,
            """
            ALTER TABLE order_book_updates 
            ADD COLUMN IF NOT EXISTS reception_timestamp DateTime64(3),
            ADD COLUMN IF NOT EXISTS network_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS processing_lag_ms Float32,
            ADD COLUMN IF NOT EXISTS total_lag_ms Float32
            """
        ]
        
        for query in alter_queries:
            try:
                client.command(query)
            except Exception as e:
                if "already exists" not in str(e):
                    print(f"⚠️  ClickHouse alter warning: {e}")
        
        print("✅ ClickHouse tables ready with lag tracking")
        
    finally:
        client.close()

def create_data_verifier():
    """Create a verifier that checks data quality in real-time."""
    
    class DataVerifier:
        def __init__(self):
            self.stats = defaultdict(lambda: {
                'trades': 0, 'quotes': 0, 'l2': 0,
                'errors': 0, 'warnings': [],
                'last_trade_price': None,
                'last_quote': {'bid': None, 'ask': None},
                'max_lag_ms': 0,
                'avg_lag_ms': []
            })
            
        def verify_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
            """Verify message and add lag metrics."""
            symbol = message.get('symbol')
            msg_type = message.get('message_type')
            
            if not symbol or not msg_type:
                return message
            
            # Add reception timestamp if not present
            if 'reception_timestamp' not in message:
                message['reception_timestamp'] = datetime.now(timezone.utc).isoformat()
            
            # Calculate lag if timestamps present
            if 'timestamp' in message and 'reception_timestamp' in message:
                try:
                    # Parse timestamps
                    if isinstance(message['timestamp'], str):
                        # IQFeed format: YYYYMMDDHHMMSSMMM
                        ts_str = message['timestamp']
                        year = int(ts_str[:4])
                        month = int(ts_str[4:6])
                        day = int(ts_str[6:8])
                        hour = int(ts_str[8:10])
                        minute = int(ts_str[10:12])
                        second = int(ts_str[12:14])
                        millisecond = int(ts_str[14:17]) if len(ts_str) >= 17 else 0
                        
                        iqfeed_time = datetime(year, month, day, hour, minute, second, 
                                              millisecond * 1000, tzinfo=timezone.utc)
                    else:
                        iqfeed_time = message['timestamp']
                    
                    reception_time = datetime.fromisoformat(
                        message['reception_timestamp'].replace('Z', '+00:00')
                    )
                    
                    # Calculate lag
                    lag_ms = (reception_time - iqfeed_time).total_seconds() * 1000
                    message['network_lag_ms'] = round(lag_ms, 2)
                    
                    # Track stats
                    self.stats[symbol]['avg_lag_ms'].append(lag_ms)
                    if lag_ms > self.stats[symbol]['max_lag_ms']:
                        self.stats[symbol]['max_lag_ms'] = lag_ms
                    
                    # Warning if lag is too high
                    if lag_ms > 1000:  # 1 second
                        self.stats[symbol]['warnings'].append(
                            f"High lag: {lag_ms:.0f}ms at {datetime.now()}"
                        )
                except Exception as e:
                    pass
            
            # Type-specific verification
            if msg_type == 'trade':
                self.stats[symbol]['trades'] += 1
                
                # Check price sanity
                price = message.get('trade_price')
                if price:
                    last_price = self.stats[symbol]['last_trade_price']
                    if last_price and abs(price - last_price) / last_price > 0.10:
                        self.stats[symbol]['warnings'].append(
                            f"Large price move: ${last_price:.2f} -> ${price:.2f}"
                        )
                    self.stats[symbol]['last_trade_price'] = price
                    
            elif msg_type == 'quote':
                self.stats[symbol]['quotes'] += 1
                
                # Check spread sanity
                bid = message.get('bid_price')
                ask = message.get('ask_price')
                if bid and ask:
                    if bid >= ask:
                        self.stats[symbol]['warnings'].append(
                            f"Crossed quote: bid ${bid:.2f} >= ask ${ask:.2f}"
                        )
                    spread_pct = (ask - bid) / bid * 100 if bid > 0 else 0
                    if spread_pct > 5:  # 5% spread
                        self.stats[symbol]['warnings'].append(
                            f"Wide spread: {spread_pct:.1f}%"
                        )
                    self.stats[symbol]['last_quote'] = {'bid': bid, 'ask': ask}
                    
            elif msg_type == 'l2':
                self.stats[symbol]['l2'] += 1
            
            return message
        
        def get_summary(self, top_n: int = 10) -> str:
            """Get verification summary."""
            active_symbols = [(s, sum([v['trades'], v['quotes'], v['l2']])) 
                             for s, v in self.stats.items()]
            active_symbols.sort(key=lambda x: x[1], reverse=True)
            
            summary = []
            summary.append("\n📊 DATA VERIFICATION SUMMARY")
            summary.append("=" * 60)
            
            # Overall stats
            total_messages = sum(v['trades'] + v['quotes'] + v['l2'] 
                               for v in self.stats.values())
            total_warnings = sum(len(v['warnings']) for v in self.stats.values())
            
            summary.append(f"Total messages: {total_messages:,}")
            summary.append(f"Active symbols: {len(self.stats)}")
            summary.append(f"Total warnings: {total_warnings}")
            
            # Top symbols
            summary.append(f"\nTop {top_n} most active symbols:")
            for symbol, count in active_symbols[:top_n]:
                stats = self.stats[symbol]
                avg_lag = (sum(stats['avg_lag_ms']) / len(stats['avg_lag_ms']) 
                          if stats['avg_lag_ms'] else 0)
                summary.append(
                    f"  {symbol}: {count:,} msgs "
                    f"(T:{stats['trades']}, Q:{stats['quotes']}, L2:{stats['l2']}) "
                    f"Lag:{avg_lag:.0f}ms"
                )
                
                # Show warnings for this symbol
                if stats['warnings']:
                    recent_warnings = stats['warnings'][-3:]  # Last 3
                    for warning in recent_warnings:
                        summary.append(f"    ⚠️  {warning}")
            
            # Lag statistics
            all_lags = []
            for stats in self.stats.values():
                all_lags.extend(stats['avg_lag_ms'])
            
            if all_lags:
                summary.append(f"\nLag Statistics:")
                summary.append(f"  Average: {sum(all_lags)/len(all_lags):.0f}ms")
                summary.append(f"  Min: {min(all_lags):.0f}ms")
                summary.append(f"  Max: {max(all_lags):.0f}ms")
            
            return "\n".join(summary)
    
    return DataVerifier()

def main():
    """Main recording function."""
    print("🚀 Starting 495 Stock Recording with Verification")
    print("=" * 80)
    
    # Load stocks from CSV
    csv_path = "data/universe/nasdaq_screener_1753296263842.csv"
    symbols = load_and_filter_stocks(csv_path)
    
    if len(symbols) < 495:
        print(f"⚠️  Warning: Only found {len(symbols)} stocks (wanted 495)")
        response = input("Continue? (y/n): ")
        if response.lower() != 'y':
            return
    
    # Setup ClickHouse tables
    setup_clickhouse_tables()
    
    # Initialize components
    print("\n🔧 Initializing components...")
    
    # Data verifier
    verifier = create_data_verifier()
    
    # Redis cache
    try:
        redis_config = CacheConfig()
        redis_manager = RedisCacheManager(config=redis_config)
        redis_manager.start()
        print("✅ Redis cache manager started (port 6380)")
    except Exception as e:
        print(f"⚠️  Redis not available: {e}")
        redis_manager = None
    
    # ClickHouse client
    try:
        ch_client = clickhouse_connect.get_client(
            host='localhost', port=8123, database='l2_market_data',
            username='l2_user', password='l2_secure_pass'
        )
        print("✅ ClickHouse client initialized")
    except Exception as e:
        print(f"❌ ClickHouse connection failed: {e}")
        return
    
    # IQFeed client
    client = IQFeedClient()
    
    # Kafka producer
    kafka_producer = None
    
    # Initialize buffer for ClickHouse writes
    ch_buffer = defaultdict(list)
    
    try:
        # Connect to IQFeed
        print("\n🔌 Connecting to IQFeed...")
        result = client.connect()
        if not result.success:
            print(f"❌ IQFeed connection failed: {result.error_message}")
            print("\n💡 Starting mock IQFeed producer instead...")
            
            # Start mock producer if real IQFeed not available
            os.system("python simple_synthetic_test.py --symbols " + 
                     ",".join(symbols[:50]) + " --rate 100 &")
            time.sleep(2)
            
            # Wait a bit more for mock producer to start
            time.sleep(3)
            
            # Try connecting again
            result = client.connect()
            if not result.success:
                print("❌ Still can't connect. Please start IQFeed or mock producer.")
                return
        
        print(f"✅ Connected! Session: {result.session_id}")
        
        # Subscribe to symbols in batches
        print(f"\n📡 Subscribing to {len(symbols)} symbols...")
        batch_size = 50
        successful_subs = []
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            print(f"   Batch {i//batch_size + 1}/{(len(symbols)-1)//batch_size + 1}...")
            
            for symbol in batch:
                # Subscribe to all data types
                l2_ok = client.subscribe_l2(symbol).success
                trades_ok = client.subscribe_trades(symbol).success
                quotes_ok = client.subscribe_quotes(symbol).success
                
                if l2_ok and trades_ok and quotes_ok:
                    successful_subs.append(symbol)
            
            # Rate limit subscriptions
            time.sleep(0.5)
        
        print(f"✅ Subscribed to {len(successful_subs)} symbols")
        
        # Initialize Kafka
        try:
            print("\n🔗 Starting Kafka producer...")
            kafka_producer = IQFeedKafkaProducer()
            if kafka_producer.start():
                print("✅ Kafka producer started")
            else:
                kafka_producer = None
                print("⚠️  Kafka producer failed to start")
        except Exception as e:
            print(f"⚠️  Kafka not available: {e}")
        
        # Start recording
        print("\n📼 Recording started! Press Ctrl+C to stop")
        print("-" * 80)
        
        # Statistics
        last_report_time = time.time()
        last_ch_write_time = time.time()
        ch_buffer = defaultdict(list)
        
        # Main recording loop
        while running:
            # Get next message
            message = client.get_next_message(timeout=0.01)
            
            if message:
                # Verify and enrich message
                message = verifier.verify_message(message)
                
                symbol = message.get('symbol')
                msg_type = message.get('message_type')
                
                if symbol and msg_type:
                    # Cache in Redis
                    if redis_manager:
                        try:
                            if msg_type == 'l2':
                                redis_manager.cache_l2_update(symbol, message)
                            elif msg_type == 'trade':
                                redis_manager.cache_trade(symbol, message)
                            elif msg_type == 'quote':
                                redis_manager.cache_quote(symbol, message)
                        except Exception:
                            pass
                    
                    # Buffer for ClickHouse
                    ch_buffer[msg_type].append(message)
                    
                    # Send to Kafka
                    if kafka_producer:
                        try:
                            kafka_producer.process_message(message)
                        except Exception:
                            pass
            
            # Write to ClickHouse in batches (every 5 seconds)
            if time.time() - last_ch_write_time > 5:
                for msg_type, messages in ch_buffer.items():
                    if messages:
                        try:
                            if msg_type == 'trade':
                                write_to_clickhouse(ch_client, 'trades', messages)
                            elif msg_type == 'quote':
                                write_to_clickhouse(ch_client, 'quotes', messages)
                            elif msg_type == 'l2':
                                write_to_clickhouse(ch_client, 'order_book_updates', messages)
                            
                            print(f"   ✓ Wrote {len(messages)} {msg_type} messages to ClickHouse")
                        except Exception as e:
                            print(f"   ✗ ClickHouse write error: {e}")
                
                ch_buffer.clear()
                last_ch_write_time = time.time()
            
            # Print verification summary every 30 seconds
            if time.time() - last_report_time > 30:
                print(verifier.get_summary())
                
                # Check Kafka stats
                if kafka_producer:
                    stats = kafka_producer.get_statistics()
                    print(f"\nKafka Stats: {stats.messages_sent} sent, "
                          f"{stats.messages_failed} failed, "
                          f"Success rate: {stats.success_rate:.1%}")
                
                # Check Redis stats
                if redis_manager:
                    cache_stats = redis_manager.get_cache_stats()
                    print(f"Redis Cache: {cache_stats.get('total_keys', 0)} keys")
                
                print("-" * 80)
                last_report_time = time.time()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        
        # Write any remaining buffered data
        for msg_type, messages in ch_buffer.items():
            if messages:
                try:
                    if msg_type == 'trade':
                        write_to_clickhouse(ch_client, 'trades', messages)
                    elif msg_type == 'quote':
                        write_to_clickhouse(ch_client, 'quotes', messages)
                    elif msg_type == 'l2':
                        write_to_clickhouse(ch_client, 'order_book_updates', messages)
                except Exception:
                    pass
        
        # Stop components
        if client.is_connected():
            client.disconnect()
            print("✅ Disconnected from IQFeed")
        
        if kafka_producer:
            kafka_producer.stop()
            print("✅ Stopped Kafka producer")
        
        if redis_manager:
            redis_manager.stop()
            print("✅ Stopped Redis cache manager")
        
        # Final summary
        print("\n" + verifier.get_summary())
        
        # Verify data in ClickHouse
        print("\n🔍 Verifying ClickHouse data...")
        try:
            ch_client = clickhouse_connect.get_client(
                host='localhost', port=8123, database='l2_market_data',
                username='l2_user', password='l2_secure_pass'
            )
            
            # Check counts
            for table in ['trades', 'quotes', 'order_book_updates']:
                result = ch_client.query(f"""
                    SELECT 
                        COUNT(*) as count,
                        COUNT(DISTINCT symbol) as symbols,
                        AVG(network_lag_ms) as avg_lag,
                        MAX(network_lag_ms) as max_lag
                    FROM {table}
                    WHERE timestamp > now() - INTERVAL 1 HOUR
                """)
                
                if result.result_rows:
                    count, symbols, avg_lag, max_lag = result.result_rows[0]
                    print(f"   {table}: {count} records, {symbols} symbols, "
                          f"avg lag: {avg_lag:.0f}ms, max lag: {max_lag:.0f}ms")
            
            ch_client.close()
            
        except Exception as e:
            print(f"   ClickHouse verification error: {e}")

if __name__ == '__main__':
    main()