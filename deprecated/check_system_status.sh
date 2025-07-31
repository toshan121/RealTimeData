#!/bin/bash
"""
SYSTEM STATUS CHECKER
====================

Comprehensive system status monitoring for hedge fund trading operations.
Provides real-time status reporting, health metrics, and operational diagnostics.

Features:
- Service status monitoring
- Infrastructure health checks
- Resource usage reporting
- Data flow validation
- Performance metrics
- Alert condition detection

Usage:
    ./check_system_status.sh [options]
    
Options:
    --watch        Continuous monitoring mode (refresh every 30s)
    --json         Output in JSON format
    --brief        Brief status summary only
    --services     Check specific services only (comma-separated)
    --infrastructure  Check infrastructure only
    --alerts       Show only alert conditions
    --export FILE  Export status report to file
"""

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
REALTIME_DIR="$PROJECT_ROOT/realtime"
LOGS_DIR="$REALTIME_DIR/logs"
PIDS_DIR="$REALTIME_DIR/pids"

# Default options
WATCH_MODE=false
JSON_OUTPUT=false
BRIEF_MODE=false
SPECIFIC_SERVICES=""
INFRASTRUCTURE_ONLY=false
ALERTS_ONLY=false
EXPORT_FILE=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --watch)
                WATCH_MODE=true
                shift
                ;;
            --json)
                JSON_OUTPUT=true
                shift
                ;;
            --brief)
                BRIEF_MODE=true
                shift
                ;;
            --services)
                SPECIFIC_SERVICES="$2"
                shift 2
                ;;
            --infrastructure)
                INFRASTRUCTURE_ONLY=true
                shift
                ;;
            --alerts)
                ALERTS_ONLY=true
                shift
                ;;
            --export)
                EXPORT_FILE="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --watch           Continuous monitoring mode"
                echo "  --json            Output in JSON format"
                echo "  --brief           Brief status summary only"
                echo "  --services LIST   Check specific services only"
                echo "  --infrastructure  Check infrastructure only"
                echo "  --alerts          Show only alert conditions"
                echo "  --export FILE     Export status report to file"
                echo "  --help            Show this help message"
                exit 0
                ;;
            *)
                echo "Unknown option: $1" >&2
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

# Get service PID
get_service_pid() {
    local service_name="$1"
    local pid_file="$PIDS_DIR/${service_name}.pid"
    
    if [ -f "$pid_file" ]; then
        cat "$pid_file" 2>/dev/null
    fi
}

# Get process info
get_process_info() {
    local pid="$1"
    
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        echo "N/A,N/A,N/A,N/A"
        return
    fi
    
    # Get process stats using ps
    local ps_output=$(ps -p "$pid" -o pid,pcpu,pmem,etime --no-headers 2>/dev/null || echo "$pid 0.0 0.0 00:00")
    echo "$ps_output" | awk '{print $2","$3","$4}'
}

# Check port connectivity
check_port() {
    local host="$1"
    local port="$2"
    local timeout="${3:-5}"
    
    if timeout "$timeout" bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Get Redis info
get_redis_info() {
    if command -v redis-cli >/dev/null && check_port localhost 6380 2; then
        local info=$(redis-cli -p 6380 info stats 2>/dev/null | grep -E "^(total_commands_processed|used_memory_human|connected_clients):" || echo "")
        if [ -n "$info" ]; then
            echo "$info" | awk -F: '{
                if ($1 == "total_commands_processed") commands = $2
                if ($1 == "used_memory_human") memory = $2  
                if ($1 == "connected_clients") clients = $2
            }
            END { print commands","memory","clients }'
        else
            echo "0,0B,0"
        fi
    else
        echo "disconnected,N/A,N/A"
    fi
}

# Get ClickHouse info
get_clickhouse_info() {
    if check_port localhost 8123 2; then
        # Try to get basic info via HTTP
        local response=$(curl -s "http://localhost:8123/?query=SELECT%20version()" 2>/dev/null || echo "")
        if [ -n "$response" ]; then
            echo "connected,$response"
        else
            echo "connected,unknown_version"
        fi
    else
        echo "disconnected,N/A"
    fi
}

# Get Kafka info
get_kafka_info() {
    if check_port localhost 9092 2; then
        echo "connected"
    else
        echo "disconnected"
    fi
}

# Get data flow metrics
get_data_flow_metrics() {
    local data_dir="$PROJECT_ROOT/data"
    
    if [ ! -d "$data_dir" ]; then
        echo "0,0,0,0B"
        return
    fi
    
    # Count files created in last hour
    local l1_files=$(find "$data_dir" -path "*/realtime_l1/*" -name "*.jsonl" -mmin -60 2>/dev/null | wc -l)
    local l2_files=$(find "$data_dir" -path "*/realtime_l2/*" -name "*.jsonl" -mmin -60 2>/dev/null | wc -l)
    local tick_files=$(find "$data_dir" -path "*/realtime_ticks/*" -name "*.jsonl" -mmin -60 2>/dev/null | wc -l)
    
    # Get total data size
    local data_size=$(du -sh "$data_dir" 2>/dev/null | cut -f1 || echo "0B")
    
    echo "$l1_files,$l2_files,$tick_files,$data_size"
}

# Get system metrics
get_system_metrics() {
    # CPU usage
    local cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//' || echo "0.0")
    
    # Memory usage
    local memory_info=$(free -m | grep '^Mem:')
    local memory_total=$(echo "$memory_info" | awk '{print $2}')
    local memory_used=$(echo "$memory_info" | awk '{print $3}')
    local memory_percent=$(awk "BEGIN {printf \"%.1f\", ($memory_used/$memory_total)*100}")
    
    # Disk usage for root
    local disk_usage=$(df -h / | tail -1 | awk '{print $5}' | sed 's/%//')
    
    # Load average
    local load_avg=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//')
    
    echo "$cpu_usage,$memory_percent,$disk_usage,$load_avg"
}

# Check service status
check_service_status() {
    local service_name="$1"
    local status="stopped"
    local pid=""
    local cpu="0.0"
    local memory="0.0" 
    local uptime="N/A"
    
    if is_service_running "$service_name"; then
        status="running"
        pid=$(get_service_pid "$service_name")
        
        if [ -n "$pid" ]; then
            local process_info=$(get_process_info "$pid")
            cpu=$(echo "$process_info" | cut -d',' -f1)
            memory=$(echo "$process_info" | cut -d',' -f2)
            uptime=$(echo "$process_info" | cut -d',' -f3)
        fi
    fi
    
    echo "$status,$pid,$cpu,$memory,$uptime"
}

# Generate JSON output
generate_json_output() {
    local timestamp=$(date -Iseconds)
    
    cat << EOF
{
  "timestamp": "$timestamp",
  "system": {
EOF

    # System metrics
    local sys_metrics=$(get_system_metrics)
    local cpu=$(echo "$sys_metrics" | cut -d',' -f1)
    local memory=$(echo "$sys_metrics" | cut -d',' -f2)
    local disk=$(echo "$sys_metrics" | cut -d',' -f3)
    local load=$(echo "$sys_metrics" | cut -d',' -f4)
    
    cat << EOF
    "cpu_percent": $cpu,
    "memory_percent": $memory,
    "disk_percent": $disk,
    "load_average": $load
  },
  "infrastructure": {
EOF

    # Infrastructure status
    local redis_info=$(get_redis_info)
    local clickhouse_info=$(get_clickhouse_info)
    local kafka_info=$(get_kafka_info)
    
    cat << EOF
    "redis": {
      "status": "$(echo "$redis_info" | cut -d',' -f1)",
      "memory": "$(echo "$redis_info" | cut -d',' -f2)",
      "clients": "$(echo "$redis_info" | cut -d',' -f3)"
    },
    "clickhouse": {
      "status": "$(echo "$clickhouse_info" | cut -d',' -f1)",
      "version": "$(echo "$clickhouse_info" | cut -d',' -f2)"
    },
    "kafka": {
      "status": "$kafka_info"
    }
  },
  "services": {
EOF

    # Service status
    local services=("daemon_manager" "health_monitor" "data_collector" "capacity_monitor" "network_monitor" "latency_monitor")
    local first=true
    
    for service in "${services[@]}"; do
        if [ "$first" = false ]; then
            echo ","
        fi
        first=false
        
        local service_info=$(check_service_status "$service")
        local status=$(echo "$service_info" | cut -d',' -f1)
        local pid=$(echo "$service_info" | cut -d',' -f2)
        local cpu=$(echo "$service_info" | cut -d',' -f3)
        local memory=$(echo "$service_info" | cut -d',' -f4)
        local uptime=$(echo "$service_info" | cut -d',' -f5)
        
        cat << EOF
    "$service": {
      "status": "$status",
      "pid": "$pid",
      "cpu_percent": $cpu,
      "memory_percent": $memory,
      "uptime": "$uptime"
    }
EOF
    done
    
    echo "  },"
    
    # Data flow metrics
    local data_metrics=$(get_data_flow_metrics)
    local l1_files=$(echo "$data_metrics" | cut -d',' -f1)
    local l2_files=$(echo "$data_metrics" | cut -d',' -f2)
    local tick_files=$(echo "$data_metrics" | cut -d',' -f3)
    local data_size=$(echo "$data_metrics" | cut -d',' -f4)
    
    cat << EOF
  "data_flow": {
    "l1_files_last_hour": $l1_files,
    "l2_files_last_hour": $l2_files,
    "tick_files_last_hour": $tick_files,
    "total_data_size": "$data_size"
  }
}
EOF
}

# Generate human-readable output
generate_human_output() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    if [ "$BRIEF_MODE" = true ]; then
        # Brief mode
        echo "Hedge Fund Trading System Status - $timestamp"
        echo "================================================"
        
        # Quick service check
        local running_services=0
        local total_services=0
        local services=("daemon_manager" "health_monitor" "data_collector")
        
        for service in "${services[@]}"; do
            ((total_services++))
            if is_service_running "$service"; then
                ((running_services++))
            fi
        done
        
        local health_percent=$((running_services * 100 / total_services))
        
        if [ $health_percent -eq 100 ]; then
            echo -e "${GREEN}✓ System Status: HEALTHY${NC} ($running_services/$total_services services running)"
        elif [ $health_percent -gt 50 ]; then
            echo -e "${YELLOW}⚠ System Status: WARNING${NC} ($running_services/$total_services services running)"
        else
            echo -e "${RED}✗ System Status: CRITICAL${NC} ($running_services/$total_services services running)"
        fi
        
        # Quick resource check
        local sys_metrics=$(get_system_metrics)
        local cpu=$(echo "$sys_metrics" | cut -d',' -f1)
        local memory=$(echo "$sys_metrics" | cut -d',' -f2)
        local disk=$(echo "$sys_metrics" | cut -d',' -f3)
        
        echo "Resources: CPU ${cpu}%, Memory ${memory}%, Disk ${disk}%"
        
        return
    fi
    
    # Full status display
    echo "==============================================================================="
    echo "                    HEDGE FUND TRADING SYSTEM STATUS"
    echo "==============================================================================="
    echo "Timestamp: $timestamp"
    echo ""
    
    # System metrics
    echo -e "${CYAN}SYSTEM RESOURCES:${NC}"
    echo "-------------------------------------------------------------------------------"
    local sys_metrics=$(get_system_metrics)
    local cpu=$(echo "$sys_metrics" | cut -d',' -f1)
    local memory=$(echo "$sys_metrics" | cut -d',' -f2)
    local disk=$(echo "$sys_metrics" | cut -d',' -f3)
    local load=$(echo "$sys_metrics" | cut -d',' -f4)
    
    printf "%-15s %-10s %-15s %-10s\n" "CPU Usage" "Memory" "Disk Usage" "Load Avg"
    printf "%-15s %-10s %-15s %-10s\n" "${cpu}%" "${memory}%" "${disk}%" "$load"
    echo ""
    
    # Infrastructure status
    if [ "$INFRASTRUCTURE_ONLY" = false ]; then
        echo -e "${CYAN}INFRASTRUCTURE:${NC}"
        echo "-------------------------------------------------------------------------------"
        printf "%-15s %-15s %-30s\n" "Service" "Status" "Details"
        echo "-------------------------------------------------------------------------------"
        
        # Redis
        local redis_info=$(get_redis_info)
        local redis_status=$(echo "$redis_info" | cut -d',' -f1)
        local redis_memory=$(echo "$redis_info" | cut -d',' -f2)
        local redis_clients=$(echo "$redis_info" | cut -d',' -f3)
        
        if [ "$redis_status" = "disconnected" ]; then
            printf "%-15s ${RED}%-15s${NC} %-30s\n" "Redis" "DISCONNECTED" "Port 6380 not responding"
        else
            printf "%-15s ${GREEN}%-15s${NC} %-30s\n" "Redis" "CONNECTED" "Memory: $redis_memory, Clients: $redis_clients"
        fi
        
        # ClickHouse
        local clickhouse_info=$(get_clickhouse_info)
        local clickhouse_status=$(echo "$clickhouse_info" | cut -d',' -f1)
        local clickhouse_version=$(echo "$clickhouse_info" | cut -d',' -f2)
        
        if [ "$clickhouse_status" = "disconnected" ]; then
            printf "%-15s ${RED}%-15s${NC} %-30s\n" "ClickHouse" "DISCONNECTED" "Port 8123 not responding"
        else
            printf "%-15s ${GREEN}%-15s${NC} %-30s\n" "ClickHouse" "CONNECTED" "Version: $clickhouse_version"
        fi
        
        # Kafka
        local kafka_status=$(get_kafka_info)
        if [ "$kafka_status" = "disconnected" ]; then
            printf "%-15s ${RED}%-15s${NC} %-30s\n" "Kafka" "DISCONNECTED" "Port 9092 not responding"
        else
            printf "%-15s ${GREEN}%-15s${NC} %-30s\n" "Kafka" "CONNECTED" "Port 9092 responding"
        fi
        
        # IQFeed
        if check_port 127.0.0.1 9200 2; then
            printf "%-15s ${GREEN}%-15s${NC} %-30s\n" "IQFeed" "CONNECTED" "L2 port responding"
        else
            printf "%-15s ${YELLOW}%-15s${NC} %-30s\n" "IQFeed" "DISCONNECTED" "L2 port not responding"
        fi
        
        echo ""
    fi
    
    # Service status
    echo -e "${CYAN}SERVICES:${NC}"
    echo "-------------------------------------------------------------------------------"
    printf "%-20s %-12s %-8s %-8s %-8s %-12s\n" "Service" "Status" "PID" "CPU%" "Mem%" "Uptime"
    echo "-------------------------------------------------------------------------------"
    
    local services=("daemon_manager" "health_monitor" "data_collector" "capacity_monitor" "network_monitor" "latency_monitor")
    
    if [ -n "$SPECIFIC_SERVICES" ]; then
        IFS=',' read -ra services <<< "$SPECIFIC_SERVICES"
    fi
    
    for service in "${services[@]}"; do
        service=$(echo "$service" | xargs)  # Trim whitespace
        local service_info=$(check_service_status "$service")
        local status=$(echo "$service_info" | cut -d',' -f1)
        local pid=$(echo "$service_info" | cut -d',' -f2)
        local cpu=$(echo "$service_info" | cut -d',' -f3)
        local memory=$(echo "$service_info" | cut -d',' -f4)
        local uptime=$(echo "$service_info" | cut -d',' -f5)
        
        if [ "$status" = "running" ]; then
            printf "%-20s ${GREEN}%-12s${NC} %-8s %-8s %-8s %-12s\n" "$service" "RUNNING" "$pid" "$cpu" "$memory" "$uptime"
        else
            printf "%-20s ${RED}%-12s${NC} %-8s %-8s %-8s %-12s\n" "$service" "STOPPED" "N/A" "N/A" "N/A" "N/A"
        fi
    done
    
    echo ""
    
    # Data flow metrics
    echo -e "${CYAN}DATA FLOW (Last Hour):${NC}"
    echo "-------------------------------------------------------------------------------"
    local data_metrics=$(get_data_flow_metrics)
    local l1_files=$(echo "$data_metrics" | cut -d',' -f1)
    local l2_files=$(echo "$data_metrics" | cut -d',' -f2)
    local tick_files=$(echo "$data_metrics" | cut -d',' -f3)
    local data_size=$(echo "$data_metrics" | cut -d',' -f4)
    
    printf "%-15s %-15s %-15s %-15s\n" "L1 Files" "L2 Files" "Tick Files" "Total Size"
    printf "%-15s %-15s %-15s %-15s\n" "$l1_files" "$l2_files" "$tick_files" "$data_size"
    echo ""
    
    # Health status summary
    echo -e "${CYAN}HEALTH SUMMARY:${NC}"
    echo "-------------------------------------------------------------------------------"
    
    # Count running services
    local running_services=0
    local total_services=${#services[@]}
    
    for service in "${services[@]}"; do
        if is_service_running "$service"; then
            ((running_services++))
        fi
    done
    
    local health_percent=$((running_services * 100 / total_services))
    
    if [ $health_percent -eq 100 ]; then
        echo -e "${GREEN}✓ Overall Status: HEALTHY${NC}"
        echo "  All services are running normally"
    elif [ $health_percent -gt 70 ]; then
        echo -e "${YELLOW}⚠ Overall Status: WARNING${NC}"
        echo "  Some services are not running ($running_services/$total_services active)"
    else
        echo -e "${RED}✗ Overall Status: CRITICAL${NC}"
        echo "  Multiple services are down ($running_services/$total_services active)"
    fi
    
    # Resource alerts
    if (( $(echo "$cpu > 80" | bc -l) )); then
        echo -e "${RED}⚠ HIGH CPU USAGE: ${cpu}%${NC}"
    fi
    
    if (( $(echo "$memory > 80" | bc -l) )); then
        echo -e "${RED}⚠ HIGH MEMORY USAGE: ${memory}%${NC}"
    fi
    
    if (( $(echo "$disk > 85" | bc -l) )); then
        echo -e "${RED}⚠ HIGH DISK USAGE: ${disk}%${NC}"
    fi
    
    echo "==============================================================================="
}

# Main execution
main() {
    parse_args "$@"
    
    if [ "$WATCH_MODE" = true ]; then
        # Continuous monitoring mode
        echo "Starting continuous monitoring mode (Press Ctrl+C to stop)..."
        echo ""
        
        while true; do
            clear
            if [ "$JSON_OUTPUT" = true ]; then
                generate_json_output
            else
                generate_human_output
            fi
            
            echo ""
            echo "Next update in 30 seconds... (Press Ctrl+C to stop)"
            sleep 30
        done
    else
        # Single check
        if [ "$JSON_OUTPUT" = true ]; then
            local output=$(generate_json_output)
        else
            local output=$(generate_human_output)
        fi
        
        echo "$output"
        
        # Export to file if requested
        if [ -n "$EXPORT_FILE" ]; then
            echo "$output" > "$EXPORT_FILE"
            echo ""
            echo "Status exported to: $EXPORT_FILE"
        fi
    fi
}

# Handle interruption
trap 'echo -e "\n${YELLOW}Monitoring stopped${NC}"; exit 0' INT

# Execute main function
main "$@"