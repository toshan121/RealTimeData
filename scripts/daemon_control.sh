#!/bin/bash
# PRODUCTION DAEMON CONTROL SCRIPT
# =================================
#
# Comprehensive daemon control for hedge fund trading operations
# with signal-based management and operational monitoring.
#
# Features:
# - Start/stop/restart all daemons
# - Signal-based status dumps and config reloads
# - Health monitoring and alerting
# - Process supervision and recovery
# - Logging and audit trails
#
# Usage:
#   ./daemon_control.sh start          # Start all daemons
#   ./daemon_control.sh stop           # Stop all daemons
#   ./daemon_control.sh restart        # Restart all daemons
#   ./daemon_control.sh status         # Show status
#   ./daemon_control.sh status-dump    # Generate detailed status dump
#   ./daemon_control.sh reload-config  # Reload configuration
#   ./daemon_control.sh health-check   # Run health check
#   ./daemon_control.sh monitor        # Start monitoring mode

set -euo pipefail

# Configuration
PROJECT_ROOT="/home/tcr1n15/PycharmProjects/RealTimeData"
DAEMON_SCRIPT="$PROJECT_ROOT/realtime/scripts/production_daemon_manager.py"
PID_DIR="$PROJECT_ROOT/realtime/pids"
LOG_DIR="$PROJECT_ROOT/realtime/logs"
LOCK_DIR="$PROJECT_ROOT/realtime/locks"

# Daemon process names and their PID files
declare -A DAEMON_PIDS=(
    ["daemon_manager"]="$PID_DIR/production_daemon_manager.pid"
    ["health_monitor"]="$PID_DIR/health_monitor.pid"
    ["data_collector"]="$PID_DIR/data_collector.pid"
    ["capacity_monitor"]="$PID_DIR/capacity_monitor.pid"
    ["network_monitor"]="$PID_DIR/network_monitor.pid"
    ["latency_monitor"]="$PID_DIR/latency_monitor.pid"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        INFO)  echo -e "${GREEN}[INFO]${NC}  $timestamp - $message" ;;
        WARN)  echo -e "${YELLOW}[WARN]${NC}  $timestamp - $message" ;;
        ERROR) echo -e "${RED}[ERROR]${NC} $timestamp - $message" ;;
        DEBUG) echo -e "${BLUE}[DEBUG]${NC} $timestamp - $message" ;;
        *)     echo "$timestamp - $message" ;;
    esac
    
    # Also log to file
    echo "[$level] $timestamp - $message" >> "$LOG_DIR/daemon_control.log"
}

# Check if process is running
is_process_running() {
    local pid_file="$1"
    
    if [[ ! -f "$pid_file" ]]; then
        return 1
    fi
    
    local pid=$(cat "$pid_file" 2>/dev/null || echo "")
    if [[ -z "$pid" ]]; then
        return 1
    fi
    
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        # Clean up stale PID file
        rm -f "$pid_file"
        return 1
    fi
}

# Get process PID from file
get_process_pid() {
    local pid_file="$1"
    
    if [[ -f "$pid_file" ]]; then
        cat "$pid_file" 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# Send signal to daemon
send_signal_to_daemon() {
    local daemon_name="$1"
    local signal_name="$2"
    local pid_file="${DAEMON_PIDS[$daemon_name]}"
    
    if ! is_process_running "$pid_file"; then
        log ERROR "Daemon $daemon_name is not running"
        return 1
    fi
    
    local pid=$(get_process_pid "$pid_file")
    if [[ -z "$pid" ]]; then
        log ERROR "Could not get PID for daemon $daemon_name"
        return 1
    fi
    
    log INFO "Sending $signal_name to $daemon_name (PID: $pid)"
    
    if kill -s "$signal_name" "$pid" 2>/dev/null; then
        log INFO "Signal $signal_name sent successfully to $daemon_name"
        return 0
    else
        log ERROR "Failed to send signal $signal_name to $daemon_name"
        return 1
    fi
}

# Start all daemons
start_daemons() {
    log INFO "Starting hedge fund production daemons..."
    
    # Create necessary directories
    mkdir -p "$PID_DIR" "$LOG_DIR" "$LOCK_DIR"
    
    # Check if already running
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        log WARN "Production daemon manager is already running"
        return 1
    fi
    
    # Start production daemon manager
    log INFO "Starting production daemon manager..."
    cd "$PROJECT_ROOT"
    
    python "$DAEMON_SCRIPT" run > "$LOG_DIR/daemon_manager_console.log" 2>&1 &
    local daemon_pid=$!
    
    # Save PID
    echo "$daemon_pid" > "${DAEMON_PIDS[daemon_manager]}"
    
    # Wait a moment for startup
    sleep 3
    
    # Verify startup
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        log INFO "Production daemon manager started successfully (PID: $daemon_pid)"
        
        # Wait for services to start
        log INFO "Waiting for services to initialize..."
        sleep 10
        
        # Check service status
        get_daemon_status
        
        return 0
    else
        log ERROR "Failed to start production daemon manager"
        return 1
    fi
}

# Stop all daemons
stop_daemons() {
    log INFO "Stopping hedge fund production daemons..."
    
    # Send SIGTERM to daemon manager for graceful shutdown
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        send_signal_to_daemon "daemon_manager" "TERM"
        
        # Wait for graceful shutdown
        local wait_count=0
        while is_process_running "${DAEMON_PIDS[daemon_manager]}" && [[ $wait_count -lt 30 ]]; do
            sleep 1
            ((wait_count++))
        done
        
        if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
            log WARN "Daemon manager did not stop gracefully, forcing kill"
            local pid=$(get_process_pid "${DAEMON_PIDS[daemon_manager]}")
            if [[ -n "$pid" ]]; then
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        
        # Clean up PID files
        for daemon_name in "${!DAEMON_PIDS[@]}"; do
            rm -f "${DAEMON_PIDS[$daemon_name]}"
        done
        
        log INFO "All daemons stopped"
    else
        log INFO "Daemon manager is not running"
    fi
}

# Restart all daemons
restart_daemons() {
    log INFO "Restarting hedge fund production daemons..."
    stop_daemons
    sleep 2
    start_daemons
}

# Get daemon status
get_daemon_status() {
    log INFO "Checking daemon status..."
    
    echo "=================================="
    echo "HEDGE FUND DAEMON STATUS"
    echo "=================================="
    echo "Timestamp: $(date)"
    echo ""
    
    # Check main daemon manager
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        local pid=$(get_process_pid "${DAEMON_PIDS[daemon_manager]}")
        local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo "Unknown")
        echo -e "${GREEN}✓${NC} Daemon Manager: RUNNING (PID: $pid, Uptime: $uptime)"
        
        # Get detailed status from daemon manager
        if command -v python3 &> /dev/null; then
            echo ""
            echo "Detailed Service Status:"
            echo "------------------------"
            python3 "$DAEMON_SCRIPT" status 2>/dev/null || echo "Could not retrieve detailed status"
        fi
    else
        echo -e "${RED}✗${NC} Daemon Manager: STOPPED"
    fi
    
    echo ""
    echo "Individual Service Status:"
    echo "-------------------------"
    
    # Check individual services
    for daemon_name in "${!DAEMON_PIDS[@]}"; do
        if [[ "$daemon_name" == "daemon_manager" ]]; then
            continue
        fi
        
        if is_process_running "${DAEMON_PIDS[$daemon_name]}"; then
            local pid=$(get_process_pid "${DAEMON_PIDS[$daemon_name]}")
            local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo "Unknown")
            echo -e "${GREEN}✓${NC} $daemon_name: RUNNING (PID: $pid, Uptime: $uptime)"
        else
            echo -e "${RED}✗${NC} $daemon_name: STOPPED"
        fi
    done
    
    echo "=================================="
}

# Generate detailed status dump
generate_status_dump() {
    log INFO "Generating detailed status dump..."
    
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        send_signal_to_daemon "daemon_manager" "USR1"
        
        # Also send USR1 to individual services for their status dumps
        for daemon_name in "${!DAEMON_PIDS[@]}"; do
            if [[ "$daemon_name" != "daemon_manager" ]] && is_process_running "${DAEMON_PIDS[$daemon_name]}"; then
                send_signal_to_daemon "$daemon_name" "USR1"
            fi
        done
        
        log INFO "Status dump signals sent. Check log files for detailed reports."
        
        # Show recent status files
        echo ""
        echo "Recent Status Reports:"
        echo "---------------------"
        find "$LOG_DIR" -name "status_report_*.json" -mtime -1 -exec ls -la {} \; 2>/dev/null || echo "No recent status reports found"
    else
        log ERROR "Cannot generate status dump - daemon manager is not running"
        return 1
    fi
}

# Reload configuration
reload_configuration() {
    log INFO "Reloading configuration for all daemons..."
    
    if is_process_running "${DAEMON_PIDS[daemon_manager]}"; then
        send_signal_to_daemon "daemon_manager" "HUP"
        
        # Also send HUP to individual services
        for daemon_name in "${!DAEMON_PIDS[@]}"; do
            if [[ "$daemon_name" != "daemon_manager" ]] && is_process_running "${DAEMON_PIDS[$daemon_name]}"; then
                send_signal_to_daemon "$daemon_name" "HUP"
            fi
        done
        
        log INFO "Configuration reload signals sent"
    else
        log ERROR "Cannot reload configuration - daemon manager is not running"
        return 1
    fi
}

# Run health check
run_health_check() {
    log INFO "Running comprehensive health check..."
    
    local issues=0
    
    echo "=================================="
    echo "HEDGE FUND SYSTEM HEALTH CHECK"
    echo "=================================="
    echo "Timestamp: $(date)"
    echo ""
    
    # Check daemon processes
    echo "Process Health:"
    echo "---------------"
    for daemon_name in "${!DAEMON_PIDS[@]}"; do
        if is_process_running "${DAEMON_PIDS[$daemon_name]}"; then
            echo -e "${GREEN}✓${NC} $daemon_name: Running"
        else
            echo -e "${RED}✗${NC} $daemon_name: Stopped"
            ((issues++))
        fi
    done
    
    # Check disk space
    echo ""
    echo "Disk Space:"
    echo "-----------"
    local disk_usage=$(df -h "$PROJECT_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
    if [[ $disk_usage -lt 90 ]]; then
        echo -e "${GREEN}✓${NC} Disk usage: ${disk_usage}% (OK)"
    else
        echo -e "${RED}✗${NC} Disk usage: ${disk_usage}% (Critical)"
        ((issues++))
    fi
    
    # Check memory usage
    echo ""
    echo "Memory Usage:"
    echo "-------------"
    local mem_usage=$(free | awk 'NR==2{printf "%.1f", $3*100/$2}')
    if (( $(echo "$mem_usage < 90" | bc -l) )); then
        echo -e "${GREEN}✓${NC} Memory usage: ${mem_usage}% (OK)"
    else
        echo -e "${RED}✗${NC} Memory usage: ${mem_usage}% (High)"
        ((issues++))
    fi
    
    # Check log files
    echo ""
    echo "Log Files:"
    echo "----------"
    if [[ -d "$LOG_DIR" ]]; then
        local log_count=$(find "$LOG_DIR" -name "*.log" -mtime -1 | wc -l)
        echo -e "${GREEN}✓${NC} Active log files: $log_count"
        
        # Check for recent errors
        local error_count=$(find "$LOG_DIR" -name "*.log" -mtime -1 -exec grep -l "ERROR" {} \; 2>/dev/null | wc -l)
        if [[ $error_count -eq 0 ]]; then
            echo -e "${GREEN}✓${NC} No recent errors in logs"
        else
            echo -e "${YELLOW}⚠${NC} Recent errors found in $error_count log files"
        fi
    else
        echo -e "${RED}✗${NC} Log directory not found"
        ((issues++))
    fi
    
    # Summary
    echo ""
    echo "Health Check Summary:"
    echo "--------------------"
    if [[ $issues -eq 0 ]]; then
        echo -e "${GREEN}✓ System is healthy (0 issues)${NC}"
    else
        echo -e "${RED}✗ System has $issues issues requiring attention${NC}"
    fi
    
    echo "=================================="
    
    return $issues
}

# Monitor mode - continuous monitoring
monitor_mode() {
    log INFO "Entering monitoring mode (Ctrl+C to exit)..."
    
    trap 'log INFO "Monitoring stopped"; exit 0' INT TERM
    
    while true; do
        clear
        echo "CONTINUOUS MONITORING - $(date)"
        echo "Press Ctrl+C to exit"
        echo ""
        
        get_daemon_status
        
        echo ""
        echo "Next update in 30 seconds..."
        
        sleep 30
    done
}

# Main script logic
main() {
    local action="${1:-}"
    
    if [[ -z "$action" ]]; then
        echo "Usage: $0 {start|stop|restart|status|status-dump|reload-config|health-check|monitor}"
        echo ""
        echo "Commands:"
        echo "  start         Start all daemons"
        echo "  stop          Stop all daemons"
        echo "  restart       Restart all daemons"
        echo "  status        Show current status"
        echo "  status-dump   Generate detailed status dump"
        echo "  reload-config Reload configuration"
        echo "  health-check  Run comprehensive health check"
        echo "  monitor       Enter continuous monitoring mode"
        exit 1
    fi
    
    # Ensure directories exist
    mkdir -p "$PID_DIR" "$LOG_DIR" "$LOCK_DIR"
    
    case "$action" in
        start)
            start_daemons
            ;;
        stop)
            stop_daemons
            ;;
        restart)
            restart_daemons
            ;;
        status)
            get_daemon_status
            ;;
        status-dump)
            generate_status_dump
            ;;
        reload-config)
            reload_configuration
            ;;
        health-check)
            run_health_check
            ;;
        monitor)
            monitor_mode
            ;;
        *)
            log ERROR "Unknown action: $action"
            echo "Valid actions: start, stop, restart, status, status-dump, reload-config, health-check, monitor"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"