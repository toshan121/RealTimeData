#!/bin/bash
# Health check script for IQFeed container

echo "IQFeed Container Health Check"
echo "============================"

# Check container status
echo -n "Container Status: "
if docker ps | grep -q iqfeed; then
    echo "✓ Running"
    
    # Get container health
    HEALTH=$(docker inspect --format='{{.State.Health.Status}}' iqfeed 2>/dev/null)
    echo "Health Status: $HEALTH"
    
    # Show resource usage
    echo ""
    echo "Resource Usage:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" iqfeed
    
    # Check port bindings
    echo ""
    echo "Port Bindings:"
    docker port iqfeed
    
    # Recent logs
    echo ""
    echo "Recent Logs (last 10 lines):"
    docker logs --tail 10 iqfeed 2>&1 | grep -E "(Connected|Error|Warning)"
    
else
    echo "✗ Not Running"
    echo ""
    echo "To start: cd iqfeed-docker && ./start-iqfeed.sh"
fi

echo ""
echo "Network Connectivity Test:"
python3 test-iqfeed-connection.py | grep -E "(localhost|PASSED|FAILED)"