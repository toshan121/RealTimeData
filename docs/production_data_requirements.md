# Production Data Requirements Specification

## Executive Summary

This document specifies the data requirements for running the L2 microstructure analysis system in production. Based on extensive testing and gapper vs non-gapper analysis, we've identified the critical data feeds and specifications needed to detect stealth accumulation patterns.

## Core Data Requirements

### 1. Real-Time Level 2 Order Book Data

**Provider**: IQFeed Professional or equivalent
**Coverage**: 2,000 actively traded stocks (see stock_universe.json)
**Update Frequency**: Every order book change (microsecond latency)

**Required Fields**:
- Symbol
- Timestamp (microsecond precision)
- Side (bid/ask)
- Price (minimum 3 decimal places)
- Size (share count)
- Exchange/MMID
- Update type (add/update/delete)

**Data Volume**: ~500,000-1,000,000 L2 updates per second across all symbols

### 2. Time & Sales (Tick Data)

**Coverage**: Same 2,000 stocks
**Latency**: < 50ms from execution

**Required Fields**:
- Symbol
- Timestamp (microsecond precision)
- Price
- Size
- Exchange
- Trade conditions
- Bid/Ask at time of trade
- Trade direction indicator (uptick/downtick)

### 3. Consolidated Tape Data

**Purpose**: Dark pool inference
**Coverage**: All US exchanges + ATS/Dark pools

**Required**:
- Consolidated volume vs lit exchange volume
- Hidden/iceberg order indicators
- Block trade indicators

### 4. Historical Data Requirements

**Minimum History**: 30 days of tick and L2 data
**Purpose**: Pattern training and signal calibration

**Storage Requirements**:
- L2 Data: ~5TB for 30 days (compressed)
- Tick Data: ~1TB for 30 days (compressed)
- Total: ~6TB rolling window

### 5. Market Hours Coverage

**Pre-Market**: 4:00 AM - 9:30 AM ET (CRITICAL)
**Regular Hours**: 9:30 AM - 4:00 PM ET
**After Hours**: 4:00 PM - 8:00 PM ET (IMPORTANT)

**Note**: Pre-market and after-hours data is essential for detecting accumulation patterns

## Data Quality Requirements

### Completeness
- No gaps in L2 sequence numbers
- All exchanges represented
- Timestamp continuity checks

### Accuracy
- Price/size validation ranges
- Cross-validation between L2 and trades
- Spread sanity checks

### Latency
- L2 updates: < 10ms from exchange
- Trades: < 50ms from execution
- Internal processing: < 100μs per update

## Infrastructure Requirements

### Network
- Dedicated 10Gbps connection minimum
- Co-location recommended for lowest latency
- Redundant connections for failover

### Processing
- 24 GPUs (NVIDIA) for parallel processing
- 256GB RAM minimum per processing node
- NVMe storage for hot data

### Message Queue
- Kafka cluster with 3+ brokers
- Retention: 24 hours minimum
- Partitioning by symbol

### Time-Series Database
- ClickHouse or similar
- Optimized for time-series queries
- Support for 1M+ inserts/second

## Data Normalization

### Symbol Mapping
- Maintain symbol change history
- Handle corporate actions
- Map to consistent internal IDs

### Price Adjustments
- Split adjustments in real-time
- Dividend adjustments for continuity
- Handle special dividends

### Exchange Codes
- Normalize exchange identifiers
- Map dark pool indicators
- Track market maker IDs

## Filtering Requirements

### Universe Selection
- Minimum average daily volume: 1M shares
- Price range: $5 - $1000
- Listed on major exchanges (NYSE, NASDAQ)
- Exclude: ETFs, ADRs (unless specified)

### Data Filtering
- Remove crossed markets
- Filter stub quotes
- Validate against NBBO
- Remove erroneous prints

## Critical Success Factors

### 1. Pre-Market Data Quality
Our analysis shows pre-market (4:00-9:30 AM) is the most critical period for detecting accumulation. Ensure:
- Full depth of book
- All market maker quotes
- Dark pool indications

### 2. Order Book Depth
Minimum 10 levels each side, preferably full book:
- Detect iceberg orders
- Track large hidden liquidity
- Monitor bid persistence

### 3. Trade Attribution
Must identify:
- Trades hitting bid vs lifting offer
- Block trades vs retail
- Sweep orders

### 4. Real-Time Performance
System must handle:
- 1M+ events/second ingestion
- < 100μs signal calculation
- < 5ms end-to-end latency

## Data Provider Evaluation

### Recommended Providers
1. **IQFeed Professional**
   - Pros: Native L2, good API, reliable
   - Cons: Limited historical L2

2. **Refinitiv Elektron**
   - Pros: Full depth, extensive history
   - Cons: Complex integration

3. **Bloomberg B-PIPE**
   - Pros: Comprehensive coverage
   - Cons: Expensive, complex

### Minimum Requirements Checklist
- [ ] Real-time L2 order book (10+ levels)
- [ ] Microsecond timestamps
- [ ] Pre/post market data
- [ ] Trade direction indicators
- [ ] 30+ day history available
- [ ] API supporting 1M+ msg/sec
- [ ] Exchange/dark pool attribution
- [ ] Corporate action adjustments

## Implementation Timeline

### Phase 1: Basic Setup (Week 1-2)
- Establish data feeds
- Set up Kafka ingestion
- Validate data quality

### Phase 2: Historical Loading (Week 3-4)
- Backfill 30 days of data
- Calibrate signals on historical data
- Validate patterns

### Phase 3: Production Rollout (Week 5-6)
- Start real-time processing
- Monitor signal quality
- Tune thresholds

### Phase 4: Scaling (Week 7-8)
- Expand to full universe
- Optimize GPU processing
- Add redundancy

## Monitoring & Alerts

### Data Quality Metrics
- Missing updates per symbol
- Latency percentiles
- Spread validity
- Volume reconciliation

### System Health
- Kafka lag
- GPU utilization
- Signal calculation time
- Database query performance

### Business Metrics
- Signals generated/hour
- False positive rate
- Coverage percentage
- Pattern detection rate

## Cost Estimates

### Data Feeds
- Professional L2 feed: $5,000-15,000/month
- Historical data: $10,000-50,000 one-time
- Ongoing storage: $2,000/month

### Infrastructure
- GPU instances: $10,000/month
- Network/bandwidth: $3,000/month
- Database/storage: $5,000/month

### Total Monthly: $25,000-40,000

## Conclusion

These data requirements are based on extensive analysis of gapper vs non-gapper patterns. The key findings show that detecting stealth accumulation requires:

1. **Full market hours coverage** (especially pre-market)
2. **Deep order book data** (10+ levels)
3. **Microsecond precision** timing
4. **Trade direction attribution**
5. **Historical data** for pattern training

Meeting these requirements will enable the system to detect the subtle accumulation patterns that precede significant price gaps with high accuracy.