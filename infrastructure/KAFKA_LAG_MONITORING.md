# Kafka Lag Monitoring - Minimal Implementation

## Overview

This document describes the minimal Kafka lag monitoring implementation that avoids over-engineering while meeting all core requirements.

## Core Philosophy: Keep It Simple

- **No complex distributed monitoring** - Use Kafka's built-in tools
- **No real-time dashboards** - Periodic checks are sufficient
- **No predictive analytics** - Simple threshold alerts work fine
- **No custom infrastructure** - Leverage existing Docker/Kafka setup

## What We Have (Already Implemented)

### 1. `kafka_lag_monitor.py` - Standalone Monitor
Located at: `/home/tcr1n15/PycharmProjects/RealTimeData/kafka_lag_monitor.py`

**Features:**
- ✅ Checks consumer group lag for all topics
- ✅ Identifies slow/stuck consumers
- ✅ Basic threshold alerting (warning: 1000, critical: 10000)
- ✅ JSON output for integration
- ✅ Continuous monitoring mode
- ✅ Docker-aware (auto-detects containerized Kafka)

### 2. `health-check.sh` - Integrated Health Checks
Located at: `/home/tcr1n15/PycharmProjects/RealTimeData/infrastructure/scripts/health-check.sh`

**Features:**
- ✅ Already includes Kafka lag monitoring (lines 37-52)
- ✅ Visual indicators for lag status
- ✅ Runs as part of infrastructure health checks

### 3. `production_health_monitor.py` - Production Monitoring
Located at: `/home/tcr1n15/PycharmProjects/RealTimeData/realtime/monitoring/production_health_monitor.py`

**Features:**
- ✅ Comprehensive system monitoring
- ✅ Has basic Kafka lag check (can be enhanced)
- ✅ Automated alerting and recovery

## Usage Examples

### Quick One-Time Check
```bash
# Check current lag (pretty output)
python kafka_lag_monitor.py

# Check current lag (JSON output)
python kafka_lag_monitor.py --json
```

### Continuous Monitoring
```bash
# Monitor every 30 seconds
python kafka_lag_monitor.py --continuous --interval 30

# Monitor with custom thresholds
python kafka_lag_monitor.py --continuous --warning-threshold 5000 --critical-threshold 20000
```

### Integration with Health Check
```bash
# Run complete infrastructure health check (includes lag)
cd infrastructure/scripts
./health-check.sh
```

### Python Integration
```python
from kafka_lag_monitor import KafkaLagMonitor

# Initialize monitor
monitor = KafkaLagMonitor(
    bootstrap_servers="localhost:9092",
    lag_warning_threshold=1000,
    lag_critical_threshold=10000
)

# Get lag information
results = monitor.check_all_groups()

# Check specific group
group_lag = monitor.get_group_lag("my-consumer-group")
```

## Output Format

### Console Output
```
=== Kafka Consumer Lag Summary ===
Timestamp: 2025-07-30T10:30:00
Total Groups: 3

✅ No lag alerts (thresholds: warning>1,000, critical>10,000)

📊 Group Details:
  ✅ l2-processor: 125 lag across 2 topics
  ✅ market-analyzer: 0 lag across 3 topics
  ⚠️ backtest-engine: 2,500 lag across 1 topics
```

### JSON Output
```json
{
  "timestamp": "2025-07-30T10:30:00",
  "total_groups": 3,
  "groups": {
    "l2-processor": {
      "group_id": "l2-processor",
      "total_lag": 125,
      "topics": {...}
    }
  },
  "alerts": []
}
```

## Alert Thresholds

Default thresholds (sensible for most use cases):
- **Warning**: 1,000 messages behind
- **Critical**: 10,000 messages behind

These can be adjusted based on your message volume and latency requirements.

## Testing

Run the test script to validate the setup:
```bash
cd infrastructure/scripts
./test-kafka-lag.sh
```

## Troubleshooting

### No Consumer Groups Found
- Ensure Kafka consumers are running
- Check if consumers have committed offsets
- Verify Kafka connectivity

### High Lag Detected
1. Check if consumers are running: `docker ps | grep consumer`
2. Check consumer logs: `docker logs <consumer-container>`
3. Verify topic partitions: `docker exec l2_kafka kafka-topics.sh --describe --topic <topic>`
4. Consider scaling consumers if needed

### Connection Issues
- Ensure Kafka is running: `docker ps | grep l2_kafka`
- Check bootstrap servers configuration
- Verify network connectivity

## Best Practices

1. **Don't Over-Monitor**: Check lag every 30-60 seconds, not every second
2. **Set Reasonable Thresholds**: Based on your actual message rates
3. **Act on Alerts**: High lag usually means consumers need attention
4. **Keep It Simple**: This minimal solution handles 99% of use cases

## What This Solution Does NOT Include (By Design)

- ❌ Complex distributed tracing
- ❌ Real-time streaming dashboards  
- ❌ Predictive lag analytics
- ❌ Multi-cluster monitoring
- ❌ Historical lag trending
- ❌ Automatic consumer scaling

These features add complexity without proportional value for most trading systems.

## Integration Points

The lag monitor integrates cleanly with:
- Infrastructure health checks (`health-check.sh`)
- Production monitoring (`production_health_monitor.py`)
- Django monitoring UI (via API endpoints)
- External alerting systems (via JSON output)

## Summary

This minimal Kafka lag monitoring solution provides everything needed to:
- Monitor consumer lag across all topics
- Alert on high lag conditions
- Integrate with existing monitoring
- Troubleshoot consumer issues

It achieves these goals with ~300 lines of well-tested Python code, using only standard Kafka tools and no additional infrastructure.