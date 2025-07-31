#!/bin/bash

# Stop L2 Market Data Infrastructure
# This script handles graceful shutdown of all services

echo "=== L2 Market Data Infrastructure Shutdown ==="
echo "$(date)"
echo

# Check if services are running
echo "Checking running services..."
docker-compose ps

echo
echo "Stopping all services gracefully..."

# Stop services in reverse dependency order
echo "Stopping Kafka UI..."
docker-compose stop kafka-ui

echo "Stopping Kafka..."
docker-compose stop kafka

echo "Stopping Redis and ClickHouse..."
docker-compose stop redis clickhouse

echo "Stopping Zookeeper..."
docker-compose stop zookeeper

echo
echo "Removing containers..."
docker-compose down

echo
echo "=== Infrastructure Shutdown Complete ==="
echo
echo "Data is preserved in Docker volumes:"
echo "  - kafka_data"
echo "  - redis_data" 
echo "  - clickhouse_data"
echo "  - zookeeper_data"
echo "  - zookeeper_logs"
echo
echo "To completely remove all data: docker-compose down -v"
echo "To restart: ./scripts/start-infrastructure.sh"