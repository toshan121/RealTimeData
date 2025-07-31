#!/bin/bash
# Start IQFeed Docker container with LAN accessibility

echo "Starting IQFeed Docker container..."
echo "Credentials: User=523093, Product=IQFEED_DIAGNOSTICS"
echo ""

# Check if docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker first."
    exit 1
fi

# Stop existing container if running
if docker ps -a | grep -q iqfeed; then
    echo "Stopping existing IQFeed container..."
    docker-compose down
fi

# Start IQFeed
echo "Starting IQFeed container..."
docker-compose up -d

# Wait for container to be healthy
echo ""
echo "Waiting for IQFeed to be ready..."
for i in {1..30}; do
    if docker inspect --format='{{.State.Health.Status}}' iqfeed 2>/dev/null | grep -q healthy; then
        echo "✓ IQFeed is healthy and ready!"
        break
    fi
    echo -n "."
    sleep 10
done

echo ""
echo "Container status:"
docker ps --filter name=iqfeed

echo ""
echo "IQFeed Ports (accessible from LAN):"
echo "  Admin:    0.0.0.0:5009"
echo "  Level 1:  0.0.0.0:9100"
echo "  Level 2:  0.0.0.0:9200"
echo "  History:  0.0.0.0:9300"
echo "  News:     0.0.0.0:9400"
echo "  HTTP API: 0.0.0.0:8088"
echo "  VNC:      0.0.0.0:5901"

echo ""
echo "To view logs: docker-compose logs -f iqfeed"
echo "To stop: docker-compose down"