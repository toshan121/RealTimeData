#!/bin/bash
# BACKGROUND PRODUCTION DATA COLLECTION SCRIPT
# 🏦 HEDGE FUND L2/L1/TICK DATA COLLECTION 🏦

set -e

# Parse command line arguments
HEADLESS=false
SHOW_UI=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --headless)
            HEADLESS=true
            SHOW_UI=false
            shift
            ;;
        --ui)
            SHOW_UI=true
            HEADLESS=false
            shift
            ;;
        --help)
            echo "Usage: $0 [--headless|--ui]"
            echo "Options:"
            echo "  --headless    Run without UI (production mode)"
            echo "  --ui         Run with UI (default, development mode)"
            echo "  --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [ "$HEADLESS" = true ]; then
    echo "🏦 STARTING HEDGE FUND DATA COLLECTION SYSTEM (HEADLESS) 🏦"
else
    echo "🏦 STARTING HEDGE FUND DATA COLLECTION SYSTEM (WITH UI) 🏦"
fi
echo "==============================================="

# Check if already running
if pgrep -f "start_production_data_collection.py" > /dev/null; then
    echo "❌ Data collection already running!"
    echo "To stop: pkill -f start_production_data_collection.py"
    exit 1
fi

# Create logs directory
mkdir -p logs

# Start infrastructure if not running
echo "🔧 Checking infrastructure..."
cd infrastructure
if ! docker-compose ps | grep -q "Up"; then
    echo "🚀 Starting Docker infrastructure..."
    docker-compose up -d
    echo "⏳ Waiting for services to start..."
    sleep 15
else
    echo "✅ Infrastructure already running"
fi
cd ..

# Check IQConnect is running
if ! pgrep -f "IQConnect" > /dev/null; then
    echo "⚠️  WARNING: IQConnect.exe may not be running!"
    echo "   Make sure IQFeed client is connected before starting"
fi

# Start data collection in background
if [ "$HEADLESS" = true ]; then
    echo "🚀 Starting data collection in headless mode..."
    nohup python realtime/start_production_data_collection.py --headless > logs/production_$(date +%Y%m%d_%H%M%S).log 2>&1 &
else
    echo "🚀 Starting data collection with UI..."
    nohup python realtime/start_production_data_collection.py --ui > logs/production_$(date +%Y%m%d_%H%M%S).log 2>&1 &
fi

# Get PID
PID=$!
echo "✅ Data collection started with PID: $PID"

# Save PID for easy stopping
echo $PID > logs/data_collection.pid

echo ""
echo "📊 SYSTEM STATUS:"
echo "=================="
echo "📁 Data location: data/"
echo "📋 Log file: logs/production_$(date +%Y%m%d_%H%M%S).log"
echo "🔢 Process ID: $PID (saved to logs/data_collection.pid)"
echo ""
echo "🔧 MANAGEMENT COMMANDS:"
echo "======================="
echo "View logs:     tail -f logs/production_*.log"
echo "Check status:  ps aux | grep start_production_data_collection"
echo "Stop system:   ./stop_background.sh"
echo "Kill process:  kill $PID"
echo ""
echo "🎯 MONITORING:"
echo "=============="
echo "ClickHouse UI: http://localhost:8123"
echo "Kafka UI:      http://localhost:8080"
echo "Redis CLI:     redis-cli -h localhost -p 6380"
echo ""
echo "💰 COLLECTING MONEY-MAKING DATA! 💰"
echo "System is now running in background..."

# Wait a moment and check if process started successfully
sleep 3
if ps -p $PID > /dev/null; then
    echo "✅ Process $PID confirmed running"
else
    echo "❌ Process may have failed - check logs!"
    exit 1
fi