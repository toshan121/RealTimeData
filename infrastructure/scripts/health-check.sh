#!/bin/bash

# Health check for all infrastructure services

echo "=== Infrastructure Health Check ==="
echo "$(date)"
echo

# Function to check if a container is running
check_container() {
    local container_name=$1
    if docker ps --format "table {{.Names}}" | grep -q "^${container_name}$"; then
        return 0
    else
        return 1
    fi
}

# Check Docker Compose services
echo "Docker Services Status:"
if command -v docker-compose > /dev/null 2>&1; then
    docker-compose ps
else
    echo "Warning: docker-compose not available, using docker ps"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep l2_
fi
echo

# Check Kafka
echo "Kafka Health:"
if check_container "l2_kafka"; then
    if docker exec l2_kafka kafka-broker-api-versions.sh --bootstrap-server localhost:9092 > /dev/null 2>&1; then
        echo "✓ Kafka is healthy"
        echo "  Topics:"
        docker exec l2_kafka kafka-topics.sh --list --bootstrap-server localhost:9092 2>/dev/null | sed 's/^/    /'
        
        echo "  Consumer Groups & Lag:"
        docker exec l2_kafka kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list 2>/dev/null | while read -r group; do
            if [[ -n "$group" && "$group" != *"Note:"* ]]; then
                # Get total lag for this group
                total_lag=$(docker exec l2_kafka kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group "$group" 2>/dev/null | \
                    awk 'NR>1 && $5 != "-" {sum += $5} END {print (sum ? sum : 0)}')
                
                if [[ "$total_lag" -gt 10000 ]]; then
                    echo "    🔥 $group: ${total_lag} (CRITICAL)"
                elif [[ "$total_lag" -gt 1000 ]]; then
                    echo "    ⚠️  $group: ${total_lag} (WARNING)"
                else
                    echo "    ✓ $group: ${total_lag}"
                fi
            fi
        done
    else
        echo "✗ Kafka container is running but not responding"
    fi
else
    echo "✗ Kafka container is not running"
fi
echo

# Check Redis
echo "Redis Health:"
if check_container "l2_redis"; then
    if docker exec l2_redis redis-cli ping > /dev/null 2>&1; then
        echo "✓ Redis is healthy"
        docker exec l2_redis redis-cli info server | grep redis_version | sed 's/^/  /'
    else
        echo "✗ Redis container is running but not responding"
    fi
else
    echo "✗ Redis container is not running"
fi
echo

# Check ClickHouse
echo "ClickHouse Health:"
if check_container "l2_clickhouse"; then
    if docker exec l2_clickhouse clickhouse-client --query "SELECT 1" > /dev/null 2>&1; then
        echo "✓ ClickHouse is healthy"
        echo "  Databases:"
        docker exec l2_clickhouse clickhouse-client --query "SHOW DATABASES" 2>/dev/null | grep -v "^_" | sed 's/^/    /'
    else
        echo "✗ ClickHouse container is running but not responding"
    fi
else
    echo "✗ ClickHouse container is not running"
fi
echo

# Check Zookeeper
echo "Zookeeper Health:"
if check_container "l2_zookeeper"; then
    if docker exec l2_zookeeper bash -c "echo ruok | nc localhost 2181" 2>/dev/null | grep -q imok; then
        echo "✓ Zookeeper is healthy"
    else
        echo "✗ Zookeeper container is running but not responding"
    fi
else
    echo "✗ Zookeeper container is not running"
fi
echo

# Resource usage
echo "Resource Usage:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" | grep l2_