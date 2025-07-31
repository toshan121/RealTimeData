# Market Hours Aware Alerting System

## Overview

A minimal alerting system that follows the ultra-simple principle: **"Send alerts during market hours only."**

This system prevents alert spam during weekends, holidays, and after-hours while ensuring critical trading system alerts are delivered when the market is open.

## Core Components

### 1. Market Hours Checker (`market_hours.py`)
- **Purpose**: Determine if US equity markets are open
- **Market Hours**: 9:30 AM - 4:00 PM Eastern Time, weekdays only
- **Holidays**: Hardcoded list of 2025 US market holidays
- **Timezone**: Simple US Eastern Time handling (no complex multi-timezone support)

### 2. Alert Notifications (`alert_notifications.py`)
- **Purpose**: Deliver alerts via simple methods
- **File Logging**: Always enabled, logs all alerts to `logs/market_alerts.log`
- **Email Notifications**: Optional, only for CRITICAL/URGENT alerts during market hours
- **No Complex Routing**: Single email address, basic SMTP

### 3. Market-Aware Alert Manager (`alert_manager.py`)
- **Purpose**: Integrate market hours checking with existing alert system
- **Modified**: Enhanced existing `RedisAlertManager` to check market hours
- **Alert Suppression**: Alerts logged but not delivered when market is closed
- **Batch Processing**: Handles multiple alerts efficiently

## Key Features

### ✅ What This System Does (Minimal Requirements)
- Knows when US market is open (9:30 AM - 4:00 PM ET weekdays)
- Only sends alerts during market hours
- Basic alert types (system, data, error)
- Simple delivery method (log file + optional email)
- Handles market holidays (basic hardcoded list)

### ❌ What This System Does NOT Do (Anti-Over-Engineering)
- Complex multi-timezone support
- Sophisticated notification channels (SMS, Slack, etc.)
- Advanced alert routing and escalation
- Real-time holiday calendar integration
- Complex alert deduplication systems
- Advanced scheduling algorithms

## Installation & Configuration

### 1. Dependencies
```bash
pip install pytz  # Only external dependency for timezone handling
```

### 2. Environment Variables (Optional Email)
```bash
export ALERT_SMTP_SERVER="smtp.gmail.com"
export ALERT_SMTP_PORT="587"
export ALERT_SMTP_USERNAME="your-email@gmail.com"
export ALERT_SMTP_PASSWORD="your-app-password"
export ALERT_EMAIL_TO="alerts@yourcompany.com"
```

### 3. Log Directory
The system creates alerts logs in `/home/tcr1n15/PycharmProjects/RealTimeData/logs/market_alerts.log`

## Usage Examples

### Basic Market Hours Check
```python
from ui.monitor.market_hours import is_market_open, get_market_status

# Check if market is currently open
if is_market_open():
    print("Market is open - send alerts")
else:
    print("Market is closed - suppress alerts")

# Get detailed status
status = get_market_status()
print(f"Market open: {status['is_open']}")
print(f"Reason if closed: {status.get('reason_closed')}")
```

### Send Market-Aware Alert
```python
from ui.monitor.alert_notifications import send_market_alert

# This will only deliver via email if market is open AND alert is critical
success = send_market_alert('CRITICAL', 'iqfeed', 'IQFeed connection lost')
```

### Use with Existing Alert Manager
```python
from ui.monitor.alert_manager import get_alert_manager

alert_manager = get_alert_manager()

# This automatically checks market hours before sending notifications
alerts = alert_manager.generate_and_store_alerts()

# Get dashboard data with market context
dashboard_data = alert_manager.get_market_aware_dashboard_data()
print(f"Alerts enabled: {dashboard_data['market_status']['alerts_enabled']}")
```

## Testing

### Run Tests
```bash
cd /home/tcr1n15/PycharmProjects/RealTimeData
python -m pytest tests/test_market_hours_alerting.py -v
```

### Run Demo
```bash
cd /home/tcr1n15/PycharmProjects/RealTimeData
python ui/monitor/market_hours_demo.py
```

## System Integration

### With Existing RedisAlertManager
The existing alert system has been enhanced with market hours awareness:

1. **Alert Generation**: Still generates all alerts as before
2. **Alert Storage**: All alerts stored in Redis (unchanged)
3. **Alert Delivery**: NEW - Only delivers notifications during market hours
4. **Dashboard**: NEW - Shows market status and alert suppression info

### Backward Compatibility
- All existing alert functionality preserved
- Existing API endpoints unchanged
- Only notification delivery behavior modified

## Market Hours & Holidays

### Trading Hours
- **Open**: 9:30 AM Eastern Time
- **Close**: 4:00 PM Eastern Time
- **Days**: Monday through Friday only

### 2025 Market Holidays (Hardcoded)
- New Year's Day: January 1
- MLK Day: January 20
- Presidents Day: February 17
- Good Friday: April 18
- Memorial Day: May 26
- Juneteenth: June 19
- Independence Day: July 4
- Labor Day: September 1
- Thanksgiving: November 27
- Christmas: December 25

### Holiday Handling
- If holiday falls on weekend, no special handling needed
- Simple date-based checking (no "observed" holiday logic)
- For future years, update the hardcoded list in `market_hours.py`

## File Structure

```
ui/monitor/
├── market_hours.py              # Core market hours checking
├── alert_notifications.py      # Simple notification delivery
├── alert_manager.py            # Enhanced existing alert manager
├── market_hours_demo.py        # Demo script
└── MARKET_HOURS_ALERTING_README.md

tests/
└── test_market_hours_alerting.py  # Comprehensive tests

logs/
└── market_alerts.log              # Alert log file (created automatically)
```

## Troubleshooting

### Alerts Not Being Sent
1. Check if market is open: `python -c "from ui.monitor.market_hours import get_market_status; print(get_market_status())"`
2. Check log file: `tail -f logs/market_alerts.log`
3. Test notification system: `python ui/monitor/market_hours_demo.py`

### Email Not Working
1. Verify environment variables are set
2. Check SMTP credentials and server settings
3. Test with demo: alerts are still logged even if email fails

### Time Zone Issues
1. System uses US Eastern Time only
2. Automatically handles daylight saving time transitions
3. For other timezones, UTC times are converted to Eastern

## Philosophy: Anti-Over-Engineering

This system was built with the principle of doing exactly what was asked and nothing more:

**Requirement**: "Send alerts during market hours only"

**Implementation**: 
- ✅ Simple market hours check
- ✅ Basic holiday list
- ✅ Alert suppression when closed
- ✅ File logging always works
- ✅ Optional email for critical alerts

**Avoided Over-Engineering**:
- ❌ Complex timezone libraries
- ❌ Multiple notification channels
- ❌ Advanced scheduling systems
- ❌ Real-time holiday APIs
- ❌ Sophisticated routing logic

The result is a system that is:
- Easy to understand and maintain
- Reliable (fewer moving parts)
- Fast (minimal complexity)
- Testable (simple logic paths)
- Deployable (minimal dependencies)

## Future Enhancements (If Needed)

If additional features are truly needed:

1. **Add SMS notifications**: Extend `AlertNotificationManager`
2. **Support multiple timezones**: Enhance `MarketHoursChecker`
3. **Dynamic holiday calendar**: Replace hardcoded holidays
4. **Advanced escalation**: Add time-based escalation rules

But remember: each addition increases complexity. Only add what is genuinely required.