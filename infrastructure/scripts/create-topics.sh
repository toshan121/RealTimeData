#!/bin/bash

# Create Kafka topics for L2 market data

echo "Creating Kafka topics..."

# Function to wait for Kafka to be ready
wait_for_kafka() {
    local max_attempts=30
    local attempt=1
    
    echo "Waiting for Kafka to be ready..."
    
    while [ $attempt -le $max_attempts ]; do
        if docker exec l2_kafka kafka-broker-api-versions.sh --bootstrap-server localhost:9092 > /dev/null 2>&1; then
            echo "✓ Kafka is ready after $attempt attempts"
            return 0
        fi
        
        echo "  Attempt $attempt/$max_attempts - Kafka not ready yet, waiting 10 seconds..."
        sleep 10
        attempt=$((attempt + 1))
    done
    
    echo "✗ Kafka failed to become ready after $max_attempts attempts"
    return 1
}

# Wait for Kafka to be ready before creating topics
if ! wait_for_kafka; then
    echo "Error: Kafka is not available. Please check the service status."
    exit 1
fi

# Create topics with appropriate partitions and replication
docker exec -it l2_kafka kafka-topics.sh \
  --create \
  --topic iqfeed.l2.raw \
  --partitions 10 \
  --replication-factor 1 \
  --config retention.ms=86400000 \
  --config segment.ms=3600000 \
  --bootstrap-server localhost:9092 \
  --if-not-exists

docker exec -it l2_kafka kafka-topics.sh \
  --create \
  --topic iqfeed.trades.raw \
  --partitions 10 \
  --replication-factor 1 \
  --config retention.ms=86400000 \
  --config segment.ms=3600000 \
  --bootstrap-server localhost:9092 \
  --if-not-exists

docker exec -it l2_kafka kafka-topics.sh \
  --create \
  --topic iqfeed.quotes.raw \
  --partitions 10 \
  --replication-factor 1 \
  --config retention.ms=86400000 \
  --config segment.ms=3600000 \
  --bootstrap-server localhost:9092 \
  --if-not-exists

# Create processed data topics
docker exec -it l2_kafka kafka-topics.sh \
  --create \
  --topic trading.signals \
  --partitions 5 \
  --replication-factor 1 \
  --config retention.ms=86400000 \
  --bootstrap-server localhost:9092 \
  --if-not-exists

docker exec -it l2_kafka kafka-topics.sh \
  --create \
  --topic market.features \
  --partitions 5 \
  --replication-factor 1 \
  --config retention.ms=86400000 \
  --bootstrap-server localhost:9092 \
  --if-not-exists

# List all topics
echo -e "\nCreated topics:"
docker exec -it l2_kafka kafka-topics.sh --list --bootstrap-server localhost:9092

echo -e "\nTopic configuration:"
docker exec -it l2_kafka kafka-topics.sh --describe --bootstrap-server localhost:9092