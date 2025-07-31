#!/usr/bin/env python3
"""
ClickHouse Data Legitimacy Analyzer
==================================

Comprehensive analysis to detect synthetic vs real market data patterns.
Examines L2 order book, L1 quotes, and tick data for authenticity markers.

Real market data characteristics:
- Irregular timing patterns (human/algo behavior)
- Market maker ID diversity and consistency
- Realistic price-size relationships
- Natural bid-ask spread distributions
- Volume clustering at psychological price levels
- Time-of-day patterns aligned with market sessions

Synthetic data red flags:
- Perfectly uniform timing
- Sequential or pattern-based market maker IDs
- Unrealistic price movements
- Artificial spread patterns
- Missing market microstructure noise
"""

import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import sys
from collections import Counter, defaultdict
import warnings
warnings.filterwarnings('ignore')

class ClickHouseDataLegitimacyAnalyzer:
    def __init__(self):
        """Initialize connection to ClickHouse."""
        try:
            self.client = clickhouse_connect.get_client(
                host='localhost', 
                port=8123, 
                database='l2_market_data',
                username='l2_user', 
                password='l2_secure_pass'
            )
            print("✓ Connected to ClickHouse successfully")
        except Exception as e:
            print(f"✗ Failed to connect to ClickHouse: {e}")
            sys.exit(1)
    
    def get_data_overview(self):
        """Get basic overview of available data."""
        print("\n" + "="*80)
        print("CLICKHOUSE DATA OVERVIEW")
        print("="*80)
        
        # Check table record counts
        tables = ['l2_updates', 'trades', 'quotes', 'features']
        overview = {}
        
        for table in tables:
            try:
                result = self.client.query(f"SELECT COUNT(*) FROM {table}")
                count = result.result_rows[0][0] if result.result_rows else 0
                overview[table] = count
                print(f"{table:15}: {count:,} records")
            except Exception as e:
                print(f"{table:15}: ERROR - {e}")
                overview[table] = 0
        
        # Check date ranges
        print("\nDATE RANGES:")
        for table in tables:
            if overview[table] > 0:
                try:
                    result = self.client.query(f"""
                        SELECT MIN(date) as min_date, MAX(date) as max_date 
                        FROM {table}
                    """)
                    if result.result_rows:
                        min_date, max_date = result.result_rows[0]
                        print(f"{table:15}: {min_date} to {max_date}")
                except Exception as e:
                    print(f"{table:15}: ERROR getting date range - {e}")
        
        # Check symbol coverage
        print("\nSYMBOL COVERAGE:")
        for table in tables:
            if overview[table] > 0:
                try:
                    result = self.client.query(f"""
                        SELECT COUNT(DISTINCT symbol) as symbol_count 
                        FROM {table}
                    """)
                    if result.result_rows:
                        symbol_count = result.result_rows[0][0]
                        print(f"{table:15}: {symbol_count} unique symbols")
                except Exception as e:
                    print(f"{table:15}: ERROR getting symbol count - {e}")
        
        return overview
    
    def analyze_l2_data_legitimacy(self):
        """Analyze L2 order book data for synthetic patterns."""
        print("\n" + "="*80)
        print("L2 ORDER BOOK LEGITIMACY ANALYSIS")
        print("="*80)
        
        legitimacy_score = 100  # Start at 100, deduct for red flags
        findings = []
        
        # Check if L2 data exists
        result = self.client.query("SELECT COUNT(*) FROM l2_updates")
        if not result.result_rows or result.result_rows[0][0] == 0:
            print("✗ No L2 data found in ClickHouse")
            return {"score": 0, "findings": ["No L2 data available"]}
        
        total_records = result.result_rows[0][0]
        print(f"Analyzing {total_records:,} L2 updates...")
        
        # 1. Market Maker ID Analysis
        print("\n1. MARKET MAKER ID ANALYSIS:")
        result = self.client.query("""
            SELECT 
                market_maker,
                COUNT(*) as update_count,
                COUNT(DISTINCT symbol) as symbol_count
            FROM l2_updates 
            GROUP BY market_maker 
            ORDER BY update_count DESC 
            LIMIT 20
        """)
        
        if result.result_rows:
            mm_patterns = []
            for row in result.result_rows:
                mm_id, count, symbols = row
                mm_patterns.append((mm_id, count, symbols))
                print(f"  {mm_id:15}: {count:,} updates across {symbols} symbols")
            
            # Check for synthetic patterns
            synthetic_mm_flags = 0
            for mm_id, count, symbols in mm_patterns[:10]:  # Top 10 MMs
                # Red flag: Sequential IDs like MM_001, MM_002
                if ('_' in mm_id and mm_id.split('_')[-1].isdigit()):
                    synthetic_mm_flags += 1
                # Red flag: Generic names like TEST, FAKE, SIM
                if any(word in mm_id.upper() for word in ['TEST', 'FAKE', 'SIM', 'SYNTHETIC']):
                    synthetic_mm_flags += 2
            
            if synthetic_mm_flags > 0:
                legitimacy_score -= min(synthetic_mm_flags * 10, 30)
                findings.append(f"Detected {synthetic_mm_flags} synthetic market maker patterns")
            else:
                findings.append("Market maker IDs appear realistic")
        
        # 2. Price Level Distribution Analysis
        print("\n2. PRICE LEVEL DISTRIBUTION:")
        result = self.client.query("""
            SELECT 
                symbol,
                AVG(price) as avg_price,
                MIN(price) as min_price,
                MAX(price) as max_price,
                COUNT(DISTINCT price) as unique_prices,
                COUNT(*) as total_updates
            FROM l2_updates 
            GROUP BY symbol 
            HAVING COUNT(*) > 10
            ORDER BY total_updates DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, avg_price, min_price, max_price, unique_prices, total = row
                price_diversity = unique_prices / total if total > 0 else 0
                price_range = float(max_price) - float(min_price)
                price_range_pct = (price_range / float(avg_price) * 100) if float(avg_price) > 0 else 0
                
                print(f"  {symbol:8}: Avg=${float(avg_price):7.2f}, Range=${price_range:.4f} ({price_range_pct:.2f}%), "
                      f"Diversity={price_diversity:.3f}")
                
                # Red flag: Too uniform pricing (< 0.1 diversity)
                if price_diversity < 0.1:
                    legitimacy_score -= 5
                    findings.append(f"{symbol}: Suspiciously uniform pricing (diversity={price_diversity:.3f})")
                elif min_price == max_price:
                    legitimacy_score -= 10
                    findings.append(f"{symbol}: All prices identical (${float(min_price):.2f})")
        
        # 3. Timing Pattern Analysis (Simplified)
        print("\n3. TIMING PATTERN ANALYSIS:")
        result = self.client.query("""
            SELECT 
                symbol,
                MIN(timestamp) as first_update,
                MAX(timestamp) as last_update,
                COUNT(*) as update_count
            FROM l2_updates 
            GROUP BY symbol
            ORDER BY update_count DESC
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, first_ts, last_ts, count = row
                duration_seconds = (last_ts - first_ts).total_seconds() if last_ts and first_ts else 0
                updates_per_second = count / duration_seconds if duration_seconds > 0 else 0
                
                print(f"  {symbol:8}: {count:,} updates over {duration_seconds:.0f}s = {updates_per_second:.1f}/sec")
                
                # Basic timing red flags
                if duration_seconds < 60 and count > 100:  # Too many updates in short time
                    legitimacy_score -= 5
                    findings.append(f"{symbol}: High update frequency in short time")
        
        # 4. Order Size Analysis
        print("\n4. ORDER SIZE ANALYSIS:")
        result = self.client.query("""
            SELECT 
                symbol,
                AVG(size) as avg_size,
                STDDEV(size) as size_stddev,
                percentile(0.5)(size) as median_size,
                MIN(size) as min_size,
                MAX(size) as max_size
            FROM l2_updates 
            WHERE size > 0
            GROUP BY symbol 
            HAVING COUNT(*) > 100
            ORDER BY AVG(size) DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, avg_size, stddev, median, min_size, max_size = row
                print(f"  {symbol:8}: Avg={float(avg_size):7.0f}, Median={float(median):7.0f}, "
                      f"Range={int(min_size)}-{int(max_size)}")
                
                # Red flag: Unrealistic size patterns
                if min_size == max_size and min_size > 0:  # All same size
                    legitimacy_score -= 15
                    findings.append(f"{symbol}: All order sizes identical ({min_size})")
                elif float(stddev) / float(avg_size) < 0.05:  # Very low variation
                    legitimacy_score -= 8
                    findings.append(f"{symbol}: Suspiciously uniform order sizes")
        
        return {
            "score": max(0, legitimacy_score),
            "findings": findings,
            "total_records": total_records
        }
    
    def analyze_l1_quote_legitimacy(self):
        """Analyze L1 quote data for synthetic patterns."""
        print("\n" + "="*80)
        print("L1 QUOTE DATA LEGITIMACY ANALYSIS")
        print("="*80)
        
        legitimacy_score = 100
        findings = []
        
        # Check if quote data exists
        result = self.client.query("SELECT COUNT(*) FROM quotes")
        if not result.result_rows or result.result_rows[0][0] == 0:
            print("✗ No L1 quote data found in ClickHouse")
            return {"score": 0, "findings": ["No L1 quote data available"]}
        
        total_records = result.result_rows[0][0]
        print(f"Analyzing {total_records:,} quote updates...")
        
        # 1. Spread Analysis
        print("\n1. BID-ASK SPREAD ANALYSIS:")
        result = self.client.query("""
            SELECT 
                symbol,
                AVG(spread) as avg_spread,
                MIN(spread) as min_spread,
                MAX(spread) as max_spread,
                COUNT(*) as quote_count
            FROM quotes 
            WHERE spread > 0 AND spread < 10  -- Filter obvious errors
            GROUP BY symbol 
            HAVING COUNT(*) > 10
            ORDER BY quote_count DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, avg_spread, min_spread, max_spread, count = row
                spread_range = float(max_spread) - float(min_spread)
                
                print(f"  {symbol:8}: Avg=${float(avg_spread):6.4f}, "
                      f"Range=${float(min_spread):6.4f}-${float(max_spread):6.4f}")
                
                # Red flags for spreads
                if min_spread == max_spread:  # All spreads identical
                    legitimacy_score -= 20
                    findings.append(f"{symbol}: All spreads identical (${float(min_spread):.4f})")
                elif spread_range < 0.0001:  # Very low spread variation
                    legitimacy_score -= 10
                    findings.append(f"{symbol}: Suspiciously uniform spreads (range=${spread_range:.6f})")
                elif float(min_spread) <= 0:  # Negative or zero spreads
                    legitimacy_score -= 15
                    findings.append(f"{symbol}: Invalid spreads detected (min=${float(min_spread):.4f})")
        
        # 2. Quote Update Frequency Analysis
        print("\n2. QUOTE UPDATE FREQUENCY:")
        result = self.client.query("""
            SELECT 
                symbol,
                COUNT(*) as total_quotes,
                COUNT(DISTINCT toStartOfMinute(timestamp)) as active_minutes,
                COUNT(*) / COUNT(DISTINCT toStartOfMinute(timestamp)) as quotes_per_minute
            FROM quotes 
            GROUP BY symbol 
            HAVING COUNT(*) > 100
            ORDER BY quotes_per_minute DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, total, minutes, qpm = row
                print(f"  {symbol:8}: {total:,} quotes in {minutes} minutes = {float(qpm):6.1f} q/min")
                
                # Red flag: Unrealistic quote frequency
                if float(qpm) > 1000:  # More than 1000 quotes/minute is suspicious
                    legitimacy_score -= 5
                    findings.append(f"{symbol}: Extremely high quote frequency ({float(qpm):.1f}/min)")
        
        # 3. Market Center Analysis
        print("\n3. MARKET CENTER DISTRIBUTION:")
        result = self.client.query("""
            SELECT 
                bid_market_center,
                ask_market_center,
                COUNT(*) as occurrence_count
            FROM quotes 
            GROUP BY bid_market_center, ask_market_center 
            ORDER BY occurrence_count DESC 
            LIMIT 15
        """)
        
        if result.result_rows:
            synthetic_center_flags = 0
            for row in result.result_rows:
                bid_center, ask_center, count = row
                print(f"  {bid_center:10} / {ask_center:10}: {count:,} occurrences")
                
                # Check for synthetic market center names
                for center in [bid_center, ask_center]:
                    if any(word in center.upper() for word in ['TEST', 'FAKE', 'SIM', 'SYNTHETIC']):
                        synthetic_center_flags += 1
            
            if synthetic_center_flags > 0:
                legitimacy_score -= synthetic_center_flags * 8
                findings.append(f"Detected {synthetic_center_flags} synthetic market center names")
        
        return {
            "score": max(0, legitimacy_score),
            "findings": findings,
            "total_records": total_records
        }
    
    def analyze_trade_legitimacy(self):
        """Analyze trade/tick data for synthetic patterns."""
        print("\n" + "="*80)
        print("TRADE/TICK DATA LEGITIMACY ANALYSIS")
        print("="*80)
        
        legitimacy_score = 100
        findings = []
        
        # Check if trade data exists
        result = self.client.query("SELECT COUNT(*) FROM trades")
        if not result.result_rows or result.result_rows[0][0] == 0:
            print("✗ No trade data found in ClickHouse")
            return {"score": 0, "findings": ["No trade data available"]}
        
        total_records = result.result_rows[0][0]
        print(f"Analyzing {total_records:,} trades...")
        
        # 1. Price Distribution Analysis
        print("\n1. TRADE PRICE DISTRIBUTION:")
        result = self.client.query("""
            SELECT 
                symbol,
                MIN(trade_price) as min_price,
                MAX(trade_price) as max_price,
                AVG(trade_price) as avg_price,
                COUNT(DISTINCT trade_price) as unique_prices,
                COUNT(*) as trade_count
            FROM trades 
            GROUP BY symbol 
            HAVING COUNT(*) > 10
            ORDER BY trade_count DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, min_p, max_p, avg_p, unique_prices, total = row
                price_range_pct = (float(max_p) - float(min_p)) / float(avg_p) * 100 if float(avg_p) > 0 else 0
                price_diversity = unique_prices / total if total > 0 else 0
                
                print(f"  {symbol:8}: ${float(min_p):7.2f}-${float(max_p):7.2f} "
                      f"(range: {price_range_pct:5.1f}%, diversity: {price_diversity:.3f})")
                
                # Red flags for trade prices
                if price_diversity < 0.05:  # Very few unique prices
                    legitimacy_score -= 8
                    findings.append(f"{symbol}: Low price diversity ({price_diversity:.3f})")
                elif price_range_pct > 50:  # Unrealistic price range
                    legitimacy_score -= 10
                    findings.append(f"{symbol}: Suspicious price range ({price_range_pct:.1f}%)")
                elif min_p == max_p:  # All same price
                    legitimacy_score -= 15
                    findings.append(f"{symbol}: All trades at same price (${float(min_p):.2f})")
        
        # 2. Volume Analysis
        print("\n2. TRADE VOLUME ANALYSIS:")
        result = self.client.query("""
            SELECT 
                symbol,
                MIN(trade_size) as min_size,
                MAX(trade_size) as max_size,
                AVG(trade_size) as avg_size,
                percentile(0.5)(trade_size) as median_size,
                COUNT(*) as trade_count
            FROM trades 
            WHERE trade_size > 0
            GROUP BY symbol 
            HAVING COUNT(*) > 50
            ORDER BY trade_count DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                symbol, min_size, max_size, avg_size, median_size, count = row
                size_ratio = float(max_size) / float(min_size) if float(min_size) > 0 else 0
                
                print(f"  {symbol:8}: {int(min_size):,}-{int(max_size):,} shares "
                      f"(avg: {float(avg_size):,.0f}, median: {float(median_size):,.0f})")
                
                # Red flags for volume
                if min_size == max_size:  # All same size
                    legitimacy_score -= 15
                    findings.append(f"{symbol}: All trades same size ({int(min_size):,})")
                elif size_ratio > 10000:  # Extreme size variation
                    legitimacy_score -= 8
                    findings.append(f"{symbol}: Extreme volume variation (ratio: {size_ratio:.0f})")
        
        # 3. Trade Conditions Analysis
        print("\n3. TRADE CONDITIONS ANALYSIS:")
        result = self.client.query("""
            SELECT 
                trade_conditions,
                COUNT(*) as occurrence_count,
                COUNT(DISTINCT symbol) as symbol_count
            FROM trades 
            WHERE trade_conditions != ''
            GROUP BY trade_conditions 
            ORDER BY occurrence_count DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            synthetic_condition_flags = 0
            for row in result.result_rows:
                condition, count, symbols = row
                print(f"  '{condition:15}': {count:,} trades across {symbols} symbols")
                
                # Check for synthetic trade conditions
                if any(word in condition.upper() for word in ['TEST', 'FAKE', 'SIM', 'SYNTHETIC']):
                    synthetic_condition_flags += 1
            
            if synthetic_condition_flags > 0:
                legitimacy_score -= synthetic_condition_flags * 10
                findings.append(f"Detected {synthetic_condition_flags} synthetic trade conditions")
        
        # 4. Market Center Analysis
        print("\n4. TRADE MARKET CENTER ANALYSIS:")
        result = self.client.query("""
            SELECT 
                trade_market_center,
                COUNT(*) as trade_count,
                COUNT(DISTINCT symbol) as symbol_count,
                AVG(trade_size) as avg_trade_size
            FROM trades 
            WHERE trade_market_center != ''
            GROUP BY trade_market_center 
            ORDER BY trade_count DESC 
            LIMIT 10
        """)
        
        if result.result_rows:
            for row in result.result_rows:
                center, count, symbols, avg_size = row
                print(f"  {center:15}: {count:,} trades, {symbols} symbols, avg size: {float(avg_size):,.0f}")
        
        return {
            "score": max(0, legitimacy_score),
            "findings": findings,
            "total_records": total_records
        }
    
    def analyze_temporal_patterns(self):
        """Analyze temporal patterns for market hour consistency."""
        print("\n" + "="*80)
        print("TEMPORAL PATTERN ANALYSIS")
        print("="*80)
        
        legitimacy_score = 100
        findings = []
        
        # Check trading hour distribution
        print("\n1. TRADING HOUR DISTRIBUTION:")
        result = self.client.query("""
            SELECT 
                toHour(timestamp) as hour,
                COUNT(*) as activity_count
            FROM trades 
            GROUP BY hour 
            ORDER BY hour
        """)
        
        if result.result_rows:
            total_activity = sum(row[1] for row in result.result_rows)
            print("  Hour | Activity Count | % of Total")
            print("  -----|---------------|----------")
            
            market_hours_activity = 0  # 9:30 AM - 4:00 PM EST (14:30-21:00 UTC)
            
            for hour, count in result.result_rows:
                pct = (count / total_activity * 100) if total_activity > 0 else 0
                print(f"  {hour:4d} | {count:13,} | {pct:7.2f}%")
                
                # Check if activity aligns with market hours (approximate)
                if 14 <= hour <= 21:  # Market hours in UTC (approximate)
                    market_hours_activity += count
            
            market_hours_pct = (market_hours_activity / total_activity * 100) if total_activity > 0 else 0
            
            if market_hours_pct < 70:  # Less than 70% during market hours is suspicious
                legitimacy_score -= 15
                findings.append(f"Low market hours activity ({market_hours_pct:.1f}%)")
            else:
                findings.append(f"Good market hours concentration ({market_hours_pct:.1f}%)")
        
        # Check weekend activity
        print("\n2. DAY OF WEEK DISTRIBUTION:")
        result = self.client.query("""
            SELECT 
                toDayOfWeek(timestamp) as dow,
                COUNT(*) as activity_count
            FROM trades 
            GROUP BY dow 
            ORDER BY dow
        """)
        
        if result.result_rows:
            days = ['', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            total_activity = sum(row[1] for row in result.result_rows)
            weekend_activity = 0
            
            for dow, count in result.result_rows:
                pct = (count / total_activity * 100) if total_activity > 0 else 0
                day_name = days[dow] if dow < len(days) else f'Day_{dow}'
                print(f"  {day_name:10} | {count:13,} | {pct:7.2f}%")
                
                if dow in [6, 7]:  # Saturday, Sunday
                    weekend_activity += count
            
            weekend_pct = (weekend_activity / total_activity * 100) if total_activity > 0 else 0
            
            if weekend_pct > 5:  # More than 5% weekend activity is suspicious
                legitimacy_score -= 10
                findings.append(f"Suspicious weekend activity ({weekend_pct:.1f}%)")
        
        return {
            "score": max(0, legitimacy_score),
            "findings": findings
        }
    
    def generate_legitimacy_report(self):
        """Generate comprehensive legitimacy assessment report."""
        print("\n" + "="*80)
        print("COMPREHENSIVE DATA LEGITIMACY ASSESSMENT")
        print("="*80)
        
        # Get data overview
        overview = self.get_data_overview()
        
        # Run all analyses
        l2_analysis = self.analyze_l2_data_legitimacy()
        l1_analysis = self.analyze_l1_quote_legitimacy()
        trade_analysis = self.analyze_trade_legitimacy()
        temporal_analysis = self.analyze_temporal_patterns()
        
        # Calculate overall legitimacy score
        analyses = [l2_analysis, l1_analysis, trade_analysis, temporal_analysis]
        valid_scores = [a['score'] for a in analyses if a['score'] > 0]
        
        if valid_scores:
            overall_score = sum(valid_scores) / len(valid_scores)
        else:
            overall_score = 0
        
        # Generate report
        report = {
            "timestamp": datetime.now().isoformat(),
            "overall_legitimacy_score": round(overall_score, 1),
            "data_overview": overview,
            "analyses": {
                "l2_order_book": l2_analysis,
                "l1_quotes": l1_analysis,
                "trades": trade_analysis,
                "temporal_patterns": temporal_analysis
            },
            "assessment": self._get_assessment(overall_score),
            "recommendations": self._get_recommendations(analyses)
        }
        
        # Print summary
        print("\n" + "="*80)
        print("FINAL ASSESSMENT")
        print("="*80)
        print(f"Overall Legitimacy Score: {overall_score:.1f}/100")
        print(f"Assessment: {report['assessment']}")
        
        print("\nKey Findings:")
        all_findings = []
        for analysis in analyses:
            all_findings.extend(analysis['findings'])
        
        for i, finding in enumerate(all_findings[:10], 1):  # Top 10 findings
            print(f"  {i:2d}. {finding}")
        
        if len(all_findings) > 10:
            print(f"  ... and {len(all_findings) - 10} more findings")
        
        print("\nRecommendations:")
        for i, rec in enumerate(report['recommendations'], 1):
            print(f"  {i}. {rec}")
        
        return report
    
    def _get_assessment(self, score):
        """Get qualitative assessment based on score."""
        if score >= 85:
            return "HIGHLY LEGITIMATE - Data appears to be real market data"
        elif score >= 70:
            return "LIKELY LEGITIMATE - Minor synthetic patterns detected"
        elif score >= 50:
            return "QUESTIONABLE - Significant synthetic characteristics"
        elif score >= 25:
            return "LIKELY SYNTHETIC - Multiple red flags detected"
        else:
            return "HIGHLY SYNTHETIC - Data appears artificially generated"
    
    def _get_recommendations(self, analyses):
        """Generate recommendations based on analysis results."""
        recommendations = []
        
        # Check for missing data types
        if any(a['score'] == 0 for a in analyses):
            recommendations.append("Ensure all data types (L2, L1, trades) are being captured")
        
        # Check for low scores
        low_score_analyses = [a for a in analyses if 0 < a['score'] < 60]
        if low_score_analyses:
            recommendations.append("Review data generation/ingestion processes for realism")
        
        # General recommendations
        recommendations.extend([
            "Validate market maker IDs against real exchange specifications",
            "Ensure price movements follow realistic market dynamics",
            "Verify timestamp accuracy and irregular human/algorithmic patterns",
            "Cross-reference with known market events during data periods"
        ])
        
        return recommendations
    
    def save_report(self, report, filename=None):
        """Save report to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"/home/tcr1n15/PycharmProjects/RealTimeData/data/clickhouse_legitimacy_report_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n✓ Report saved to: {filename}")
        return filename
    
    def close(self):
        """Close ClickHouse connection."""
        if hasattr(self, 'client'):
            self.client.close()

def main():
    """Main execution function."""
    analyzer = ClickHouseDataLegitimacyAnalyzer()
    
    try:
        # Generate comprehensive report
        report = analyzer.generate_legitimacy_report()
        
        # Save report
        analyzer.save_report(report)
        
        print(f"\nAnalysis complete. Overall legitimacy score: {report['overall_legitimacy_score']}/100")
        print(f"Assessment: {report['assessment']}")
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        analyzer.close()

if __name__ == "__main__":
    main()