#!/bin/bash
#
# Start Kafka Streaming System with Historical Data
#

echo "Starting Kafka Streaming System..."
echo "================================="

# Check if Docker services are running
echo "1. Checking Docker services..."
if ! docker ps | grep -q kafka; then
    echo "   Starting Kafka..."
    cd ../infrastructure
    docker-compose up -d kafka zookeeper redis
    cd ../streaming
    sleep 10
else
    echo "   Kafka is running ✓"
fi

if ! docker ps | grep -q redis; then
    echo "   Starting Redis..."
    cd ../infrastructure
    docker-compose up -d redis
    cd ../streaming
    sleep 5
else
    echo "   Redis is running ✓"
fi

# Create Kafka topics
echo ""
echo "2. Creating Kafka topics..."
docker exec -it kafka kafka-topics.sh --create --topic market.ticks --bootstrap-server localhost:9092 --partitions 10 --replication-factor 1 --if-not-exists
docker exec -it kafka kafka-topics.sh --create --topic market.quotes --bootstrap-server localhost:9092 --partitions 10 --replication-factor 1 --if-not-exists
docker exec -it kafka kafka-topics.sh --create --topic market.darkpool --bootstrap-server localhost:9092 --partitions 10 --replication-factor 1 --if-not-exists
docker exec -it kafka kafka-topics.sh --create --topic accumulation.alerts --bootstrap-server localhost:9092 --partitions 5 --replication-factor 1 --if-not-exists
docker exec -it kafka kafka-topics.sh --create --topic system.metrics --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1 --if-not-exists

echo "   Topics created ✓"

# Check for historical data
echo ""
echo "3. Checking historical data..."
if [ -d "$(dirname "$0")/../data/real_test_data" ]; then
    file_count=$(ls "$(dirname "$0")/../data/real_test_data"/*.json 2>/dev/null | wc -l)
    if [ $file_count -gt 0 ]; then
        echo "   Found $file_count tick data files ✓"
    else
        echo "   ERROR: No JSON files found in data/real_test_data/"
        echo "   Please download historical data first"
        exit 1
    fi
else
    echo "   ERROR: Directory data/real_test_data/ not found"
    echo "   Please create it and add historical tick data"
    exit 1
fi

# Run the integrated system
echo ""
echo "4. Starting integrated streaming system..."
echo "   - Speed: 100x (configurable in code)"
echo "   - Processing first 10 symbols"
echo "   - GPU acceleration enabled"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python integrated_kafka_example.py