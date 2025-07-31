#!/usr/bin/env python3
"""
Synthetic data recording for testing without IQFeed.
Generates realistic market data for 494 stocks.
"""

import os
import sys
import time
import random
import signal
import threading
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.kafka_producer import IQFeedKafkaProducer
from processing.redis_cache_manager import RedisCacheManager

running = True

def signal_handler(sig, frame):
    """Handle shutdown gracefully."""
    global running
    print("\n⏹️  Stopping synthetic recording...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class SyntheticRecorder:
    def __init__(self):
        """Initialize synthetic recorder."""
        self.symbols = []
        self.kafka_producer = None
        self.redis_manager = None
        self.base_prices = {}
        
    def load_symbols(self):
        """Load symbols from processed universe."""
        symbol_file = Path("data/universe/symbols_495.txt")
        if not symbol_file.exists():
            print(f"❌ Symbol file not found: {symbol_file}")
            return False
            
        with open(symbol_file, 'r') as f:
            self.symbols = [line.strip() for line in f if line.strip()]
            
        # Initialize base prices for each symbol
        for symbol in self.symbols:
            self.base_prices[symbol] = random.uniform(1.0, 20.0)
            
        print(f"✅ Loaded {len(self.symbols)} symbols")
        return True
        
    def wait_for_services(self):
        """Wait for all services to be ready."""
        print("⏳ Waiting for services...")
        
        # Wait for Redis
        try:
            from redis import Redis
            redis_client = Redis(host='localhost', port=6379, decode_responses=True)
            redis_client.ping()
            print("✅ Redis ready")
        except Exception as e:
            print(f"❌ Redis not ready: {e}")
            return False
            
        # Optional Kafka check - continue without it
        try:
            from kafka import KafkaProducer
            kafka = KafkaProducer(bootstrap_servers='localhost:9092')
            kafka.close()
            print("✅ Kafka ready")
        except Exception as e:
            print(f"⚠️  Kafka not available: {e}")
            print("   Continuing with Redis-only mode")
            
        return True
        
    def generate_quote(self, symbol, timestamp):
        """Generate synthetic quote data."""
        base_price = self.base_prices[symbol]
        
        # Add some random movement
        movement = random.gauss(0, 0.001) * base_price
        mid_price = base_price + movement
        
        # Update base price slightly
        self.base_prices[symbol] = mid_price
        
        # Generate bid/ask spread
        spread = random.uniform(0.01, 0.05)
        bid = round(mid_price - spread/2, 2)
        ask = round(mid_price + spread/2, 2)
        
        # Generate sizes
        bid_size = random.randint(100, 5000)
        ask_size = random.randint(100, 5000)
        
        return {
            'type': 'quote',
            'symbol': symbol,
            'timestamp': timestamp,
            'bid': bid,
            'ask': ask,
            'bid_size': bid_size,
            'ask_size': ask_size,
            'mid': round((bid + ask) / 2, 3),
            'spread': round(ask - bid, 3)
        }
        
    def generate_trade(self, symbol, timestamp, quote):
        """Generate synthetic trade data."""
        # 70% chance of trade at bid or ask
        if random.random() < 0.7:
            if random.random() < 0.5:
                price = quote['bid']
                side = 'B'
            else:
                price = quote['ask']
                side = 'S'
        else:
            # Trade inside spread
            price = round(random.uniform(quote['bid'], quote['ask']), 2)
            side = 'M'
            
        size = random.randint(100, 2000)
        
        return {
            'type': 'trade',
            'symbol': symbol,
            'timestamp': timestamp,
            'price': price,
            'size': size,
            'side': side,
            'volume': size * price
        }
        
    def start_recording(self):
        """Start synthetic recording for all symbols."""
        print(f"\n🎯 Starting synthetic recording for {len(self.symbols)} stocks")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Initialize clients
            try:
                self.kafka_producer = IQFeedKafkaProducer()
                print("✅ Initialized Kafka producer")
            except Exception as e:
                print(f"⚠️  Kafka unavailable: {e}")
                self.kafka_producer = None
                
            self.redis_manager = RedisCacheManager()
            print("✅ Initialized Redis client")
            
            # Start processing loop
            message_count = 0
            last_report = time.time()
            
            while running:
                try:
                    current_time = datetime.now().isoformat()
                    
                    # Generate data for random subset of symbols
                    active_symbols = random.sample(self.symbols, min(50, len(self.symbols)))
                    
                    for symbol in active_symbols:
                        # Generate quote
                        quote = self.generate_quote(symbol, current_time)
                        
                        # Send to Kafka (if available)
                        if self.kafka_producer:
                            from ingestion.kafka_producer import MessageType
                            self.kafka_producer.publish_message(quote, MessageType.QUOTE)
                        
                        # Cache in Redis
                        self.redis_manager.update_quote(symbol, quote)
                        
                        message_count += 1
                        
                        # Sometimes generate a trade
                        if random.random() < 0.3:
                            trade = self.generate_trade(symbol, current_time, quote)
                            if self.kafka_producer:
                                self.kafka_producer.publish_message(trade, MessageType.TRADE)
                            self.redis_manager.update_trade(symbol, trade)
                            message_count += 1
                            
                    # Periodic status report
                    if time.time() - last_report > 30:
                        print(f"📈 Synthetic Recording: {message_count} messages generated | {datetime.now().strftime('%H:%M:%S')}")
                        last_report = time.time()
                        
                    # Simulate realistic data rate
                    time.sleep(0.1)
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"⚠️  Error generating message: {e}")
                    
        except Exception as e:
            print(f"❌ Recording error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up connections."""
        print("\n🧹 Cleaning up...")
        
        if self.kafka_producer:
            try:
                self.kafka_producer.close()
                print("✅ Kafka producer closed")
            except:
                pass
                
        print("✅ Cleanup complete")

def main():
    """Main entry point."""
    print("🚀 Synthetic Recording Service Starting...")
    print("   (Testing mode - no IQFeed required)")
    print("=" * 50)
    
    recorder = SyntheticRecorder()
    
    # Load symbols
    if not recorder.load_symbols():
        sys.exit(1)
        
    # Wait for services
    if not recorder.wait_for_services():
        print("❌ Services not ready. Exiting.")
        sys.exit(1)
        
    # Start recording
    recorder.start_recording()
    
    print("\n👋 Synthetic recording stopped")

if __name__ == "__main__":
    main()