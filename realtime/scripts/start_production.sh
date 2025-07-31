#!/bin/bash

# Hedge Fund Production System Startup Script
# Starts all components for real-time market data collection

set -e  # Exit on any error

echo "🏦 Starting Hedge Fund Production Market Data System"
echo "=================================================="

# Configuration
PROJECT_DIR="/opt/l2-system"
KAFKA_DIR="/opt/kafka"
LOG_DIR="/var/log/l2-system"
PID_DIR="/var/run/l2-system"

# Create directories
sudo mkdir -p $LOG_DIR $PID_DIR
sudo chown $(whoami) $LOG_DIR $PID_DIR

# Function to check if service is running
check_service() {
    local service_name=$1
    local port=$2
    local timeout=${3:-10}
    
    echo "🔍 Checking $service_name on port $port..."
    
    for i in $(seq 1 $timeout); do
        if nc -z localhost $port 2>/dev/null; then
            echo "✅ $service_name is running"
            return 0
        fi
        sleep 1
    done
    
    echo "❌ $service_name is not responding on port $port"
    return 1
}

# Function to start service with PID tracking
start_service() {
    local service_name=$1
    local command=$2
    local log_file="$LOG_DIR/${service_name}.log"
    local pid_file="$PID_DIR/${service_name}.pid"
    
    # Check if already running
    if [ -f "$pid_file" ] && kill -0 $(cat "$pid_file") 2>/dev/null; then
        echo "⚠️  $service_name is already running (PID: $(cat $pid_file))"
        return 0
    fi
    
    echo "🚀 Starting $service_name..."
    nohup $command > "$log_file" 2>&1 &
    echo $! > "$pid_file"
    echo "✅ $service_name started (PID: $!, log: $log_file)"
}

# Function to stop service
stop_service() {
    local service_name=$1
    local pid_file="$PID_DIR/${service_name}.pid"
    
    if [ -f "$pid_file" ] && kill -0 $(cat "$pid_file") 2>/dev/null; then
        echo "🛑 Stopping $service_name (PID: $(cat $pid_file))..."
        kill $(cat "$pid_file")
        rm -f "$pid_file"
        echo "✅ $service_name stopped"
    else
        echo "⚠️  $service_name is not running"
    fi
}

# Handle script arguments
case "${1:-start}" in
    "start")
        echo "🔧 Starting all services..."
        
        # 1. Start ClickHouse
        echo "📊 Starting ClickHouse..."
        sudo systemctl start clickhouse-server
        check_service "ClickHouse" 8123 30
        
        # 2. Start Redis
        echo "💾 Starting Redis..."
        sudo systemctl start redis-server
        check_service "Redis" 6379 10
        
        # 3. Start Kafka
        echo "📨 Starting Kafka..."
        cd $KAFKA_DIR
        start_service "kafka" "$KAFKA_DIR/bin/kafka-server-start.sh $KAFKA_DIR/config/server.properties"
        sleep 5
        check_service "Kafka" 9092 30
        
        # 4. Create Kafka topics
        echo "📝 Creating Kafka topics..."
        $KAFKA_DIR/bin/kafka-topics.sh --create --if-not-exists --topic market-ticks --bootstrap-server localhost:9092 --partitions 6 --replication-factor 1
        $KAFKA_DIR/bin/kafka-topics.sh --create --if-not-exists --topic market-l1 --bootstrap-server localhost:9092 --partitions 6 --replication-factor 1
        $KAFKA_DIR/bin/kafka-topics.sh --create --if-not-exists --topic market-l2 --bootstrap-server localhost:9092 --partitions 6 --replication-factor 1
        $KAFKA_DIR/bin/kafka-topics.sh --create --if-not-exists --topic market-metrics --bootstrap-server localhost:9092 --partitions 2 --replication-factor 1
        
        # 5. Start Python services
        cd $PROJECT_DIR
        source venv/bin/activate
        
        echo "🔍 Starting Health Monitor..."
        start_service "health-monitor" "python realtime/monitoring/health_monitor.py"
        
        echo "📊 Starting Capacity Monitor..."
        start_service "capacity-monitor" "python realtime/monitoring/capacity_monitor.py"
        
        echo "📥 Starting Market Data Capture..."
        start_service "market-data-capture" "python realtime/scripts/market_data_capture.py"
        
        echo "🎯 Starting IQFeed Client..."
        start_service "iqfeed-client" "python realtime/core/iqfeed_realtime_client.py"
        
        echo "🖥️  Starting Production Monitor UI..."
        start_service "production-ui" "streamlit run realtime/ui/production_monitor.py --server.port 8501 --server.address 0.0.0.0"
        
        # 6. Wait and verify all services
        echo "⏳ Waiting for services to initialize..."
        sleep 10
        
        echo "🔍 Verifying all services..."
        check_service "ClickHouse" 8123
        check_service "Redis" 6379  
        check_service "Kafka" 9092
        check_service "Production UI" 8501
        
        echo "✅ All services started successfully!"
        echo "📊 Production Monitor: http://localhost:8501"
        echo "🔍 Health Monitor: Check logs at $LOG_DIR/health-monitor.log"
        echo "📈 Capacity Monitor: Check logs at $LOG_DIR/capacity-monitor.log"
        ;;
        
    "stop")
        echo "🛑 Stopping all services..."
        
        # Stop Python services
        stop_service "production-ui"
        stop_service "iqfeed-client"
        stop_service "market-data-capture"
        stop_service "capacity-monitor"
        stop_service "health-monitor"
        
        # Stop Kafka
        stop_service "kafka"
        
        # Stop system services
        echo "🛑 Stopping Redis..."
        sudo systemctl stop redis-server
        
        echo "🛑 Stopping ClickHouse..."
        sudo systemctl stop clickhouse-server
        
        echo "✅ All services stopped"
        ;;
        
    "restart")
        echo "🔄 Restarting all services..."
        $0 stop
        sleep 5
        $0 start
        ;;
        
    "status")
        echo "📊 Service Status Check"
        echo "======================"
        
        # Check system services
        echo "System Services:"
        systemctl is-active clickhouse-server && echo "✅ ClickHouse: Running" || echo "❌ ClickHouse: Stopped"
        systemctl is-active redis-server && echo "✅ Redis: Running" || echo "❌ Redis: Stopped"
        
        # Check ports
        echo -e "\nPort Status:"
        check_service "ClickHouse" 8123 1 || true
        check_service "Redis" 6379 1 || true
        check_service "Kafka" 9092 1 || true
        check_service "Production UI" 8501 1 || true
        
        # Check Python services
        echo -e "\nPython Services:"
        for service in health-monitor capacity-monitor market-data-capture iqfeed-client production-ui; do
            pid_file="$PID_DIR/${service}.pid"
            if [ -f "$pid_file" ] && kill -0 $(cat "$pid_file") 2>/dev/null; then
                echo "✅ $service: Running (PID: $(cat $pid_file))"
            else
                echo "❌ $service: Stopped"
            fi
        done
        
        # Data flow check
        echo -e "\nData Flow Status:"
        if command -v redis-cli >/dev/null; then
            ticks=$(redis-cli -p 6379 get "metrics:ticks:count:last_minute" 2>/dev/null || echo "0")
            l1=$(redis-cli -p 6379 get "metrics:l1:count:last_minute" 2>/dev/null || echo "0")
            l2=$(redis-cli -p 6379 get "metrics:l2:count:last_minute" 2>/dev/null || echo "0")
            echo "📊 Last minute: $ticks ticks, $l1 L1, $l2 L2"
        fi
        ;;
        
    "logs")
        service=${2:-"all"}
        if [ "$service" = "all" ]; then
            echo "📋 All service logs:"
            for log_file in $LOG_DIR/*.log; do
                if [ -f "$log_file" ]; then
                    echo "=== $(basename $log_file) ==="
                    tail -n 5 "$log_file"
                    echo ""
                fi
            done
        else
            log_file="$LOG_DIR/${service}.log"
            if [ -f "$log_file" ]; then
                tail -f "$log_file"
            else
                echo "❌ Log file not found: $log_file"
            fi
        fi
        ;;
        
    "test")
        echo "🧪 Running system tests..."
        cd $PROJECT_DIR
        source venv/bin/activate
        
        echo "Testing infrastructure connectivity..."
        python -c "
import redis, clickhouse_connect
from kafka import KafkaProducer

# Test Redis
try:
    r = redis.Redis(host='localhost', port=6379)
    r.ping()
    print('✅ Redis: Connected')
except Exception as e:
    print(f'❌ Redis: {e}')

# Test ClickHouse
try:
    ch = clickhouse_connect.get_client(host='localhost', port=8123, database='l2_market_data')
    ch.query('SELECT 1')
    print('✅ ClickHouse: Connected')
except Exception as e:
    print(f'❌ ClickHouse: {e}')

# Test Kafka
try:
    producer = KafkaProducer(bootstrap_servers=['localhost:9092'])
    producer.close()
    print('✅ Kafka: Connected')
except Exception as e:
    print(f'❌ Kafka: {e}')
"
        
        echo "✅ System test completed"
        ;;
        
    "monitor")
        echo "📊 Opening production monitor..."
        if command -v xdg-open >/dev/null; then
            xdg-open http://localhost:8501
        elif command -v open >/dev/null; then
            open http://localhost:8501
        else
            echo "📊 Production Monitor: http://localhost:8501"
        fi
        ;;
        
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [service]|test|monitor}"
        echo ""
        echo "Commands:"
        echo "  start    - Start all production services"
        echo "  stop     - Stop all production services"
        echo "  restart  - Restart all services"
        echo "  status   - Check service status"
        echo "  logs     - View service logs (optionally specify service name)"
        echo "  test     - Test infrastructure connectivity"
        echo "  monitor  - Open production monitor in browser"
        echo ""
        echo "Services: health-monitor, capacity-monitor, market-data-capture, iqfeed-client, production-ui"
        exit 1
        ;;
esac

echo "🏦 Production system management complete"