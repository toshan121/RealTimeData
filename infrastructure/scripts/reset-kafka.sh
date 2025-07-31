#!/bin/bash

# Reset Kafka by deleting all topics and recreating them

echo "WARNING: This will delete all Kafka data!"
read -p "Are you sure? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

echo "Deleting all topics..."

# Get list of topics
topics=$(docker exec l2_kafka kafka-topics.sh --list --bootstrap-server localhost:9092 2>/dev/null | grep -v "__consumer_offsets")

# Delete each topic
for topic in $topics; do
    echo "Deleting topic: $topic"
    docker exec l2_kafka kafka-topics.sh --delete --topic "$topic" --bootstrap-server localhost:9092
done

echo "Waiting for deletion to complete..."
sleep 5

# Recreate topics
echo "Recreating topics..."
$(dirname "$0")/create-topics.sh

echo "Kafka reset complete!"