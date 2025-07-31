# End-to-End Data Pipeline Management Guide

## Overview

This document provides comprehensive guidance for managing the end-to-end data pipeline system that processes market data from IQFeed through Kafka, processing components, and storage systems.

## Architecture

The pipeline consists of the following components:

```
IQFeed → Pipeline Orchestrator → Kafka → Processing → Storage
                ↓                           ↓         ↓
        Health Monitor ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ←
```

### Key Components

1. **Pipeline Orchestrator** (`pipeline_orchestrator.py`)
   - Coordinates data flow between all components
   - Manages component lifecycle and dependencies
   - Provides end-to-end message tracing
   - Handles error recovery and circuit breaking

2. **Health Monitor** (`pipeline_health_monitor.py`)
   - Real-time health monitoring and alerting
   - Performance metrics collection
   - Bottleneck detection and analysis
   - Alert management and recommendations

3. **Pipeline Validator** (`validate_data_pipeline.py`)
   - Comprehensive system validation
   - Infrastructure health checks
   - Performance benchmarking
   - Integration testing

4. **Pipeline Manager** (`manage_pipeline.py`)
   - Production management interface
   - Startup/shutdown procedures
   - Scaling and maintenance operations
   - Configuration management

## Quick Start

### Prerequisites

1. **Infrastructure Services Running:**
   ```bash
   cd infrastructure
   docker-compose up -d
   ```

2. **Python Environment:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure logs directory exists:**
   ```bash
   mkdir -p logs
   ```

### Basic Operations

#### 1. Validate Pipeline Before Starting
```bash
# Run comprehensive validation
python validate_data_pipeline.py

# Check validation results
ls -la logs/pipeline_validation_*
```

#### 2. Start Pipeline
```bash
# Start with validation
python manage_pipeline.py start

# Start without validation (faster)
python manage_pipeline.py start --no-validate

# Start with custom configuration  
python manage_pipeline.py start --config config/custom_pipeline.json
```

#### 3. Monitor Pipeline
```bash
# Monitor continuously
python manage_pipeline.py monitor

# Monitor for specific duration
python manage_pipeline.py monitor --duration 60

# Get current status
python manage_pipeline.py status
```

#### 4. Stop Pipeline
```bash
# Graceful shutdown
python manage_pipeline.py stop

# Force shutdown (immediate)
python manage_pipeline.py stop --force
```

#### 5. Restart Pipeline
```bash
# Restart with validation
python manage_pipeline.py restart

# Quick restart without validation
python manage_pipeline.py restart --no-validate
```

## Advanced Operations

### Health Monitoring

#### Real-time Health Dashboard
```bash
# Start Streamlit dashboard (if available)
streamlit run pipeline_health_monitor.py
```

#### Programmatic Health Checks
```python
from pipeline_health_monitor import PipelineHealthMonitor
from pipeline_orchestrator import PipelineOrchestrator

# Create orchestrator
orchestrator = PipelineOrchestrator(symbols=['AAPL', 'GOOGL'])
await orchestrator.start()

# Create health monitor
monitor = PipelineHealthMonitor(orchestrator=orchestrator)
await monitor.start_monitoring()

# Get health status
health_status = await monitor.get_current_health_status()
print(f"Health Score: {health_status['health_score']}/100")
```

### Performance Optimization

#### Bottleneck Detection
The health monitor automatically detects bottlenecks in:
- **Ingestion Stage**: IQFeed connection issues
- **Kafka Stage**: Producer/consumer throughput issues  
- **Processing Stage**: Order book and feature calculation delays
- **Storage Stage**: ClickHouse write performance issues

#### Performance Metrics
Key metrics monitored:
- **Throughput**: Messages per second through each stage
- **Latency**: End-to-end processing time
- **Error Rate**: Percentage of failed messages
- **Resource Usage**: CPU, memory, network utilization

### Error Handling and Recovery

#### Automatic Recovery
The orchestrator implements several recovery mechanisms:

1. **Component Reconnection**: Automatic reconnection to failed services
2. **Circuit Breakers**: Prevent cascade failures
3. **Backpressure Handling**: Manage high load scenarios
4. **Graceful Degradation**: Continue operating with reduced functionality

#### Manual Recovery
```bash
# Enter maintenance mode
python manage_pipeline.py maintenance --enable

# Restart specific components (through configuration)
python manage_pipeline.py restart

# Exit maintenance mode
python manage_pipeline.py maintenance --disable
```

### Scaling Operations

#### Adding Symbols
```bash
# Add new symbols to monitoring
python manage_pipeline.py scale --symbols NVDA AMD INTC
```

#### Configuration Updates
1. Edit configuration file:
   ```json
   {
     "symbols": ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"],
     "kafka": {
       "bootstrap_servers": "localhost:9092"
     },
     "performance": {
       "startup_timeout_seconds": 60
     }
   }
   ```

2. Restart with new configuration:
   ```bash
   python manage_pipeline.py restart --config config/updated_config.json
   ```

## Production Deployment

### Pre-deployment Checklist

1. **Infrastructure Validation**
   ```bash
   # Check all services are running
   docker-compose ps
   
   # Verify service health
   docker-compose exec kafka kafka-broker-api-versions.sh --bootstrap-server localhost:9092
   docker-compose exec redis redis-cli ping
   docker-compose exec clickhouse clickhouse-client --query "SELECT 1"
   ```

2. **Pipeline Validation**
   ```bash
   # Run comprehensive validation
   python validate_data_pipeline.py
   
   # Check validation report
   cat logs/pipeline_validation_report_*.txt
   ```

3. **Configuration Review**
   ```bash
   # Backup current configuration
   python manage_pipeline.py backup
   
   # Review configuration
   cat config/pipeline_config.json
   ```

### Production Startup Procedure

1. **Start Infrastructure**
   ```bash
   cd infrastructure
   docker-compose up -d
   
   # Wait for services to be ready
   ./scripts/health-check.sh
   ```

2. **Validate System**
   ```bash
   python validate_data_pipeline.py
   ```

3. **Start Pipeline**
   ```bash
   python manage_pipeline.py start
   ```

4. **Verify Operation**
   ```bash
   # Check status
   python manage_pipeline.py status
   
   # Monitor for initial period
   python manage_pipeline.py monitor --duration 10
   ```

### Production Monitoring

#### Key Metrics to Monitor

1. **Health Score**: Should stay above 80
2. **Throughput**: Should meet minimum requirements (>100 msg/s)
3. **Latency**: End-to-end should be <500ms
4. **Error Rate**: Should be <1%
5. **Active Alerts**: Should be minimal

#### Alert Thresholds

Configure in `config/pipeline_config.json`:
```json
{
  "alerts": {
    "alert_thresholds": {
      "latency_max_ms": 1000,
      "throughput_min_msg_per_sec": 100,
      "error_rate_max_percent": 5.0,
      "health_score_min": 70
    }
  }
}
```

## Troubleshooting

### Common Issues

#### 1. Pipeline Won't Start
```bash
# Check infrastructure
docker-compose ps

# Check logs
tail -f logs/pipeline_orchestrator.log

# Run validation
python validate_data_pipeline.py
```

#### 2. Low Throughput
```bash
# Check for bottlenecks
python manage_pipeline.py status | jq '.bottlenecks'

# Monitor resource usage
python manage_pipeline.py monitor --duration 5
```

#### 3. High Error Rate
```bash
# Check error details
python manage_pipeline.py status | jq '.active_alerts'

# Review logs for specific errors
grep ERROR logs/pipeline_orchestrator.log | tail -20
```

#### 4. Component Failures
```bash
# Check component health
python manage_pipeline.py status | jq '.infrastructure_status'

# Restart specific components
docker-compose restart kafka redis clickhouse

# Restart pipeline
python manage_pipeline.py restart
```

### Log Analysis

#### Key Log Files
- `logs/pipeline_orchestrator.log`: Main orchestrator logs
- `logs/pipeline_health_monitor.log`: Health monitoring logs
- `logs/pipeline_validation.log`: Validation results
- `logs/pipeline_validation_report_*.txt`: Human-readable validation reports

#### Log Analysis Commands
```bash
# Check for errors
grep ERROR logs/*.log

# Monitor real-time logs
tail -f logs/pipeline_orchestrator.log

# Analyze performance
grep "Performance:" logs/pipeline_orchestrator.log | tail -10

# Check alert history
grep "ALERT" logs/pipeline_health_monitor.log
```

## Best Practices

### Development
1. **Always validate before deployment**
2. **Use version control for configuration**
3. **Test with realistic data volumes**
4. **Monitor resource usage during development**

### Production
1. **Regular health checks**
2. **Automated backup procedures**
3. **Alert escalation procedures**
4. **Capacity planning and scaling**
5. **Regular system updates and maintenance**

### Monitoring
1. **Set up comprehensive alerting**
2. **Monitor key business metrics**
3. **Track performance trends**
4. **Regular bottleneck analysis**

## Integration with Existing Systems

### IQFeed Integration
```python
# Configure IQFeed connection
config = {
    "iqfeed": {
        "host": "localhost",
        "port": 9200,
        "username": "your_username",
        "password": "your_password"
    }
}
```

### Kafka Integration
```python
# Configure Kafka settings
config = {
    "kafka": {
        "bootstrap_servers": "kafka1:9092,kafka2:9092",
        "compression_type": "lz4",
        "batch_size": 16384,
        "linger_ms": 10
    }
}
```

### ClickHouse Integration
```python
# Configure ClickHouse connection
config = {
    "clickhouse": {
        "host": "clickhouse-cluster",
        "port": 8123,
        "database": "market_data",
        "username": "user",
        "password": "password"
    }
}
```

## Support and Maintenance

### Regular Maintenance Tasks

1. **Weekly**:
   - Review health metrics
   - Check error rates
   - Analyze performance trends

2. **Monthly**:
   - Update configurations as needed
   - Review capacity and scaling needs
   - Update system dependencies

3. **Quarterly**:
   - Comprehensive system validation
   - Performance benchmarking
   - Disaster recovery testing

### Emergency Procedures

#### System Down
1. Check infrastructure services
2. Review recent logs for errors
3. Attempt graceful restart
4. If failed, force restart
5. Validate system after restart

#### Data Loss
1. Stop pipeline immediately
2. Assess scope of data loss
3. Restore from backups if available
4. Restart pipeline with validation
5. Monitor for data integrity

#### Performance Degradation
1. Identify bottlenecks using health monitor
2. Check resource utilization
3. Scale affected components
4. Consider maintenance mode if severe

For additional support, refer to the comprehensive test suite in `tests/integration/test_pipeline_orchestrator.py` for detailed examples of system behavior and expected outcomes.