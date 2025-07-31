#!/usr/bin/env python3
"""
Historical Data Replay System
Replay recorded market data through Kafka for testing and validation
Works independently of UI - feeds data to Kafka for consumption by any component
"""

import json
import time
import pandas as pd
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError
import argparse
import glob

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalDataReplayer:
    """
    Replay historical market data through Kafka
    - Reads CSV files from our data collection
    - Streams tick data and L1 quotes to Kafka topics
    - Maintains original timing or accelerated replay
    - Supports multiple symbols simultaneously
    """
    
    def __init__(self, kafka_config: Dict = None):
        self.kafka_config = kafka_config or {
            'bootstrap_servers': ['localhost:9092'],
            'value_serializer': lambda x: json.dumps(x, default=str).encode('utf-8'),
            'key_serializer': lambda x: x.encode('utf-8') if x else None,
            'acks': 1,
            'retries': 3
        }
        
        # Initialize Kafka producer
        try:
            self.producer = KafkaProducer(**self.kafka_config)
            logger.info("✅ Kafka producer initialized for replay")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Kafka producer: {e}")
            raise
        
        # Data paths
        self.data_root = "/home/tcr1n15/PycharmProjects/L2/data"
        self.tick_data_dir = f"{self.data_root}/raw_ticks"
        self.l1_data_dir = f"{self.data_root}/raw_l1"
        
        # Replay state
        self.is_replaying = False
        self.replay_stats = {
            'messages_sent': 0,
            'start_time': None,
            'symbols_processed': 0,
            'errors': 0
        }
    
    def list_available_data(self) -> Dict[str, List[str]]:
        """List available data files for replay"""
        available_data = {
            'tick_files': [],
            'l1_files': [],
            'dates': set(),
            'symbols': set()
        }
        
        # Find tick files
        if os.path.exists(self.tick_data_dir):
            tick_pattern = f"{self.tick_data_dir}/*/*.csv"
            tick_files = glob.glob(tick_pattern)
            available_data['tick_files'] = tick_files
            
            for file_path in tick_files:
                # Extract symbol and date from filename
                filename = os.path.basename(file_path)
                if '_ticks_' in filename:
                    parts = filename.split('_')
                    if len(parts) >= 3:
                        symbol = parts[0]
                        date = parts[2].replace('.csv', '')
                        available_data['symbols'].add(symbol)
                        available_data['dates'].add(date)
        
        # Find L1 files
        if os.path.exists(self.l1_data_dir):
            l1_pattern = f"{self.l1_data_dir}/*/*.csv"
            l1_files = glob.glob(l1_pattern)
            available_data['l1_files'] = l1_files
            
            for file_path in l1_files:
                filename = os.path.basename(file_path)
                if '_l1_' in filename:
                    parts = filename.split('_')
                    if len(parts) >= 3:
                        symbol = parts[0]
                        date = parts[2].replace('.csv', '')
                        available_data['symbols'].add(symbol)
                        available_data['dates'].add(date)
        
        # Convert sets to sorted lists
        available_data['dates'] = sorted(list(available_data['dates']))
        available_data['symbols'] = sorted(list(available_data['symbols']))
        
        return available_data
    
    def replay_symbol_data(self, symbol: str, date: str, replay_speed: float = 1.0, max_messages: int = None) -> bool:
        """
        Replay data for a single symbol
        
        Args:
            symbol: Stock symbol to replay
            date: Date string (YYYYMMDD format)
            replay_speed: Speed multiplier (1.0 = real-time, 10.0 = 10x speed)
            max_messages: Maximum messages to send (None = all)
        """
        logger.info(f"🔄 Starting replay for {symbol} on {date} at {replay_speed}x speed")
        
        # Find data files
        tick_file = f"{self.tick_data_dir}/{symbol}/{symbol}_ticks_{date}.csv"
        l1_file = f"{self.l1_data_dir}/{symbol}/{symbol}_l1_{date}.csv"
        
        tick_data = None
        l1_data = None
        
        # Load tick data
        if os.path.exists(tick_file):
            try:
                tick_data = pd.read_csv(tick_file)
                tick_data['timestamp'] = pd.to_datetime(tick_data['timestamp'])
                tick_data = tick_data.sort_values('timestamp')
                logger.info(f"📊 Loaded {len(tick_data)} tick records for {symbol}")
            except Exception as e:
                logger.error(f"❌ Error loading tick data for {symbol}: {e}")
        
        # Load L1 data
        if os.path.exists(l1_file):
            try:
                l1_data = pd.read_csv(l1_file)
                l1_data['timestamp'] = pd.to_datetime(l1_data['timestamp'])
                l1_data = l1_data.sort_values('timestamp')
                logger.info(f"📊 Loaded {len(l1_data)} L1 records for {symbol}")
            except Exception as e:
                logger.error(f"❌ Error loading L1 data for {symbol}: {e}")
        
        if tick_data is None and l1_data is None:
            logger.warning(f"⚠️ No data found for {symbol} on {date}")
            return False
        
        # Combine and sort all data by timestamp
        all_records = []
        
        if tick_data is not None:
            for _, row in tick_data.iterrows():
                all_records.append({
                    'type': 'tick',
                    'timestamp': row['timestamp'],
                    'data': row.to_dict()
                })
        
        if l1_data is not None:
            for _, row in l1_data.iterrows():
                all_records.append({
                    'type': 'l1',
                    'timestamp': row['timestamp'],
                    'data': row.to_dict()
                })
        
        # Sort by timestamp
        all_records.sort(key=lambda x: x['timestamp'])
        
        if max_messages:
            all_records = all_records[:max_messages]
        
        logger.info(f"📈 Replaying {len(all_records)} total records for {symbol}")
        
        # Replay data
        messages_sent = 0
        start_time = time.time()
        replay_start_timestamp = all_records[0]['timestamp'] if all_records else None
        
        for i, record in enumerate(all_records):
            if not self.is_replaying:
                break
            
            # Calculate timing for realistic replay
            if i > 0 and replay_speed > 0:
                # Time difference between current and previous record
                time_diff = (record['timestamp'] - all_records[i-1]['timestamp']).total_seconds()
                # Sleep for scaled time difference
                sleep_time = time_diff / replay_speed
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 1.0))  # Cap at 1 second
            
            # Prepare message
            message_data = record['data'].copy()
            message_data['symbol'] = symbol
            message_data['replay_timestamp'] = datetime.now().isoformat()
            message_data['original_timestamp'] = record['timestamp'].isoformat()
            
            # Send to appropriate Kafka topic
            topic = f"market_{record['type']}s"  # market_ticks or market_l1s
            
            try:
                future = self.producer.send(
                    topic=topic,
                    key=symbol,
                    value=message_data
                )
                
                # Don't wait for every message, just log errors
                future.add_errback(lambda e: logger.error(f"Failed to send message: {e}"))
                
                messages_sent += 1
                self.replay_stats['messages_sent'] += 1
                
                if messages_sent % 1000 == 0:
                    elapsed = time.time() - start_time
                    rate = messages_sent / elapsed if elapsed > 0 else 0
                    logger.info(f"📊 {symbol}: {messages_sent}/{len(all_records)} messages sent ({rate:.1f} msg/sec)")
                
            except Exception as e:
                logger.error(f"❌ Error sending message for {symbol}: {e}")
                self.replay_stats['errors'] += 1
        
        # Flush producer
        self.producer.flush(timeout=10)
        
        elapsed = time.time() - start_time
        rate = messages_sent / elapsed if elapsed > 0 else 0
        logger.info(f"✅ Completed replay for {symbol}: {messages_sent} messages in {elapsed:.1f}s ({rate:.1f} msg/sec)")
        
        return True
    
    def replay_multiple_symbols(self, symbols: List[str], date: str, replay_speed: float = 1.0, max_messages_per_symbol: int = None) -> Dict:
        """
        Replay data for multiple symbols simultaneously
        
        Args:
            symbols: List of stock symbols
            date: Date string (YYYYMMDD format)  
            replay_speed: Speed multiplier
            max_messages_per_symbol: Max messages per symbol
        """
        logger.info(f"🚀 Starting multi-symbol replay: {len(symbols)} symbols on {date}")
        
        self.is_replaying = True
        self.replay_stats = {
            'messages_sent': 0,
            'start_time': datetime.now(),
            'symbols_processed': 0,
            'errors': 0
        }
        
        results = {
            'success_count': 0,
            'failed_symbols': [],
            'total_messages': 0,
            'duration': 0
        }
        
        start_time = time.time()
        
        for symbol in symbols:
            if not self.is_replaying:
                break
                
            try:
                success = self.replay_symbol_data(
                    symbol=symbol,
                    date=date,
                    replay_speed=replay_speed,
                    max_messages=max_messages_per_symbol
                )
                
                if success:
                    results['success_count'] += 1
                    self.replay_stats['symbols_processed'] += 1
                else:
                    results['failed_symbols'].append(symbol)
                    
            except Exception as e:
                logger.error(f"❌ Failed to replay {symbol}: {e}")
                results['failed_symbols'].append(symbol)
                self.replay_stats['errors'] += 1
        
        results['total_messages'] = self.replay_stats['messages_sent']
        results['duration'] = time.time() - start_time
        
        logger.info(f"🎉 Multi-symbol replay completed:")
        logger.info(f"   ✅ Successful: {results['success_count']}/{len(symbols)} symbols")
        logger.info(f"   📊 Total messages: {results['total_messages']:,}")
        logger.info(f"   ⏱️ Duration: {results['duration']:.1f} seconds")
        logger.info(f"   🚀 Avg rate: {results['total_messages']/results['duration']:.1f} msg/sec")
        
        return results
    
    def stop_replay(self):
        """Stop ongoing replay"""
        logger.info("🛑 Stopping historical data replay")
        self.is_replaying = False
    
    def close(self):
        """Close producer and cleanup"""
        if self.producer:
            self.producer.close()
        logger.info("✅ Historical data replayer closed")


def main():
    """Command line interface for historical data replay"""
    parser = argparse.ArgumentParser(description="Replay historical market data through Kafka")
    parser.add_argument('--symbols', nargs='+', help='Symbols to replay (e.g., AAPL TSLA)')
    parser.add_argument('--date', help='Date to replay (YYYYMMDD format)')
    parser.add_argument('--speed', type=float, default=1.0, help='Replay speed multiplier (default: 1.0)')
    parser.add_argument('--max-messages', type=int, help='Maximum messages per symbol')
    parser.add_argument('--list-data', action='store_true', help='List available data files')
    
    args = parser.parse_args()
    
    replayer = HistoricalDataReplayer()
    
    try:
        if args.list_data:
            # List available data
            available = replayer.list_available_data()
            print("\n📊 AVAILABLE HISTORICAL DATA:")
            print(f"   📅 Dates: {', '.join(available['dates'])}")
            print(f"   🎯 Symbols: {', '.join(available['symbols'])}")
            print(f"   📁 Tick files: {len(available['tick_files'])}")
            print(f"   📁 L1 files: {len(available['l1_files'])}")
            return
        
        if not args.date:
            logger.error("❌ --date is required for replay")
            return
            
        if not args.symbols:
            # Use all available symbols for the date
            available = replayer.list_available_data()
            if args.date in available['dates']:
                args.symbols = available['symbols']
                logger.info(f"🎯 Using all available symbols for {args.date}: {len(args.symbols)} symbols")
            else:
                logger.error(f"❌ No data available for date: {args.date}")
                return
        
        # Start replay
        results = replayer.replay_multiple_symbols(
            symbols=args.symbols,
            date=args.date,
            replay_speed=args.speed,
            max_messages_per_symbol=args.max_messages
        )
        
        print(f"\n🎉 REPLAY COMPLETED:")
        print(f"   ✅ Successfully replayed: {results['success_count']} symbols")
        print(f"   ❌ Failed symbols: {len(results['failed_symbols'])}")
        print(f"   📊 Total messages sent: {results['total_messages']:,}")
        print(f"   ⏱️ Duration: {results['duration']:.1f} seconds")
        
        if results['failed_symbols']:
            print(f"   Failed symbols: {', '.join(results['failed_symbols'])}")
    
    except KeyboardInterrupt:
        logger.info("🛑 Replay interrupted by user")
        replayer.stop_replay()
    
    finally:
        replayer.close()


if __name__ == '__main__':
    main()