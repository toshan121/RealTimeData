#!/bin/bash
"""
PRODUCTION SYSTEM STARTUP SCRIPT
================================

Enhanced production-ready startup script for hedge fund trading operations.
Provides robust daemon management, health monitoring, and operational control.

Features:
- Infrastructure validation and setup
- Service dependency management
- Health monitoring and alerting
- Graceful error handling and recovery
- Comprehensive logging and status reporting
- Production-ready daemon supervision

Usage:
    ./start_production_system.sh [options]
    
Options:
    --daemon       Run as daemon (detached)
    --no-ui        Skip UI components
    --config FILE  Use custom configuration file
    --debug        Enable debug logging
    --force        Force start even if already running
    --check-only   Only check prerequisites, don't start
"""

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
REALTIME_DIR="$PROJECT_ROOT/realtime"
LOGS_DIR="$REALTIME_DIR/logs"
PIDS_DIR="$REALTIME_DIR/pids"

# Default options
DAEMON_MODE=false
SKIP_UI=false
CONFIG_FILE=""
DEBUG_MODE=false
FORCE_START=false
CHECK_ONLY=false

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
    echo "[$level] $timestamp: $message" >> "$LOGS_DIR/startup.log"
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --daemon)
                DAEMON_MODE=true
                shift
                ;;
            --no-ui)
                SKIP_UI=true
                shift
                ;;
            --config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            --debug)
                DEBUG_MODE=true
                shift
                ;;
            --force)
                FORCE_START=true
                shift
                ;;
            --check-only)
                CHECK_ONLY=true
                shift
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --daemon       Run as daemon (detached)"
                echo "  --no-ui        Skip UI components"
                echo "  --config FILE  Use custom configuration file"
                echo "  --debug        Enable debug logging"
                echo "  --force        Force start even if already running"
                echo "  --check-only   Only check prerequisites, don't start"
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

# Create directories
setup_directories() {
    log "INFO" "Setting up directory structure..."
    
    local dirs=(
        "$LOGS_DIR"
        "$PIDS_DIR"
        "$PROJECT_ROOT/data/realtime_l1/raw"
        "$PROJECT_ROOT/data/realtime_l2/raw"
        "$PROJECT_ROOT/data/realtime_ticks/raw"
        "$REALTIME_DIR/logs/health_reports"
    )
    
    for dir in "${dirs[@]}"; do
        if ! mkdir -p "$dir" 2>/dev/null; then
            log "ERROR" "Failed to create directory: $dir"
            return 1
        fi
        log "DEBUG" "Created directory: $dir"
    done
    
    log "INFO" "Directory structure setup complete"
    return 0
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
        # Process not running, remove stale PID file
        rm -f "$pid_file"
        return 1
    fi
    
    return 0
}

# Check if system is already running
check_already_running() {
    local services=("data_collector" "health_monitor" "daemon_manager")
    local running_services=()
    
    for service in "${services[@]}"; do
        if is_service_running "$service"; then
            running_services+=("$service")
        fi
    done
    
    if [ ${#running_services[@]} -gt 0 ]; then
        if [ "$FORCE_START" = false ]; then
            log "ERROR" "System already running. Services: ${running_services[*]}"
            log "INFO" "Use --force to restart, or stop services first with: ./stop_production_system.sh"
            return 1
        else
            log "WARN" "Forcing restart of running services: ${running_services[*]}"
            # Stop existing services
            "$SCRIPT_DIR/stop_production_system.sh" || true
            sleep 5
        fi
    fi
    
    return 0
}

# Check prerequisites
check_prerequisites() {
    log "INFO" "Checking prerequisites..."
    
    local errors=0
    
    # Check Python
    if ! command -v python3 >/dev/null; then
        log "ERROR" "Python 3 not found"
        ((errors++))
    else
        local python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
        log "DEBUG" "Python version: $python_version"
    fi
    
    # Check required Python packages
    local required_packages=(
        "psutil"
        "redis"
        "kafka-python"
        "clickhouse-connect"
    )
    
    for package in "${required_packages[@]}"; do
        if ! python3 -c "import $package" 2>/dev/null; then
            log "ERROR" "Required Python package not found: $package"
            ((errors++))
        else
            log "DEBUG" "Package available: $package"
        fi
    done
    
    # Check infrastructure services
    log "INFO" "Checking infrastructure services..."
    
    # Check Redis
    if ! nc -z localhost 6380 2>/dev/null; then
        log "WARN" "Redis not responding on port 6380"
        log "INFO" "Attempting to start Redis..."
        if ! start_redis; then
            log "ERROR" "Failed to start Redis"
            ((errors++))
        fi
    else
        log "INFO" "Redis is running on port 6380"
    fi
    
    # Check ClickHouse
    if ! nc -z localhost 8123 2>/dev/null; then
        log "WARN" "ClickHouse not responding on port 8123"
        log "INFO" "Attempting to start ClickHouse..."
        if ! start_clickhouse; then
            log "ERROR" "Failed to start ClickHouse"
            ((errors++))
        fi
    else
        log "INFO" "ClickHouse is running on port 8123"
    fi
    
    # Check Kafka
    if ! nc -z localhost 9092 2>/dev/null; then
        log "WARN" "Kafka not responding on port 9092"
        log "INFO" "Attempting to start Kafka..."
        if ! start_kafka; then
            log "ERROR" "Failed to start Kafka"
            ((errors++))
        fi
    else
        log "INFO" "Kafka is running on port 9092"
    fi
    
    # Check IQFeed (warning only, not critical)
    if ! nc -z 127.0.0.1 9200 2>/dev/null; then
        log "WARN" "IQFeed L2 port (9200) not responding - ensure IQConnect is running"
    else
        log "INFO" "IQFeed L2 port is accessible"
    fi
    
    if [ $errors -gt 0 ]; then
        log "ERROR" "Prerequisites check failed with $errors errors"
        return 1
    fi
    
    log "INFO" "Prerequisites check passed"
    return 0
}

# Start Redis if not running
start_redis() {
    log "INFO" "Starting Redis..."
    
    # Check if Redis is installed
    if ! command -v redis-server >/dev/null; then
        log "ERROR" "Redis server not found. Please install Redis."
        return 1
    fi
    
    # Start Redis with custom config if available
    local redis_config="$PROJECT_ROOT/infrastructure/redis/redis.conf"
    if [ -f "$redis_config" ]; then
        redis-server "$redis_config" --daemonize yes --port 6380
    else
        redis-server --daemonize yes --port 6380
    fi
    
    # Wait for Redis to start
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if nc -z localhost 6380 2>/dev/null; then
            log "INFO" "Redis started successfully"
            return 0
        fi
        sleep 1
        ((attempts++))
    done
    
    log "ERROR" "Redis failed to start within 30 seconds"
    return 1
}

# Start ClickHouse if not running
start_clickhouse() {
    log "INFO" "Starting ClickHouse..."
    
    # Try Docker first
    if command -v docker >/dev/null; then
        local docker_compose_file="$PROJECT_ROOT/infrastructure/docker-compose.yml"
        if [ -f "$docker_compose_file" ]; then
            cd "$PROJECT_ROOT/infrastructure"
            docker-compose up -d clickhouse
            cd "$PROJECT_ROOT"
            
            # Wait for ClickHouse to start
            local attempts=0
            while [ $attempts -lt 60 ]; do
                if nc -z localhost 8123 2>/dev/null; then
                    log "INFO" "ClickHouse started successfully via Docker"
                    return 0
                fi
                sleep 1
                ((attempts++))
            done
        fi
    fi
    
    # Try system service
    if command -v systemctl >/dev/null; then
        if systemctl start clickhouse-server 2>/dev/null; then
            # Wait for ClickHouse to start
            local attempts=0
            while [ $attempts -lt 60 ]; do
                if nc -z localhost 8123 2>/dev/null; then
                    log "INFO" "ClickHouse started successfully via systemctl"
                    return 0
                fi
                sleep 1
                ((attempts++))
            done
        fi
    fi
    
    log "ERROR" "Failed to start ClickHouse"
    return 1
}

# Start Kafka if not running
start_kafka() {
    log "INFO" "Starting Kafka..."
    
    # Try Docker first
    if command -v docker >/dev/null; then
        local docker_compose_file="$PROJECT_ROOT/infrastructure/docker-compose.yml"
        if [ -f "$docker_compose_file" ]; then
            cd "$PROJECT_ROOT/infrastructure"
            docker-compose up -d kafka
            cd "$PROJECT_ROOT"
            
            # Wait for Kafka to start
            local attempts=0
            while [ $attempts -lt 60 ]; do
                if nc -z localhost 9092 2>/dev/null; then
                    log "INFO" "Kafka started successfully via Docker"
                    return 0
                fi
                sleep 2
                ((attempts++))
            done
        fi
    fi
    
    log "ERROR" "Failed to start Kafka"
    return 1
}

# Start production services
start_production_services() {
    log "INFO" "Starting production services..."
    
    # Change to realtime directory
    cd "$REALTIME_DIR"
    
    # Prepare daemon manager command
    local daemon_cmd="python scripts/production_daemon_manager.py"
    
    if [ "$DAEMON_MODE" = true ]; then
        daemon_cmd="$daemon_cmd run"
    else
        daemon_cmd="$daemon_cmd start"
    fi
    
    # Add configuration if specified
    if [ -n "$CONFIG_FILE" ]; then
        daemon_cmd="$daemon_cmd --config $CONFIG_FILE"
    fi
    
    log "INFO" "Executing: $daemon_cmd"
    
    if [ "$DAEMON_MODE" = true ]; then
        # Run in background as daemon
        nohup $daemon_cmd > "$LOGS_DIR/daemon_manager.log" 2>&1 &
        local daemon_pid=$!
        
        # Save daemon manager PID
        echo "$daemon_pid" > "$PIDS_DIR/daemon_manager.pid"
        
        log "INFO" "Daemon manager started with PID: $daemon_pid"
        
        # Wait briefly and check if it's still running
        sleep 5
        if ! kill -0 "$daemon_pid" 2>/dev/null; then
            log "ERROR" "Daemon manager failed to start"
            return 1
        fi
        
        log "INFO" "Production services are starting in background"
        log "INFO" "Check status with: $SCRIPT_DIR/check_system_status.sh"
        log "INFO" "View logs: tail -f $LOGS_DIR/daemon_manager.log"
    else
        # Run in foreground
        exec $daemon_cmd
    fi
    
    return 0
}

# Main execution
main() {
    # Setup
    setup_directories || exit 1
    
    # Parse arguments
    parse_args "$@"
    
    log "INFO" "Starting Hedge Fund Production System"
    log "INFO" "Script: $0"
    log "INFO" "Project Root: $PROJECT_ROOT"
    log "INFO" "Daemon Mode: $DAEMON_MODE"
    log "INFO" "Skip UI: $SKIP_UI"
    log "INFO" "Debug Mode: $DEBUG_MODE"
    log "INFO" "Force Start: $FORCE_START"
    log "INFO" "Check Only: $CHECK_ONLY"
    
    # Check if already running
    if ! check_already_running; then
        exit 1
    fi
    
    # Check prerequisites
    if ! check_prerequisites; then
        log "ERROR" "Prerequisites check failed"
        exit 1
    fi
    
    if [ "$CHECK_ONLY" = true ]; then
        log "INFO" "Prerequisites check complete. System ready to start."
        exit 0
    fi
    
    # Start production services
    if ! start_production_services; then
        log "ERROR" "Failed to start production services"
        exit 1
    fi
    
    if [ "$DAEMON_MODE" = true ]; then
        log "INFO" "Production system started successfully in daemon mode"
        log "INFO" "Use '$SCRIPT_DIR/stop_production_system.sh' to stop"
    else
        log "INFO" "Production system started successfully"
    fi
}

# Handle script termination
trap 'log "INFO" "Script interrupted"; exit 130' INT
trap 'log "INFO" "Script terminated"; exit 143' TERM

# Execute main function
main "$@"