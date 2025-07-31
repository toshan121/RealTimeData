#!/bin/bash

# Start L2 Market Data Infrastructure
# This script handles the complete startup sequence with proper timing

set -e

echo "=== L2 Market Data Infrastructure Startup ==="
echo "$(date)"
echo

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo "✗ Docker is not running. Please start Docker and try again."
        exit 1
    fi
    echo "✓ Docker is running"
}

# Function to wait for service health
wait_for_service() {
    local service_name=$1
    local max_attempts=${2:-30}
    local attempt=1
    
    echo "Waiting for $service_name to be healthy..."
    
    while [ $attempt -le $max_attempts ]; do
        if docker-compose ps $service_name | grep -q "healthy\|Up"; then
            echo "✓ $service_name is ready after $attempt attempts"
            return 0
        fi
        
        echo "  Attempt $attempt/$max_attempts - $service_name not ready yet, waiting 10 seconds..."
        sleep 10
        attempt=$((attempt + 1))
    done
    
    echo "✗ $service_name failed to become ready after $max_attempts attempts"
    return 1
}

# Step 1: Check prerequisites
echo "Step 1: Checking prerequisites..."
check_docker

# Check for port conflicts
echo "Checking for port conflicts..."
for port in 2181 6380 8080 8123 9000 9092; do
    if netstat -tln | grep -q ":$port "; then
        echo "⚠ Warning: Port $port appears to be in use"
    fi
done

# Step 2: Start infrastructure services
echo
echo "Step 2: Starting infrastructure services..."
docker-compose up -d

# Step 3: Wait for services to be healthy
echo
echo "Step 3: Waiting for services to be healthy..."

# Wait for Zookeeper first
if ! wait_for_service zookeeper 20; then
    echo "Failed to start Zookeeper. Check logs: docker logs l2_zookeeper"
    exit 1
fi

# Wait for Kafka
if ! wait_for_service kafka 30; then
    echo "Failed to start Kafka. Check logs: docker logs l2_kafka"
    exit 1
fi

# Wait for Redis and ClickHouse in parallel
wait_for_service redis 15 &
redis_pid=$!

wait_for_service clickhouse 30 &
clickhouse_pid=$!

# Wait for both to complete
wait $redis_pid
redis_status=$?

wait $clickhouse_pid  
clickhouse_status=$?

if [ $redis_status -ne 0 ]; then
    echo "Failed to start Redis. Check logs: docker logs l2_redis"
    exit 1
fi

if [ $clickhouse_status -ne 0 ]; then
    echo "Failed to start ClickHouse. Check logs: docker logs l2_clickhouse"
    exit 1
fi

# Step 4: Create Kafka topics
echo
echo "Step 4: Creating Kafka topics..."
if ! ./scripts/create-topics.sh; then
    echo "Warning: Failed to create some Kafka topics. They may already exist."
fi

# Step 5: Final health check
echo
echo "Step 5: Performing final health check..."
if ! ./scripts/health-check.sh; then
    echo "Warning: Some services may not be fully healthy. Check the output above."
fi

echo
echo "=== Infrastructure Startup Complete ==="
echo "Services are available at:"
echo "  - Kafka UI: http://localhost:8080"
echo "  - ClickHouse: http://localhost:8123/play"
echo "  - Redis: localhost:6380"
echo "  - Kafka: localhost:9092"
echo
echo "To stop all services: docker-compose down"
echo "To view logs: docker-compose logs -f [service_name]"
echo "To check health: ./scripts/health-check.sh"