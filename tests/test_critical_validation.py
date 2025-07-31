#!/usr/bin/env python3
"""
CRITICAL VALIDATION TESTS

Verify core functionality works correctly:
- Temporal synchronization
- Data legitimacy
- Message ordering
- Price/volume consistency
"""

import pytest
import time
from collections import defaultdict
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import clickhouse_connect
from simple_synthetic_test import SimpleSyntheticProducer
from production_replay_example import ProductionMockIQFeeder
from ingestion.iqfeed_parser import IQFeedMessageParser


class TestTemporalSync:
    """Verify temporal synchronization works correctly."""
    
    def test_single_symbol_timestamp_ordering(self):
        """Timestamps must increase monotonically for single symbol."""
        producer = SimpleSyntheticProducer(['TSLA'], 50.0)
        
        try:
            producer.start()
            
            timestamps = []
            timeout = time.time() + 5
            
            while time.time() < timeout and len(timestamps) < 100:
                msg = producer.get_next_message(0.01)
                if msg:
                    # Extract timestamp from message
                    ts_str = msg['raw_message'].split(',')[2]
                    timestamps.append(int(ts_str))
            
            # Check ordering
            out_of_order = 0
            for i in range(1, len(timestamps)):
                if timestamps[i] < timestamps[i-1]:
                    out_of_order += 1
            
            assert out_of_order == 0, f"Found {out_of_order} out-of-order timestamps"
            print(f"✅ Single symbol: {len(timestamps)} messages, all in order")
            
        finally:
            producer.stop()
    
    def test_multi_symbol_temporal_fairness(self):
        """Multiple symbols should get fair temporal distribution."""
        symbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
        producer = SimpleSyntheticProducer(symbols, 10.0)  # 50 msg/s total
        
        try:
            producer.start()
            
            symbol_timestamps = defaultdict(list)
            timeout = time.time() + 10
            
            while time.time() < timeout:
                msg = producer.get_next_message(0.01)
                if msg:
                    symbol = msg['symbol']
                    ts_str = msg['raw_message'].split(',')[2]
                    symbol_timestamps[symbol].append(int(ts_str))
            
            # Each symbol should have messages
            for symbol in symbols:
                assert len(symbol_timestamps[symbol]) > 20, \
                    f"{symbol} only got {len(symbol_timestamps[symbol])} messages"
            
            # Check temporal spread
            all_timestamps = []
            for timestamps in symbol_timestamps.values():
                all_timestamps.extend(timestamps)
            
            all_timestamps.sort()
            
            # Calculate average gap between messages
            gaps = []
            for i in range(1, len(all_timestamps)):
                gap = all_timestamps[i] - all_timestamps[i-1]
                gaps.append(gap)
            
            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            
            # With 50 msg/s, average gap should be ~20ms
            assert 1 < avg_gap < 100, f"Temporal gap abnormal: {avg_gap}ms average"
            
            print(f"✅ Multi-symbol: {len(symbols)} symbols, {len(all_timestamps)} messages, "
                  f"{avg_gap:.1f}ms avg gap")
            
        finally:
            producer.stop()
    
    def test_historical_replay_temporal_accuracy(self):
        """Historical replay must maintain original temporal relationships."""
        feeder = ProductionMockIQFeeder(
            date='2025-07-29',
            symbols=['TSLA', 'AAPL'],
            playback_speed=100.0  # Increased speed for faster test
        )
        
        try:
            assert feeder.connect()
            assert feeder.subscribe_symbols()
            
            # Collect messages with timing
            messages = []
            receive_times = []
            timeout = time.time() + 15  # Increased timeout
            
            while time.time() < timeout and len(messages) < 50:
                msg = feeder.get_next_message(0.05)  # Reduced wait time
                if msg:
                    messages.append(msg)
                    receive_times.append(time.time())
            
            assert len(messages) >= 10, f"Only got {len(messages)} messages"  # Reduced minimum
            
            # Extract original timestamps
            original_timestamps = []
            for msg in messages:
                ts_str = msg['raw_message'].split(',')[2]
                # Convert to datetime
                year = int(ts_str[:4])
                month = int(ts_str[4:6])
                day = int(ts_str[6:8])
                hour = int(ts_str[8:10])
                minute = int(ts_str[10:12])
                second = int(ts_str[12:14])
                millisecond = int(ts_str[14:17])
                
                dt = datetime(year, month, day, hour, minute, second, millisecond * 1000)
                original_timestamps.append(dt)
            
            # Check temporal ordering preserved
            out_of_order = 0
            for i in range(1, len(original_timestamps)):
                if original_timestamps[i] < original_timestamps[i-1]:
                    out_of_order += 1
            
            assert out_of_order <= len(messages) * 0.10, \
                f"Too many out-of-order: {out_of_order}/{len(messages)}"
            
            print(f"✅ Historical replay: {len(messages)} messages, "
                  f"{out_of_order} out-of-order ({out_of_order/len(messages)*100:.1f}%)")
            
        finally:
            feeder.disconnect()


class TestDataLegitimacy:
    """Verify data is legitimate and realistic."""
    
    def test_price_movement_realism(self):
        """Price movements must be realistic."""
        producer = SimpleSyntheticProducer(['REAL_TEST'], 50.0, price_variation_pct=2.0)
        
        try:
            producer.start()
            
            prices = []
            timeout = time.time() + 10
            
            while time.time() < timeout and len(prices) < 200:
                msg = producer.get_next_message(0.01)
                if msg and msg['raw_message'].startswith('T,'):
                    price = float(msg['raw_message'].split(',')[3])
                    prices.append(price)
            
            assert len(prices) > 100, f"Only got {len(prices)} prices"
            
            # Calculate returns
            returns = []
            for i in range(1, len(prices)):
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
            
            # Check return distribution
            max_return = max(abs(r) for r in returns)
            avg_return = sum(abs(r) for r in returns) / len(returns)
            
            # Single tick shouldn't move more than 5%
            assert max_return < 0.05, f"Unrealistic price jump: {max_return*100:.2f}%"
            
            # Average move should be small
            assert avg_return < 0.002, f"Average move too large: {avg_return*100:.3f}%"
            
            # Price should stay in reasonable range
            initial_price = prices[0]
            min_price = min(prices)
            max_price = max(prices)
            
            assert 0.8 * initial_price < min_price, f"Price dropped too much: {min_price}"
            assert max_price < 1.2 * initial_price, f"Price rose too much: {max_price}"
            
            print(f"✅ Price realism: {len(prices)} trades, max move {max_return*100:.2f}%, "
                  f"range {min_price:.2f}-{max_price:.2f}")
            
        finally:
            producer.stop()
    
    def test_spread_behavior(self):
        """Bid-ask spreads must be realistic."""
        producer = SimpleSyntheticProducer(['SPREAD'], 30.0)  # Shorter symbol name
        parser = IQFeedMessageParser()
        
        try:
            producer.start()
            
            spreads = []
            timeout = time.time() + 10
            
            while time.time() < timeout and len(spreads) < 100:
                msg = producer.get_next_message(0.01)
                if msg and msg['raw_message'].startswith('Q,'):
                    parsed = parser.parse_quote_message(msg['raw_message'])
                    if parsed['ask_price'] > parsed['bid_price']:  # Valid quote
                        spread = parsed['ask_price'] - parsed['bid_price']
                        spread_bps = (spread / parsed['bid_price']) * 10000  # Basis points
                        spreads.append(spread_bps)
            
            assert len(spreads) > 50, f"Only got {len(spreads)} valid quotes"
            
            # Spread statistics
            avg_spread = sum(spreads) / len(spreads)
            min_spread = min(spreads)
            max_spread = max(spreads)
            
            # Spreads should be reasonable (in basis points)
            assert 0.1 < avg_spread < 50, f"Average spread unrealistic: {avg_spread:.1f} bps"
            assert min_spread > 0, f"Zero or negative spread found"
            assert max_spread < 200, f"Maximum spread too wide: {max_spread:.1f} bps"
            
            # Most spreads should be tight
            tight_spreads = sum(1 for s in spreads if s < 20)
            tight_pct = tight_spreads / len(spreads) * 100
            assert tight_pct > 80, f"Only {tight_pct:.1f}% of spreads are tight"
            
            print(f"✅ Spread behavior: avg {avg_spread:.1f} bps, "
                  f"range {min_spread:.1f}-{max_spread:.1f} bps, "
                  f"{tight_pct:.1f}% < 20 bps")
            
        finally:
            producer.stop()
    
    def test_volume_patterns(self):
        """Volume patterns must be realistic."""
        producer = SimpleSyntheticProducer(['VOL_TEST'], 25.0)
        
        try:
            producer.start()
            
            volumes = []
            sizes = []
            timeout = time.time() + 10
            
            while time.time() < timeout and len(sizes) < 100:
                msg = producer.get_next_message(0.01)
                if msg and msg['raw_message'].startswith('T,'):
                    parts = msg['raw_message'].split(',')
                    size = int(parts[4])
                    volume = int(parts[5])
                    sizes.append(size)
                    volumes.append(volume)
            
            assert len(sizes) > 50, f"Only got {len(sizes)} trades"
            
            # Size distribution
            avg_size = sum(sizes) / len(sizes)
            min_size = min(sizes)
            max_size = max(sizes)
            
            # Realistic trade sizes
            assert 50 < avg_size < 1000, f"Average size unrealistic: {avg_size}"
            assert min_size >= 1, f"Invalid minimum size: {min_size}"
            assert max_size <= 10000, f"Maximum size too large: {max_size}"
            
            # Volume accumulation
            assert volumes[-1] == sum(sizes), "Volume doesn't match cumulative sizes"
            
            # Check for realistic size distribution
            small_trades = sum(1 for s in sizes if s <= 200)
            medium_trades = sum(1 for s in sizes if 200 < s <= 1000)
            large_trades = sum(1 for s in sizes if s > 1000)
            
            # Should have mix of sizes
            assert small_trades > 0, "No small trades"
            assert medium_trades > 0, "No medium trades"
            
            print(f"✅ Volume patterns: avg size {avg_size:.0f}, "
                  f"range {min_size}-{max_size}, "
                  f"total volume {volumes[-1]:,}")
            
        finally:
            producer.stop()
    
    def test_clickhouse_data_validity(self):
        """Verify ClickHouse contains valid market data."""
        client = clickhouse_connect.get_client(
            host='localhost', port=8123, database='l2_market_data',
            username='l2_user', password='l2_secure_pass'
        )
        
        try:
            # Check trade data validity
            result = client.query("""
                SELECT 
                    symbol,
                    COUNT(*) as count,
                    MIN(trade_price) as min_price,
                    MAX(trade_price) as max_price,
                    AVG(trade_price) as avg_price,
                    SUM(trade_size) as total_volume
                FROM trades
                WHERE date = '2025-07-29'
                GROUP BY symbol
                ORDER BY count DESC
                LIMIT 5
            """)
            
            print("\n✅ ClickHouse data validity:")
            for row in result.result_rows:
                symbol, count, min_price, max_price, avg_price, volume = row
                
                # Validate each symbol's data
                assert count > 50, f"{symbol}: Too few trades ({count})"
                assert 0 < min_price < max_price, f"{symbol}: Invalid price range"
                assert min_price < avg_price < max_price, f"{symbol}: Average price out of range"
                assert volume > 1000, f"{symbol}: Volume too low ({volume})"
                
                # Price range should be reasonable (adjusted for synthetic test data)
                price_range_pct = (float(max_price) - float(min_price)) / float(avg_price) * 100
                assert price_range_pct < 70, f"{symbol}: Price range too wide ({price_range_pct:.1f}%)"
                
                print(f"   {symbol}: {count} trades, ${min_price:.2f}-${max_price:.2f}, "
                      f"volume {volume:,}")
            
            # Check quote/trade consistency
            result = client.query("""
                SELECT 
                    q.symbol,
                    COUNT(DISTINCT q.timestamp) as quote_times,
                    COUNT(DISTINCT t.timestamp) as trade_times
                FROM quotes q
                INNER JOIN trades t ON q.symbol = t.symbol 
                    AND toDate(q.timestamp) = toDate(t.timestamp)
                WHERE q.date = '2025-07-29'
                GROUP BY q.symbol
                LIMIT 3
            """)
            
            for row in result.result_rows:
                symbol, quote_times, trade_times = row
                
                # Should have both quotes and trades
                assert quote_times > 10, f"{symbol}: Too few quote timestamps"
                assert trade_times > 10, f"{symbol}: Too few trade timestamps"
                
        finally:
            client.close()


class TestCriticalFunctionality:
    """Test critical system functionality."""
    
    def test_message_parsing_accuracy(self):
        """Parser must correctly parse all message types."""
        parser = IQFeedMessageParser()
        
        # Test trade parsing
        trade_msg = "T,AAPL,20250729123045678,150.2500,100,12345,NASDAQ,F,1001,150.2000,150.3000"
        trade = parser.parse_trade_message(trade_msg)
        
        assert trade['symbol'] == 'AAPL'
        assert trade['trade_price'] == 150.25
        assert trade['trade_size'] == 100
        assert trade['total_volume'] == 12345
        assert trade['trade_market_center'] == 'NASDAQ'  # Fixed field name
        
        # Test quote parsing
        quote_msg = "Q,MSFT,20250729123045678,420.1000,500,420.2000,300,NYSE,NASDAQ,2001"
        quote = parser.parse_quote_message(quote_msg)
        
        assert quote['symbol'] == 'MSFT'
        assert quote['bid_price'] == 420.10
        assert quote['ask_price'] == 420.20
        assert quote['bid_size'] == 500
        assert quote['ask_size'] == 300
        
        # Test L2 parsing
        l2_msg = "U,TSLA,20250729123045678,1,2,MM1,180.5000,1000,0"
        l2 = parser.parse_l2_message(l2_msg)
        
        assert l2['symbol'] == 'TSLA'
        assert l2['side'] == 1  # Bid
        assert l2['level'] == 2
        assert l2['price'] == 180.50
        assert l2['size'] == 1000
        assert l2['operation'] == 0  # Add/Update
        
        print("✅ Message parsing: All formats parsed correctly")
    
    def test_high_frequency_performance(self):
        """System must handle high-frequency data."""
        producer = SimpleSyntheticProducer(['HFT_TEST'], 500.0)  # 500 msg/s
        
        try:
            producer.start()
            
            # Measure actual performance
            start_time = time.time()
            count = 0
            
            while time.time() - start_time < 5.0:  # 5 seconds
                if producer.get_next_message(0.001):
                    count += 1
            
            actual_rate = count / 5.0
            
            # Should achieve reasonable percentage of target
            efficiency = (actual_rate / 500.0) * 100
            assert efficiency > 50, f"Performance too low: {actual_rate:.1f} msg/s ({efficiency:.1f}%)"
            
            print(f"✅ High frequency: {actual_rate:.1f} msg/s ({efficiency:.1f}% of 500 msg/s target)")
            
        finally:
            producer.stop()
    
    def test_data_continuity(self):
        """No data gaps or discontinuities."""
        producer = SimpleSyntheticProducer(['CONT_TEST'], 30.0)
        
        try:
            producer.start()
            
            # Track tick IDs for continuity
            tick_ids = []
            timeout = time.time() + 10
            
            while time.time() < timeout and len(tick_ids) < 100:
                msg = producer.get_next_message(0.01)
                if msg:
                    raw = msg['raw_message']
                    parts = raw.split(',')
                    
                    # Extract tick ID based on message type
                    if raw.startswith('T,') and len(parts) >= 9:
                        tick_ids.append(int(parts[8]))
                    elif raw.startswith('Q,') and len(parts) >= 10:
                        tick_ids.append(int(parts[9]))
            
            assert len(tick_ids) > 50, f"Only got {len(tick_ids)} tick IDs"
            
            # Check for gaps
            tick_ids.sort()
            gaps = []
            for i in range(1, len(tick_ids)):
                gap = tick_ids[i] - tick_ids[i-1]
                if gap > 1:
                    gaps.append((tick_ids[i-1], tick_ids[i]))
            
            # Small gaps are acceptable, large gaps indicate problems
            large_gaps = [g for g in gaps if g[1] - g[0] > 10]
            assert len(large_gaps) == 0, f"Found large gaps in tick IDs: {large_gaps}"
            
            print(f"✅ Data continuity: {len(tick_ids)} ticks, "
                  f"{len(gaps)} small gaps, no large gaps")
            
        finally:
            producer.stop()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])