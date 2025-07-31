#!/usr/bin/env python3
"""
Start market data recording - works for premarket, regular hours, or after hours.
Uses Redis on port 6380 and Kafka for streaming.
"""

import os
import sys
import json
import time
import signal
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion.iqfeed_client import IQFeedClient
from ingestion.kafka_producer import IQFeedKafkaProducer
from processing.redis_cache_manager import RedisCacheManager

# Signal handler for graceful shutdown
running = True

def signal_handler(sig, frame):
    global running
    print("\n⏹️  Stopping data recording...")
    running = False

signal.signal(signal.SIGINT, signal_handler)

def main():
    print("🚀 Starting Market Data Recording")
    print("=" * 60)
    
    # Check market hours
    now = datetime.now()
    hour = now.hour
    
    if 4 <= hour < 9:
        market_phase = "PREMARKET"
    elif 9 <= hour < 16:
        market_phase = "REGULAR"
    elif 16 <= hour < 20:
        market_phase = "AFTERHOURS"
    else:
        market_phase = "CLOSED"
    
    print(f"📅 Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Market phase: {market_phase}")
    
    # Select symbols based on market phase
    if market_phase == "PREMARKET":
        symbols = [
            # Liquid premarket movers
            'TSLA', 'NVDA', 'AMD', 'AAPL', 'SPY', 'QQQ',
            # Small caps that might gap
            'ABAT', 'ABOS', 'ABVX', 'ACHV', 'ADIL',
            'ANEB', 'PAPL', 'RNAZ', 'UAVS', 'ZOOZ'
        ]
    else:
        # Regular hours - can handle more symbols
        symbols = [
            # Major stocks
            'TSLA', 'NVDA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'AMZN',
            'SPY', 'QQQ', 'IWM',
            # Small caps
            'ABAT', 'ABOS', 'ABVX', 'ACHV', 'ADIL', 'ANEB', 'PAPL', 
            'RNAZ', 'UAVS', 'ZOOZ', 'CLSD', 'AMOD', 'CIVR', 'GPRO'
        ]
    
    print(f"📊 Recording {len(symbols)} symbols")
    
    # Initialize Redis cache manager (on port 6380)
    print("\n🔗 Connecting to Redis...")
    try:
        from processing.redis_cache_manager import CacheConfig
        redis_config = CacheConfig()  # Already defaults to port 6380
        redis_manager = RedisCacheManager(config=redis_config)
        redis_manager.start()
        print("✅ Redis connected on port 6380")
    except Exception as e:
        print(f"⚠️  Redis not available: {e}")
        redis_manager = None
    
    # Initialize IQFeed client
    print("\n🔌 Connecting to IQFeed...")
    client = IQFeedClient()
    
    # Initialize kafka_producer to None to avoid UnboundLocalError
    kafka_producer = None
    
    try:
        # Connect to IQFeed
        result = client.connect()
        if not result.success:
            print(f"❌ Failed to connect: {result.error_message}")
            return
        
        print(f"✅ Connected! Session: {result.session_id}")
        
        # Subscribe to symbols
        print("\n📡 Subscribing to symbols...")
        successful_subscriptions = []
        
        for symbol in symbols:
            # Subscribe to all data types
            l2_result = client.subscribe_l2(symbol)
            trades_result = client.subscribe_trades(symbol)
            quotes_result = client.subscribe_quotes(symbol)
            
            if l2_result.success and trades_result.success and quotes_result.success:
                print(f"   ✅ {symbol}: L2, Trades, Quotes")
                successful_subscriptions.append(symbol)
            else:
                print(f"   ⚠️  {symbol}: Partial subscription")
        
        print(f"\n✅ Successfully subscribed to {len(successful_subscriptions)} symbols")
        
        # Initialize Kafka producer
        kafka_producer = None
        try:
            print("\n🔗 Connecting to Kafka...")
            kafka_producer = IQFeedKafkaProducer()
            if kafka_producer.start():
                print("✅ Kafka producer started")
            else:
                print("⚠️  Kafka producer failed to start")
                kafka_producer = None
        except Exception as e:
            print(f"⚠️  Kafka not available: {e}")
        
        # Start recording
        print("\n📼 Recording started! Press Ctrl+C to stop")
        print("-" * 60)
        
        # Statistics
        message_counts = {symbol: {'l2': 0, 'trades': 0, 'quotes': 0} 
                         for symbol in symbols}
        last_report_time = time.time()
        total_messages = 0
        
        # Main recording loop
        while running:
            # Get next message
            message = client.get_next_message(timeout=0.1)
            
            if message:
                symbol = message.get('symbol')
                msg_type = message.get('message_type')
                
                if symbol and msg_type:
                    # Update statistics
                    if symbol in message_counts:
                        message_counts[symbol][msg_type] += 1
                        total_messages += 1
                    
                    # Cache in Redis if available
                    if redis_manager:
                        try:
                            if msg_type == 'l2':
                                redis_manager.cache_l2_update(symbol, message)
                            elif msg_type == 'trade':
                                redis_manager.cache_trade(symbol, message)
                            elif msg_type == 'quote':
                                redis_manager.cache_quote(symbol, message)
                        except Exception as e:
                            # Don't stop recording if caching fails
                            pass
                    
                    # Send to Kafka if available
                    if kafka_producer and msg_type:
                        try:
                            kafka_producer.process_message(message)
                        except Exception as e:
                            # Don't stop recording if Kafka fails
                            pass
            
            # Print statistics every 30 seconds
            if time.time() - last_report_time > 30:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Statistics:")
                print(f"Total messages: {total_messages:,}")
                
                # Show top 10 most active symbols
                active_symbols = sorted(
                    [(s, sum(c.values())) for s, c in message_counts.items()],
                    key=lambda x: x[1],
                    reverse=True
                )[:10]
                
                print("\nMost active symbols:")
                for symbol, count in active_symbols:
                    counts = message_counts[symbol]
                    print(f"  {symbol}: {count} (L2={counts['l2']}, T={counts['trades']}, Q={counts['quotes']})")
                
                # Show Redis stats if available
                if redis_manager:
                    stats = redis_manager.get_cache_stats()
                    print(f"\nRedis cache: {stats.get('total_keys', 0)} keys")
                
                # Show Kafka stats if available
                if kafka_producer:
                    kafka_stats = kafka_producer.get_statistics()
                    print(f"Kafka: {kafka_stats.messages_sent} sent, "
                          f"{kafka_stats.messages_failed} failed")
                
                print("-" * 60)
                last_report_time = time.time()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        
        # Disconnect from IQFeed
        if client.is_connected():
            client.disconnect()
            print("✅ Disconnected from IQFeed")
        
        # Stop Kafka producer
        if kafka_producer:
            kafka_producer.stop()
            print("✅ Stopped Kafka producer")
        
        # Print final statistics
        print("\n📊 Final Statistics:")
        print(f"Total messages recorded: {total_messages:,}")
        
        # Show all symbols with activity
        for symbol in sorted(symbols):
            counts = message_counts[symbol]
            total = sum(counts.values())
            if total > 0:
                print(f"  {symbol}: {total} (L2={counts['l2']}, T={counts['trades']}, Q={counts['quotes']})")

if __name__ == '__main__':
    main()