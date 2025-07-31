#!/usr/bin/env python3
"""
Detailed ClickHouse Data Analysis Report
========================================

Comprehensive analysis of what's actually in ClickHouse to determine data legitimacy.
"""

import clickhouse_connect
import json
from datetime import datetime

def main():
    print("DETAILED CLICKHOUSE DATA ANALYSIS")
    print("="*60)
    
    # Connect
    try:
        client = clickhouse_connect.get_client(
            host='localhost', port=8123, database='l2_market_data',
            username='l2_user', password='l2_secure_pass'
        )
        print("✓ Connected to ClickHouse")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    analysis = {}
    
    # 1. Table schemas
    print("\n1. TABLE SCHEMAS:")
    tables = ['l2_updates', 'trades', 'quotes', 'features']
    for table in tables:
        try:
            result = client.query(f"DESCRIBE {table}")
            schema = [(row[0], row[1]) for row in result.result_rows]
            analysis[f"{table}_schema"] = schema
            print(f"\n   {table}:")
            for col_name, col_type in schema:
                print(f"     {col_name:20} {col_type}")
        except Exception as e:
            print(f"   {table}: ERROR - {e}")
    
    # 2. Sample data from each table
    print("\n2. SAMPLE DATA:")
    for table in tables:
        try:
            result = client.query(f"SELECT * FROM {table} LIMIT 3")
            if result.result_rows:
                analysis[f"{table}_samples"] = result.result_rows[:3]
                print(f"\n   {table} (first 3 rows):")
                for i, row in enumerate(result.result_rows[:3], 1):
                    print(f"     Row {i}: {row}")
            else:
                print(f"\n   {table}: No data")
                analysis[f"{table}_samples"] = []
        except Exception as e:
            print(f"\n   {table}: ERROR - {e}")
    
    # 3. Data distribution analysis
    print("\n3. DATA DISTRIBUTION:")
    
    # L2 Updates analysis
    try:
        result = client.query("""
            SELECT 
                symbol,
                market_maker,
                COUNT(*) as count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                MIN(size) as min_size,
                MAX(size) as max_size
            FROM l2_updates 
            GROUP BY symbol, market_maker 
            ORDER BY count DESC 
            LIMIT 15
        """)
        
        print("\n   L2 Updates Distribution:")
        print("     Symbol   MM      Count   Price Range         Size Range")
        print("     -------  -----   -----   ---------------     -----------")
        for row in result.result_rows:
            symbol, mm, count, min_p, max_p, min_s, max_s = row
            print(f"     {symbol:7}  {mm:5}   {count:5}   ${float(min_p):6.2f}-${float(max_p):6.2f}    {min_s:5}-{max_s:5}")
        
        analysis['l2_distribution'] = result.result_rows
        
    except Exception as e:
        print(f"   L2 Updates: ERROR - {e}")
    
    # Trades analysis
    try:
        result = client.query("""
            SELECT 
                symbol,
                COUNT(*) as trade_count,
                MIN(trade_price) as min_price,
                MAX(trade_price) as max_price,
                MIN(trade_size) as min_size,
                MAX(trade_size) as max_size,
                trade_market_center
            FROM trades 
            GROUP BY symbol, trade_market_center 
            ORDER BY trade_count DESC
        """)
        
        print("\n   Trades Distribution:")
        print("     Symbol   Count   Price Range         Size Range      Market Center")
        print("     -------  -----   ---------------     -----------     -------------")
        for row in result.result_rows:
            symbol, count, min_p, max_p, min_s, max_s, center = row
            print(f"     {symbol:7}  {count:5}   ${float(min_p):6.2f}-${float(max_p):6.2f}    {min_s:5}-{max_s:5}     {center}")
        
        analysis['trades_distribution'] = result.result_rows
        
    except Exception as e:
        print(f"   Trades: ERROR - {e}")
    
    # Quotes analysis
    try:
        result = client.query("""
            SELECT 
                symbol,
                COUNT(*) as quote_count,
                MIN(bid_price) as min_bid,
                MAX(bid_price) as max_bid,
                MIN(ask_price) as min_ask,
                MAX(ask_price) as max_ask,
                MIN(ask_price - bid_price) as min_spread,
                MAX(ask_price - bid_price) as max_spread
            FROM quotes 
            GROUP BY symbol 
            ORDER BY quote_count DESC
        """)
        
        print("\n   Quotes Distribution:")
        print("     Symbol   Count   Bid Range           Ask Range           Spread Range")
        print("     -------  -----   ---------------     ---------------     -------------")
        for row in result.result_rows:
            symbol, count, min_bid, max_bid, min_ask, max_ask, min_spread, max_spread = row
            print(f"     {symbol:7}  {count:5}   ${float(min_bid):6.2f}-${float(max_bid):6.2f}    "
                  f"${float(min_ask):6.2f}-${float(max_ask):6.2f}    ${float(min_spread):5.3f}-${float(max_spread):5.3f}")
        
        analysis['quotes_distribution'] = result.result_rows
        
    except Exception as e:
        print(f"   Quotes: ERROR - {e}")
    
    # 4. Legitimacy Assessment
    print("\n4. LEGITIMACY ASSESSMENT:")
    
    legitimacy_flags = []
    synthetic_score = 0
    
    # Check market maker patterns
    try:
        result = client.query("SELECT DISTINCT market_maker FROM l2_updates ORDER BY market_maker")
        mm_ids = [row[0] for row in result.result_rows]
        print(f"\n   Market Maker IDs: {mm_ids}")
        
        generic_mm_count = sum(1 for mm in mm_ids if mm.startswith('MM') and len(mm) <= 4)
        if generic_mm_count >= 3:
            legitimacy_flags.append("Multiple generic market maker IDs (MM1, MM2, etc.)")
            synthetic_score += 30
    except:
        pass
    
    # Check price patterns
    try:
        result = client.query("""
            SELECT symbol, 
                   COUNT(DISTINCT price) as unique_prices,
                   COUNT(*) as total_updates,
                   (COUNT(DISTINCT price) * 1.0 / COUNT(*)) as diversity
            FROM l2_updates 
            GROUP BY symbol
        """)
        
        low_diversity_symbols = []
        for row in result.result_rows:
            symbol, unique, total, diversity = row
            if float(diversity) < 0.3:  # Less than 30% price diversity
                low_diversity_symbols.append(symbol)
        
        if low_diversity_symbols:
            legitimacy_flags.append(f"Low price diversity in symbols: {low_diversity_symbols}")
            synthetic_score += 15
            
    except:
        pass
    
    # Check temporal patterns
    try:
        result = client.query("""
            SELECT toHour(timestamp) as hour, COUNT(*) as count
            FROM trades 
            GROUP BY hour 
            ORDER BY count DESC
        """)
        
        if result.result_rows:
            total_trades = sum(row[1] for row in result.result_rows)
            # Check if most activity is outside market hours
            market_hours_trades = sum(row[1] for row in result.result_rows if 14 <= row[0] <= 21)
            market_hours_pct = (market_hours_trades / total_trades * 100) if total_trades > 0 else 0
            
            if market_hours_pct < 50:
                legitimacy_flags.append(f"Low market hours activity ({market_hours_pct:.1f}%)")
                synthetic_score += 20
                
    except:
        pass
    
    # Calculate final legitimacy score
    legitimacy_score = max(0, 100 - synthetic_score)
    
    print(f"\n   Synthetic Score: {synthetic_score}/100")
    print(f"   Legitimacy Score: {legitimacy_score}/100")
    
    if legitimacy_score >= 80:
        assessment = "HIGHLY LEGITIMATE - Real market data characteristics"
    elif legitimacy_score >= 60:
        assessment = "LIKELY LEGITIMATE - Minor synthetic patterns"
    elif legitimacy_score >= 40:
        assessment = "QUESTIONABLE - Mixed real/synthetic characteristics"
    elif legitimacy_score >= 20:
        assessment = "LIKELY SYNTHETIC - Multiple artificial patterns"
    else:
        assessment = "HIGHLY SYNTHETIC - Clear artificial generation"
    
    print(f"   Assessment: {assessment}")
    
    if legitimacy_flags:
        print("\n   Red Flags Detected:")
        for i, flag in enumerate(legitimacy_flags, 1):
            print(f"     {i}. {flag}")
    else:
        print("\n   ✓ No major synthetic patterns detected")
    
    # 5. Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    print(f"Data Period: {analysis.get('date_range', 'Unknown')}")
    print(f"Total Records: L2={analysis.get('l2_count', 0):,}, Trades={analysis.get('trades_count', 0):,}, Quotes={analysis.get('quotes_count', 0):,}")
    print(f"Legitimacy Assessment: {assessment}")
    
    analysis['legitimacy_assessment'] = {
        'score': legitimacy_score,
        'assessment': assessment,
        'flags': legitimacy_flags,
        'timestamp': datetime.now().isoformat()
    }
    
    # Save detailed analysis
    output_file = f"/home/tcr1n15/PycharmProjects/RealTimeData/data/detailed_data_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\n✓ Detailed analysis saved to: {output_file}")
    
    client.close()

if __name__ == "__main__":
    main()