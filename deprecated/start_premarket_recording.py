#!/usr/bin/env python3
"""
Start premarket data recording directly to files.
This bypasses Redis which is having issues.
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

# Signal handler for graceful shutdown
running = True

def signal_handler(sig, frame):
    global running
    print("\n⏹️  Stopping premarket recording...")
    running = False

signal.signal(signal.SIGINT, signal_handler)

def main():
    print("🚀 Starting Premarket Data Recording")
    print("=" * 60)
    
    # Check if it's actually premarket
    now = datetime.now()
    hour = now.hour
    
    if not (4 <= hour < 9):  # 4 AM - 9 AM ET
        print(f"⚠️  Warning: Current time {now.strftime('%H:%M')} may not be premarket hours")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return
    
    # Select symbols to record
    premarket_symbols = [
        # Liquid premarket movers
        'TSLA', 'NVDA', 'AMD', 'AAPL', 'SPY',
        # Small caps that might gap
        'ABAT', 'ABOS', 'ABVX', 'ACHV', 'ADIL',
        'ANEB', 'PAPL', 'RNAZ', 'UAVS', 'ZOOZ'
    ]
    
    print(f"📊 Recording {len(premarket_symbols)} symbols:")
    print(f"   {', '.join(premarket_symbols)}")
    
    # Create output directory
    output_dir = Path(f"data/premarket/{datetime.now().strftime('%Y%m%d')}")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output directory: {output_dir}")
    
    # Initialize IQFeed client
    print("\n🔌 Connecting to IQFeed...")
    client = IQFeedClient()
    
    try:
        # Connect to IQFeed
        result = client.connect()
        if not result.success:
            print(f"❌ Failed to connect: {result.error_message}")
            return
        
        print(f"✅ Connected! Session: {result.session_id}")
        
        # Subscribe to symbols
        print("\n📡 Subscribing to symbols...")
        for symbol in premarket_symbols:
            # Subscribe to all data types
            l2_result = client.subscribe_l2(symbol)
            trades_result = client.subscribe_trades(symbol)
            quotes_result = client.subscribe_quotes(symbol)
            
            if l2_result.success and trades_result.success and quotes_result.success:
                print(f"   ✅ {symbol}: L2, Trades, Quotes")
            else:
                print(f"   ⚠️  {symbol}: Partial subscription")
        
        # Initialize Kafka producer (optional)
        kafka_enabled = False
        kafka_producer = None
        
        try:
            print("\n🔗 Connecting to Kafka...")
            kafka_producer = IQFeedKafkaProducer()
            kafka_enabled = True
            print("✅ Kafka connected")
        except Exception as e:
            print(f"⚠️  Kafka not available: {e}")
            print("   Continuing with file-only recording")
        
        # Start recording
        print("\n📼 Recording started! Press Ctrl+C to stop")
        print("-" * 60)
        
        # Open file handles for each symbol
        file_handles = {}
        for symbol in premarket_symbols:
            file_handles[symbol] = {
                'l2': open(output_dir / f"{symbol}_l2.jsonl", 'w'),
                'trades': open(output_dir / f"{symbol}_trades.jsonl", 'w'),
                'quotes': open(output_dir / f"{symbol}_quotes.jsonl", 'w')
            }
        
        # Statistics
        message_counts = {symbol: {'l2': 0, 'trades': 0, 'quotes': 0} 
                         for symbol in premarket_symbols}
        last_report_time = time.time()
        
        # Main recording loop
        while running:
            # Get next message
            message = client.get_next_message(timeout=0.1)
            
            if message:
                symbol = message.get('symbol')
                msg_type = message.get('message_type')
                
                if symbol in premarket_symbols and msg_type:
                    # Add reception timestamp
                    message['reception_timestamp'] = datetime.now().isoformat()
                    
                    # Write to file
                    file_handle = file_handles.get(symbol, {}).get(msg_type)
                    if file_handle:
                        json.dump(message, file_handle)
                        file_handle.write('\n')
                        file_handle.flush()  # Ensure data is written
                        
                        # Update statistics
                        message_counts[symbol][msg_type] += 1
                    
                    # Send to Kafka if available
                    if kafka_enabled and kafka_producer:
                        try:
                            kafka_producer.publish_message(message, msg_type)
                        except Exception as e:
                            # Don't stop recording if Kafka fails
                            pass
            
            # Print statistics every 30 seconds
            if time.time() - last_report_time > 30:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Message counts:")
                for symbol in premarket_symbols:
                    counts = message_counts[symbol]
                    total = sum(counts.values())
                    if total > 0:
                        print(f"  {symbol}: L2={counts['l2']}, T={counts['trades']}, Q={counts['quotes']}")
                print("-" * 60)
                last_report_time = time.time()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        
        # Close file handles
        for symbol_files in file_handles.values():
            for fh in symbol_files.values():
                fh.close()
        
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
        total_messages = 0
        for symbol in premarket_symbols:
            counts = message_counts[symbol]
            total = sum(counts.values())
            if total > 0:
                print(f"  {symbol}: {total} messages (L2={counts['l2']}, T={counts['trades']}, Q={counts['quotes']})")
                total_messages += total
        
        print(f"\n✅ Total messages recorded: {total_messages}")
        print(f"📁 Data saved to: {output_dir}")

if __name__ == '__main__':
    main()