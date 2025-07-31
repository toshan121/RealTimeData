#!/bin/bash
"""
PRODUCTION SYSTEM SHUTDOWN SCRIPT
=================================

Enhanced production-ready shutdown script for hedge fund trading operations.
Provides graceful service termination, resource cleanup, and status reporting.

Features:
- Graceful service shutdown with timeouts
- Resource cleanup and validation
- Service dependency management
- Comprehensive logging and status reporting
- Emergency force-kill capabilities
- Data integrity verification

Usage:
    ./stop_production_system.sh [options]
    
Options:
    --force        Force kill services if graceful shutdown fails
    --timeout SEC  Shutdown timeout in seconds (default: 60)
    --no-cleanup   Skip cleanup procedures
    --debug        Enable debug logging
    --services     Only stop specific services (comma-separated)
"""

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
REALTIME_DIR="$PROJECT_ROOT/realtime"
LOGS_DIR="$REALTIME_DIR/logs"
PIDS_DIR="$REALTIME_DIR/pids"

# Default options
FORCE_KILL=false
SHUTDOWN_TIMEOUT=60
SKIP_CLEANUP=false
DEBUG_MODE=false
SPECIFIC_SERVICES=""

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
        "ERROR")
            echo -e "${RED}[ERROR]${NC} $timestamp: $message" >&2
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} $timestamp: $message"
            ;;
        "INFO")
            echo -e "${GREEN}[INFO]${NC} $timestamp: $message"
            ;;
        "DEBUG")
            if [ "$DEBUG_MODE" = true ]; then
                echo -e "${BLUE}[DEBUG]${NC} $timestamp: $message"
            fi
            ;;
    esac
    
    # Also log to file
    echo "[$level] $timestamp: $message" >> "$LOGS_DIR/shutdown.log"
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                FORCE_KILL=true
                shift
                ;;
            --timeout)
                SHUTDOWN_TIMEOUT="$2"
                shift 2
                ;;
            --no-cleanup)
                SKIP_CLEANUP=true
                shift
                ;;
            --debug)
                DEBUG_MODE=true
                shift
                ;;
            --services)
                SPECIFIC_SERVICES="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --force        Force kill services if graceful shutdown fails"
                echo "  --timeout SEC  Shutdown timeout in seconds (default: 60)"
                echo "  --no-cleanup   Skip cleanup procedures"
                echo "  --debug        Enable debug logging"
                echo "  --services     Only stop specific services (comma-separated)"
                echo "  --help         Show this help message"
                exit 0
                ;;
            *)
                log "ERROR" "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

# Check if service is running
is_service_running() {
    local service_name="$1"
    local pid_file="$PIDS_DIR/${service_name}.pid"
    
    if [ ! -f "$pid_file" ]; then
        return 1
    fi
    
    local pid=$(cat "$pid_file" 2>/dev/null)
    if [ -z "$pid" ]; then
        return 1
    fi
    
    if ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi
    
    return 0
}

# Get PID of service
get_service_pid() {
    local service_name="$1"
    local pid_file="$PIDS_DIR/${service_name}.pid"
    
    if [ -f "$pid_file" ]; then
        cat "$pid_file" 2>/dev/null
    fi
}

# Stop a service gracefully
stop_service() {
    local service_name="$1"
    local timeout="${2:-$SHUTDOWN_TIMEOUT}"
    
    log "INFO" "Stopping service: $service_name"
    
    local pid=$(get_service_pid "$service_name")
    if [ -z "$pid" ]; then
        log "WARN" "No PID found for service: $service_name"
        return 0
    fi
    
    if ! kill -0 "$pid" 2>/dev/null; then
        log "WARN" "Service $service_name (PID: $pid) is not running"
        rm -f "$PIDS_DIR/${service_name}.pid"
        return 0
    fi
    
    log "INFO" "Sending SIGTERM to $service_name (PID: $pid)"
    
    # Send SIGTERM for graceful shutdown
    if ! kill -TERM "$pid" 2>/dev/null; then
        log "WARN" "Failed to send SIGTERM to $service_name (PID: $pid)"
        return 1
    fi
    
    # Wait for graceful shutdown
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            log "INFO" "Service $service_name stopped gracefully"
            rm -f "$PIDS_DIR/${service_name}.pid"
            return 0
        fi
        
        sleep 1
        ((elapsed++))
        
        # Progress indicator every 10 seconds
        if [ $((elapsed % 10)) -eq 0 ]; then
            log "DEBUG" "Waiting for $service_name shutdown... ${elapsed}s elapsed"
        fi
    done
    
    # Graceful shutdown timeout
    log "WARN" "Service $service_name did not stop gracefully within ${timeout}s"
    
    if [ "$FORCE_KILL" = true ]; then
        log "INFO" "Force killing $service_name (PID: $pid)"
        
        # Try SIGKILL
        if kill -KILL "$pid" 2>/dev/null; then
            # Wait briefly for process to die
            sleep 2
            if ! kill -0 "$pid" 2>/dev/null; then
                log "INFO" "Service $service_name force killed successfully"
                rm -f "$PIDS_DIR/${service_name}.pid"
                return 0
            else
                log "ERROR" "Failed to force kill $service_name (PID: $pid)"
                return 1
            fi
        else
            log "ERROR" "Failed to send SIGKILL to $service_name (PID: $pid)"
            return 1
        fi
    else
        log "ERROR" "Service $service_name did not stop. Use --force to force kill."
        return 1
    fi
}

# Stop all production services
stop_production_services() {
    log "INFO" "Stopping production services..."
    
    # Service shutdown order (reverse of startup order)
    local services=()
    
    if [ -n "$SPECIFIC_SERVICES" ]; then
        # Split comma-separated services
        IFS=',' read -ra services <<< "$SPECIFIC_SERVICES"
    else
        # Default shutdown order
        services=(
            "latency_monitor"
            "network_monitor"
            "capacity_monitor"
            "data_collector"
            "health_monitor"
            "daemon_manager"
        )
    fi
    
    local failed_services=()
    
    # Stop each service
    for service in "${services[@]}"; do
        service=$(echo "$service" | xargs)  # Trim whitespace
        
        if is_service_running "$service"; then
            if ! stop_service "$service"; then
                failed_services+=("$service")
            fi
        else
            log "DEBUG" "Service $service is not running"
        fi
    done
    
    # Report results
    if [ ${#failed_services[@]} -eq 0 ]; then
        log "INFO" "All services stopped successfully"
        return 0
    else
        log "ERROR" "Failed to stop services: ${failed_services[*]}"
        return 1
    fi
}

# Stop additional processes
stop_additional_processes() {
    log "INFO" "Stopping additional processes..."
    
    # Find processes by name patterns
    local process_patterns=(
        "production_data_collector"
        "production_health_monitor"
        "start_production_data_collection"
    )
    
    for pattern in "${process_patterns[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        
        if [ -n "$pids" ]; then
            log "INFO" "Found processes matching '$pattern': $pids"
            
            for pid in $pids; do
                log "INFO" "Stopping process $pid ($pattern)"
                
                if kill -TERM "$pid" 2>/dev/null; then
                    # Wait for graceful shutdown
                    local elapsed=0
                    while [ $elapsed -lt 30 ]; do
                        if ! kill -0 "$pid" 2>/dev/null; then
                            log "INFO" "Process $pid stopped gracefully"
                            break
                        fi
                        sleep 1
                        ((elapsed++))
                    done
                    
                    # Force kill if still running
                    if kill -0 "$pid" 2>/dev/null; then
                        if [ "$FORCE_KILL" = true ]; then
                            log "WARN" "Force killing process $pid"
                            kill -KILL "$pid" 2>/dev/null || true
                        else
                            log "WARN" "Process $pid still running"
                        fi
                    fi
                fi
            done
        fi
    done
}

# Clean up resources
cleanup_resources() {
    if [ "$SKIP_CLEANUP" = true ]; then
        log "INFO" "Skipping cleanup as requested"
        return 0
    fi
    
    log "INFO" "Cleaning up resources..."
    
    # Clean up PID files
    if [ -d "$PIDS_DIR" ]; then
        log "DEBUG" "Cleaning up PID files..."
        find "$PIDS_DIR" -name "*.pid" -type f | while read -r pid_file; do
            local pid=$(cat "$pid_file" 2>/dev/null || echo "")
            if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
                log "DEBUG" "Removing stale PID file: $pid_file"
                rm -f "$pid_file"
            fi
        done
    fi
    
    # Clean up temporary files
    local temp_patterns=(
        "/tmp/iqfeed_*"
        "/tmp/market_data_*"
        "/tmp/.production_*"
    )
    
    for pattern in "${temp_patterns[@]}"; do
        if compgen -G "$pattern" > /dev/null 2>&1; then
            log "DEBUG" "Cleaning up temporary files: $pattern"
            rm -f $pattern 2>/dev/null || true
        fi
    done
    
    # Clean up shared memory segments (if any)
    if command -v ipcs >/dev/null; then
        local shmids=$(ipcs -m | grep "$(whoami)" | awk '{print $2}' 2>/dev/null || true)
        if [ -n "$shmids" ]; then
            log "DEBUG" "Cleaning up shared memory segments..."
            for shmid in $shmids; do
                ipcrm -m "$shmid" 2>/dev/null || true
            done
        fi
    fi
    
    log "INFO" "Resource cleanup complete"
}

# Verify shutdown
verify_shutdown() {
    log "INFO" "Verifying shutdown..."
    
    local running_processes=()
    
    # Check for remaining processes
    local process_patterns=(
        "production_data_collector"
        "production_health_monitor"
        "daemon_manager"
    )
    
    for pattern in "${process_patterns[@]}"; do
        local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            running_processes+=("$pattern:$pids")
        fi
    done
    
    # Check PID files
    if [ -d "$PIDS_DIR" ]; then
        local remaining_pids=$(find "$PIDS_DIR" -name "*.pid" -type f 2>/dev/null | wc -l)
        if [ "$remaining_pids" -gt 0 ]; then
            log "WARN" "Found $remaining_pids remaining PID files"
        fi
    fi
    
    if [ ${#running_processes[@]} -eq 0 ]; then
        log "INFO" "Shutdown verification passed - no processes running"
        return 0
    else
        log "WARN" "Shutdown verification failed - processes still running:"
        for proc in "${running_processes[@]}"; do
            log "WARN" "  $proc"
        done
        return 1
    fi
}

# Generate shutdown report
generate_shutdown_report() {
    log "INFO" "Generating shutdown report..."
    
    local report_file="$LOGS_DIR/shutdown_report_$(date +%Y%m%d_%H%M%S).txt"
    
    cat > "$report_file" << EOF
PRODUCTION SYSTEM SHUTDOWN REPORT
=================================

Timestamp: $(date)
Script: $0
Options: Force=$FORCE_KILL, Timeout=$SHUTDOWN_TIMEOUT, Cleanup=$SKIP_CLEANUP

FINAL STATUS:
$(verify_shutdown && echo "SUCCESS: All services stopped cleanly" || echo "WARNING: Some issues detected")

DATA STATISTICS:
EOF
    
    # Add data file counts
    if [ -d "$PROJECT_ROOT/data" ]; then
        echo "Data Files Created:" >> "$report_file"
        find "$PROJECT_ROOT/data" -name "*.jsonl" -type f | head -20 | while read -r file; do
            local size=$(du -h "$file" 2>/dev/null | cut -f1)
            echo "  $file ($size)" >> "$report_file"
        done
        
        local total_files=$(find "$PROJECT_ROOT/data" -name "*.jsonl" -type f | wc -l)
        echo "  Total data files: $total_files" >> "$report_file"
    fi
    
    # Add log summary
    echo "" >> "$report_file"
    echo "LOG SUMMARY:" >> "$report_file"
    if [ -f "$LOGS_DIR/daemon_manager.log" ]; then
        echo "Last 10 lines from daemon manager log:" >> "$report_file"
        tail -10 "$LOGS_DIR/daemon_manager.log" >> "$report_file" 2>/dev/null || true
    fi
    
    log "INFO" "Shutdown report saved to: $report_file"
}

# Show final statistics
show_final_statistics() {
    log "INFO" "Final system statistics:"
    
    # Count data files
    if [ -d "$PROJECT_ROOT/data" ]; then
        local l1_files=$(find "$PROJECT_ROOT/data" -path "*/realtime_l1/*" -name "*.jsonl" | wc -l)
        local l2_files=$(find "$PROJECT_ROOT/data" -path "*/realtime_l2/*" -name "*.jsonl" | wc -l)
        local tick_files=$(find "$PROJECT_ROOT/data" -path "*/realtime_ticks/*" -name "*.jsonl" | wc -l)
        
        log "INFO" "Data files created:"
        log "INFO" "  L1 files: $l1_files"
        log "INFO" "  L2 files: $l2_files"
        log "INFO" "  Tick files: $tick_files"
        log "INFO" "  Total files: $((l1_files + l2_files + tick_files))"
        
        # Show disk usage
        local data_size=$(du -sh "$PROJECT_ROOT/data" 2>/dev/null | cut -f1)
        log "INFO" "  Total data size: $data_size"
    fi
    
    # Show uptime from latest log
    if [ -f "$LOGS_DIR/daemon_manager.log" ]; then
        local uptime_line=$(grep -i "uptime:" "$LOGS_DIR/daemon_manager.log" | tail -1 || echo "")
        if [ -n "$uptime_line" ]; then
            log "INFO" "System $uptime_line"
        fi
    fi
}

# Main execution
main() {
    # Parse arguments
    parse_args "$@"
    
    # Ensure log directory exists
    mkdir -p "$LOGS_DIR"
    
    log "INFO" "Stopping Hedge Fund Production System"
    log "INFO" "Script: $0"
    log "INFO" "Force Kill: $FORCE_KILL"
    log "INFO" "Timeout: ${SHUTDOWN_TIMEOUT}s"
    log "INFO" "Skip Cleanup: $SKIP_CLEANUP"
    log "INFO" "Debug Mode: $DEBUG_MODE"
    log "INFO" "Specific Services: ${SPECIFIC_SERVICES:-'all'}"
    
    # Check if anything is running
    local services_running=false
    for service in "daemon_manager" "data_collector" "health_monitor"; do
        if is_service_running "$service"; then
            services_running=true
            break
        fi
    done
    
    if [ "$services_running" = false ]; then
        log "INFO" "No production services appear to be running"
        
        # Still check for additional processes
        stop_additional_processes
        
        if [ "$SKIP_CLEANUP" = false ]; then
            cleanup_resources
        fi
        
        log "INFO" "System already stopped"
        exit 0
    fi
    
    # Stop production services
    local stop_success=true
    if ! stop_production_services; then
        stop_success=false
    fi
    
    # Stop additional processes
    stop_additional_processes
    
    # Clean up resources
    if [ "$SKIP_CLEANUP" = false ]; then
        cleanup_resources
    fi
    
    # Verify shutdown
    if verify_shutdown; then
        log "INFO" "System shutdown verification passed"
    else
        log "WARN" "System shutdown verification failed"
        stop_success=false
    fi
    
    # Show statistics
    show_final_statistics
    
    # Generate report
    generate_shutdown_report
    
    if [ "$stop_success" = true ]; then
        log "INFO" "Production system stopped successfully"
        exit 0
    else
        log "ERROR" "Production system shutdown completed with warnings"
        exit 1
    fi
}

# Handle script termination
trap 'log "INFO" "Shutdown script interrupted"; exit 130' INT
trap 'log "INFO" "Shutdown script terminated"; exit 143' TERM

# Execute main function
main "$@"