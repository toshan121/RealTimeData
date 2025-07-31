#!/bin/bash
# STOP BACKGROUND DATA COLLECTION SCRIPT

set -e

echo "🛑 STOPPING HEDGE FUND DATA COLLECTION SYSTEM"
echo "=============================================="

# Check if PID file exists
if [ -f "logs/data_collection.pid" ]; then
    PID=$(cat logs/data_collection.pid)
    echo "📋 Found PID file: $PID"
    
    # Check if process is running
    if ps -p $PID > /dev/null; then
        echo "🔄 Stopping process $PID..."
        kill -TERM $PID
        
        # Wait for graceful shutdown
        sleep 5
        
        # Force kill if still running
        if ps -p $PID > /dev/null; then
            echo "⚡ Force killing process $PID..."
            kill -KILL $PID
        fi
        
        echo "✅ Process $PID stopped"
    else
        echo "⚠️  Process $PID not running"
    fi
    
    # Remove PID file
    rm -f logs/data_collection.pid
else
    echo "📋 No PID file found, searching for process..."
fi

# Kill any remaining processes
PIDS=$(pgrep -f "start_production_data_collection.py" || true)
if [ -n "$PIDS" ]; then
    echo "🔄 Killing remaining processes: $PIDS"
    echo $PIDS | xargs kill -TERM
    sleep 2
    
    # Force kill if needed
    REMAINING=$(pgrep -f "start_production_data_collection.py" || true)
    if [ -n "$REMAINING" ]; then
        echo "⚡ Force killing: $REMAINING"
        echo $REMAINING | xargs kill -KILL
    fi
fi

echo "✅ All data collection processes stopped"

# Show final statistics
echo ""
echo "📊 FINAL STATUS:"
echo "================"

# Count data files
if [ -d "data" ]; then
    L2_FILES=$(find data -name "*.jsonl" -path "*/realtime_l2/*" | wc -l)
    L1_FILES=$(find data -name "*.jsonl" -path "*/realtime_l1/*" | wc -l)
    TICK_FILES=$(find data -name "*.jsonl" -path "*/realtime_ticks/*" | wc -l)
    
    echo "📁 Data files created:"
    echo "   L2 files: $L2_FILES"
    echo "   L1 files: $L1_FILES" 
    echo "   Tick files: $TICK_FILES"
    
    # Show latest log
    LATEST_LOG=$(ls -t logs/production_*.log 2>/dev/null | head -1 || echo "")
    if [ -n "$LATEST_LOG" ]; then
        echo ""
        echo "📋 Latest log entries:"
        tail -10 "$LATEST_LOG"
    fi
else
    echo "📁 No data directory found"
fi

echo ""
echo "💡 To restart: ./start_background.sh"
echo "🔧 To check infrastructure: cd infrastructure && docker-compose ps"