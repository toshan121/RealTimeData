# ClickHouse Data Legitimacy Analysis - Final Report

**Analysis Date:** July 31, 2025  
**Database:** l2_market_data  
**Assessment Score:** 50/100 - QUESTIONABLE

## Executive Summary

The ClickHouse database contains **synthetic/simulated market data** with some realistic characteristics mixed with obvious artificial patterns. This is NOT real market data from IQFeed or live exchanges.

## Data Overview

| Table | Records | Date Range | Symbols |
|-------|---------|------------|---------|
| l2_updates | 1,000 | 2025-07-29 | 5 (AAPL, MSFT, TSLA, NVDA, GOOGL) |
| trades | 500 | 2025-07-29 | 5 (same symbols) |
| quotes | 800 | 2025-07-29 | 5 (same symbols) |
| features | 300 | 2025-07-29 | 5 (same symbols) |

## Key Findings - Synthetic Data Indicators

### 🚩 Major Red Flags

1. **Generic Market Maker IDs**
   - All market makers are named "MM1", "MM2", "MM3", "MM4", "MM5"
   - Real market data would have proper market maker identifiers like CITC, ARCA, NSDQ, etc.

2. **Unrealistic Timestamp Patterns**
   - All activity occurs between 1:00-4:00 AM UTC (outside market hours)
   - 0% activity during actual market hours (14:30-21:00 UTC for US markets)
   - Real markets are closed at 1-4 AM UTC

3. **Artificial Price Ranges**
   - All symbols have suspiciously similar price ranges (~$100-$200)
   - AAPL: $100.01-$199.66
   - GOOGL: $100.64-$199.10  
   - Perfect ~2:1 price ratios across all symbols

### ⚠️ Moderate Concerns

4. **Uniform Spread Patterns**
   - All bid-ask spreads are identical: $0.0099-$0.1000
   - Real market spreads vary significantly by symbol and market conditions

5. **Single Market Center**
   - All trades routed through "NASDAQ" only
   - Real data would show multiple execution venues (ARCA, NYSE, BATS, etc.)

6. **Perfect Price Diversity**
   - Most symbols show 100% price diversity (every update at different price)
   - Real markets show clustering at psychological levels (whole cents, half cents)

## Sample Data Analysis

### L2 Order Book Updates
```
AAPL | MM1 | Level 2 | $105.24 | Size 398
AAPL | MM5 | Level 1 | $196.51 | Size 914
```
- Wide price jumps between consecutive updates
- No realistic order book build-up patterns

### Trade Data
```
AAPL | $151.21 | 833 shares | NASDAQ
AAPL | $189.11 | 692 shares | NASDAQ (2 minutes later)
```
- Extreme price volatility ($38 move in 2 minutes = ~25%)
- No correlation with bid/ask quotes

### Quote Data
```
AAPL | Bid: $124.78 @ 183 | Ask: $124.80 @ 820 | NYSE/NASDAQ
AAPL | Bid: $178.09 @ 155 | Ask: $178.11 @ 120 | NYSE/NASDAQ (1 min later)
```
- Massive quote jumps ($53+ in 1 minute)
- Spreads artificially tight given volatility

## Real vs Synthetic Characteristics

| Aspect | Real Market Data | This Data | Assessment |
|--------|------------------|-----------|------------|
| Market Maker IDs | CITC, ARCA, NSDQ, BATS | MM1, MM2, MM3, MM4, MM5 | ❌ Synthetic |
| Trading Hours | 9:30 AM - 4:00 PM EST | 1:00 AM - 4:00 AM UTC | ❌ Synthetic |
| Price Patterns | Clustering, psychological levels | Uniform distribution | ❌ Synthetic |
| Spread Patterns | Variable by symbol/time | Identical ranges | ❌ Synthetic |
| Market Centers | Multiple venues | NASDAQ only | ❌ Synthetic |
| Volatility | Realistic for symbols | Extreme (25%+ moves) | ❌ Synthetic |
| Volume Patterns | Realistic clustering | Random distribution | ❌ Synthetic |

## Technical Quality Assessment

### ✅ Well-Structured Synthetic Data
- Proper ClickHouse schema implementation
- Consistent data types and formatting
- Good temporal ordering
- Complete feature calculation pipeline

### ❌ Lacks Market Realism
- No correlation with actual market microstructure
- Missing exchange-specific behaviors
- Artificial randomization patterns
- No respect for market hours/calendar

## Conclusion

**VERDICT: SYNTHETIC DATA**

This is clearly **simulated/generated market data** created for testing the microstructure analysis system. While technically well-structured, it exhibits multiple patterns that would never occur in real market data:

1. Activity outside market hours
2. Generic market maker identifiers
3. Unrealistic price volatility
4. Uniform spread distributions
5. Single market center routing

## Recommendations

### For Production Deployment
1. **Replace with real IQFeed data** for live trading
2. **Validate data sources** against known market events
3. **Implement market hours filtering** (9:30 AM - 4:00 PM EST)
4. **Add exchange-specific market maker validation**

### For Testing/Development
1. **Current synthetic data is adequate** for algorithm development
2. **Consider adding more realistic patterns**:
   - Proper market maker IDs
   - Market hours constraints
   - Realistic price clustering
   - Multiple execution venues

### For Backtesting
1. **DO NOT use this data** for performance validation
2. **Results will not translate** to live trading
3. **Download historical IQFeed data** for valid backtests
4. **Implement proper tick-to-trade reconstruction**

---

**Final Assessment:** The ClickHouse database contains well-structured but clearly synthetic market data suitable for system testing but NOT for production trading or realistic backtesting.