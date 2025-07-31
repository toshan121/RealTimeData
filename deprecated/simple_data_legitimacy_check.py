#!/usr/bin/env python3
"""
Simple ClickHouse Data Legitimacy Check
======================================

Quick analysis to determine if ClickHouse data is real or synthetic.
"""

import clickhouse_connect
import sys
from datetime import datetime

def main():
    """Main execution - simple and direct."""
    print("CLICKHOUSE DATA LEGITIMACY CHECK")
    print("="*50)
    
    # Connect to ClickHouse
    try:
        client = clickhouse_connect.get_client(
            host='localhost', port=8123, database='l2_market_data',
            username='l2_user', password='l2_secure_pass'
        )
        print("✓ Connected to ClickHouse")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return
    
    synthetic_flags = 0
    legitimacy_score = 100
    
    # 1. Basic Data Overview
    print("\n1. DATA OVERVIEW:")
    tables = ['l2_updates', 'trades', 'quotes']
    for table in tables:
        try:
            result = client.query(f"SELECT COUNT(*) FROM {table}")
            count = result.result_rows[0][0] if result.result_rows else 0
            print(f"   {table}: {count:,} records")
        except:
            print(f"   {table}: ERROR")
    
    # 2. Market Maker Analysis
    print("\n2. MARKET MAKER ANALYSIS:")
    try:
        result = client.query("""
            SELECT market_maker, COUNT(*) as count 
            FROM l2_updates 
            GROUP BY market_maker 
            ORDER BY count DESC 
            LIMIT 10
        """)
        
        for row in result.result_rows:
            mm_id, count = row
            print(f"   {mm_id}: {count:,} updates")
            
            # Red flags for synthetic MMs
            if mm_id.startswith('MM') and len(mm_id) <= 4:
                synthetic_flags += 1
            if any(word in mm_id.upper() for word in ['TEST', 'FAKE', 'SIM']):
                synthetic_flags += 2
                
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # 3. Price Analysis
    print("\n3. PRICE LEGITIMACY:")
    try:
        result = client.query("""
            SELECT 
                symbol,
                MIN(price) as min_price,
                MAX(price) as max_price,
                COUNT(DISTINCT price) as unique_prices,
                COUNT(*) as total
            FROM l2_updates 
            GROUP BY symbol 
            ORDER BY total DESC
        """)
        
        for row in result.result_rows:
            symbol, min_p, max_p, unique, total = row
            diversity = unique / total if total > 0 else 0
            range_ratio = float(max_p) / float(min_p) if float(min_p) > 0 else 0
            
            print(f"   {symbol}: ${float(min_p):.2f}-${float(max_p):.2f}, "
                  f"diversity={diversity:.3f}, range_ratio={range_ratio:.2f}")
            
            # Red flags
            if min_p == max_p:
                synthetic_flags += 3
                print(f"      ⚠️  All prices identical!")
            elif diversity < 0.1:
                synthetic_flags += 2
                print(f"      ⚠️  Low price diversity")
            elif range_ratio > 10:
                synthetic_flags += 2
                print(f"      ⚠️  Suspicious price range")
                
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # 4. Spread Analysis (if quotes exist)
    print("\n4. SPREAD ANALYSIS:")
    try:
        result = client.query("""
            SELECT 
                symbol,
                MIN(spread) as min_spread,
                MAX(spread) as max_spread,
                COUNT(*) as quote_count
            FROM quotes 
            WHERE spread > 0
            GROUP BY symbol 
            ORDER BY quote_count DESC
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, min_spread, max_spread, count = row
                print(f"   {symbol}: ${float(min_spread):.4f}-${float(max_spread):.4f} ({count:,} quotes)")
                
                # Red flags
                if min_spread == max_spread:
                    synthetic_flags += 3
                    print(f"      ⚠️  All spreads identical!")
                elif float(min_spread) <= 0:
                    synthetic_flags += 2
                    print(f"      ⚠️  Invalid spreads detected")
        else:
            print("   No valid quotes found")
            
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # 5. Trade Analysis
    print("\n5. TRADE ANALYSIS:")
    try:
        result = client.query("""
            SELECT 
                symbol,
                MIN(trade_price) as min_price,
                MAX(trade_price) as max_price,
                COUNT(DISTINCT trade_price) as unique_prices,
                COUNT(*) as trade_count
            FROM trades 
            GROUP BY symbol 
            ORDER BY trade_count DESC
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, min_p, max_p, unique, count = row
                diversity = unique / count if count > 0 else 0
                print(f"   {symbol}: ${float(min_p):.2f}-${float(max_p):.2f}, "
                      f"diversity={diversity:.3f} ({count:,} trades)")
                
                # Red flags
                if min_p == max_p:
                    synthetic_flags += 3
                    print(f"      ⚠️  All trade prices identical!")
                elif diversity < 0.05:
                    synthetic_flags += 1
                    print(f"      ⚠️  Low trade price diversity")
        else:
            print("   No trades found")
            
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # 6. Temporal Analysis
    print("\n6. TEMPORAL ANALYSIS:")
    try:
        result = client.query("""
            SELECT 
                toHour(timestamp) as hour,
                COUNT(*) as activity
            FROM trades 
            GROUP BY hour 
            ORDER BY hour
        """)
        
        if result.result_rows:
            total_activity = sum(row[1] for row in result.result_rows)
            market_hours_activity = 0
            weekend_activity = 0
            
            print("   Trading activity by hour:")
            for hour, activity in result.result_rows:
                pct = (activity / total_activity * 100) if total_activity > 0 else 0
                print(f"     {hour:2d}:00 - {activity:4d} ({pct:4.1f}%)")
                
                # Market hours (approximate 9:30 AM - 4:00 PM EST = 14:30-21:00 UTC)
                if 14 <= hour <= 21:
                    market_hours_activity += activity
            
            market_hours_pct = (market_hours_activity / total_activity * 100) if total_activity > 0 else 0
            print(f"   Market hours concentration: {market_hours_pct:.1f}%")
            
            if market_hours_pct < 50:
                synthetic_flags += 2
                print("      ⚠️  Low market hours activity")
                
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Final Assessment
    legitimacy_score = max(0, 100 - (synthetic_flags * 8))
    
    print("\n" + "="*50)
    print("FINAL ASSESSMENT")
    print("="*50)
    print(f"Synthetic flags detected: {synthetic_flags}")
    print(f"Legitimacy score: {legitimacy_score}/100")
    
    if legitimacy_score >= 80:
        assessment = "LIKELY REAL - Data appears legitimate"
    elif legitimacy_score >= 60:
        assessment = "QUESTIONABLE - Some synthetic patterns"
    elif legitimacy_score >= 40:
        assessment = "LIKELY SYNTHETIC - Multiple red flags"
    else:
        assessment = "HIGHLY SYNTHETIC - Clear artificial patterns"
    
    print(f"Assessment: {assessment}")
    
    # Summary findings
    if synthetic_flags > 0:
        print("\nRed flags detected:")
        if any('MM' in str(row[0]) for row in client.query("SELECT DISTINCT market_maker FROM l2_updates LIMIT 5").result_rows):
            print("- Generic market maker IDs (MM1, MM2, etc.)")
        print("- Check price/spread uniformity patterns")
        print("- Verify temporal distribution patterns")
    else:
        print("\n✓ No obvious synthetic patterns detected")
    
    client.close()
    print(f"\nAnalysis completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()