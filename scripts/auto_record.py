#!/usr/bin/env python3
"""
Automatic recording service for 494 stocks.
Starts automatically with the system.
"""

import os
import sys
import time
import signal
import threading
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.iqfeed_client import IQFeedClient
from ingestion.kafka_producer import IQFeedKafkaProducer
from processing.redis_cache_manager import RedisCacheManager

running = True

def signal_handler(sig, frame):
    """Handle shutdown gracefully."""
    global running
    print("\n⏹️  Stopping recording...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class AutoRecorder:
    def __init__(self):
        """Initialize auto recorder."""
        self.symbols = []
        self.iqfeed_client = None
        self.kafka_producer = None
        self.redis_manager = None
        
    def load_symbols(self):
        """Load symbols from processed universe."""
        symbol_file = Path("data/universe/symbols_495.txt")
        if not symbol_file.exists():
            print(f"❌ Symbol file not found: {symbol_file}")
            print("   Run: python scripts/process_universe.py")
            return False
            
        with open(symbol_file, 'r') as f:
            self.symbols = [line.strip() for line in f if line.strip()]
            
        print(f"✅ Loaded {len(self.symbols)} symbols")
        return True
        
    def wait_for_services(self):
        """Wait for all services to be ready."""
        print("⏳ Waiting for services...")
        
        # Wait for IQFeed
        max_retries = 30
        for i in range(max_retries):
            try:
                test_client = IQFeedClient()
                test_client.connect()
                test_client.disconnect()
                print("✅ IQFeed ready")
                break
            except Exception as e:
                print(f"   Waiting for IQFeed... ({i+1}/{max_retries})")
                time.sleep(5)
        else:
            print("❌ IQFeed not available after 150 seconds")
            return False
            
        # Wait for Redis
        try:
            from redis import Redis
            redis_client = Redis(host='localhost', port=6380, decode_responses=True)
            redis_client.ping()
            print("✅ Redis ready")
        except Exception as e:
            print(f"❌ Redis not ready: {e}")
            return False
            
        # Wait for Kafka
        try:
            from kafka import KafkaProducer
            kafka = KafkaProducer(bootstrap_servers='localhost:9092')
            kafka.close()
            print("✅ Kafka ready")
        except Exception as e:
            print(f"❌ Kafka not ready: {e}")
            return False
            
        return True
        
    def start_recording(self):
        """Start recording for all symbols."""
        print(f"\n🎯 Starting recording for {len(self.symbols)} stocks")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Initialize clients
            self.iqfeed_client = IQFeedClient()
            self.kafka_producer = IQFeedKafkaProducer()
            self.redis_manager = RedisCacheManager()
            
            # Connect to IQFeed
            self.iqfeed_client.connect()
            print("✅ Connected to IQFeed")
            
            # Subscribe to all symbols
            print(f"📊 Subscribing to {len(self.symbols)} symbols...")
            
            # Subscribe in batches to avoid overwhelming IQFeed
            batch_size = 50
            for i in range(0, len(self.symbols), batch_size):
                batch = self.symbols[i:i+batch_size]
                for symbol in batch:
                    # Subscribe to L1 quotes
                    self.iqfeed_client.watch_symbol(symbol)
                    # Subscribe to L2 depth
                    self.iqfeed_client.subscribe_l2(symbol)
                    
                print(f"   Subscribed to {min(i+batch_size, len(self.symbols))}/{len(self.symbols)} symbols")
                time.sleep(0.5)  # Small delay between batches
                
            print("✅ All subscriptions complete")
            
            # Start processing loop
            message_count = 0
            last_report = time.time()
            
            while running:
                try:
                    # Process IQFeed messages
                    if self.iqfeed_client.has_data():
                        data = self.iqfeed_client.get_next_update()
                        if data:
                            # Send to Kafka
                            self.kafka_producer.send_update(data)
                            
                            # Cache in Redis
                            if data.get('type') == 'quote':
                                self.redis_manager.update_quote(data['symbol'], data)
                            elif data.get('type') == 'trade':
                                self.redis_manager.update_trade(data['symbol'], data)
                                
                            message_count += 1
                            
                    # Periodic status report
                    if time.time() - last_report > 30:
                        print(f"📈 Recording: {message_count} messages processed | {datetime.now().strftime('%H:%M:%S')}")
                        last_report = time.time()
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"⚠️  Error processing message: {e}")
                    
        except Exception as e:
            print(f"❌ Recording error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up connections."""
        print("\n🧹 Cleaning up...")
        
        if self.iqfeed_client:
            try:
                self.iqfeed_client.disconnect()
                print("✅ IQFeed disconnected")
            except:
                pass
                
        if self.kafka_producer:
            try:
                self.kafka_producer.close()
                print("✅ Kafka producer closed")
            except:
                pass
                
        print("✅ Cleanup complete")

def main():
    """Main entry point."""
    print("🚀 Auto Recording Service Starting...")
    print("=" * 50)
    
    recorder = AutoRecorder()
    
    # Load symbols
    if not recorder.load_symbols():
        sys.exit(1)
        
    # Wait for services
    if not recorder.wait_for_services():
        print("❌ Services not ready. Exiting.")
        sys.exit(1)
        
    # Start recording
    recorder.start_recording()
    
    print("\n👋 Recording stopped")

if __name__ == "__main__":
    main()