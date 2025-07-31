#!/usr/bin/env python3
"""
Minimal Temporal Market Replay System
- Reads historical data from files/ClickHouse  
- Replays with correct timing intervals
- Sends to Redis in same format as live data
- Simple start/stop/pause controls
- NO over-engineering: just replay data with timing
"""

import json
import time
import logging
import csv
import os
import redis
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Generator
from threading import Thread, Event, Lock
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleTemporalReplayer:
    """
    Minimal market data replayer with temporal accuracy.
    Anti-over-engineering: Just replay data with timing. That's it.
    """
    
    def __init__(self, redis_config: Dict = None):
        """Initialize with minimal config"""
        self.redis_config = redis_config or {'host': 'localhost', 'port': 6379, 'db': 0}
        
        # Redis connection with simple retry
        self.redis_client = None
        self._connect_redis()
        
        # Data paths
        self.data_dir = "/home/tcr1n15/PycharmProjects/RealTimeData/data"
        
        # Simple replay state
        self._stop_event = Event()
        self._pause_event = Event()
        self._replay_thread = None
        self._stats = {'messages_sent': 0, 'start_time': None}
        self._stats_lock = Lock()  # Thread safety for stats
    
    def _connect_redis(self):
        """Simple Redis connection with retry"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.redis_client = redis.Redis(**self.redis_config)
                self.redis_client.ping()
                logger.info("✅ Connected to Redis")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"❌ Redis connection failed after {max_retries} attempts: {e}")
                    raise
                logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}, retrying...")
                time.sleep(1)
    
    def _read_csv_data(self, file_path: str) -> List[Dict]:
        """Read tick/L1 data from CSV file"""
        try:
            data = []
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert timestamp to datetime for sorting
                    try:
                        ts = datetime.fromisoformat(row['timestamp'].replace('.', '.', 1))
                        # Validate required fields
                        if not row.get('symbol'):
                            logger.error(f"Missing symbol in CSV data: {row}")
                            continue
                        data.append({
                            'timestamp': ts,
                            'data': row
                        })
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping malformed CSV row: {e}")
                        continue
            
            # Sort by timestamp
            data.sort(key=lambda x: x['timestamp'])
            logger.info(f"Loaded {len(data)} records from {file_path}")
            return data
            
        except Exception as e:
            logger.error(f"Error reading CSV {file_path}: {e}")
            return []
    
    def _read_jsonl_data(self, file_path: str) -> List[Dict]:
        """Read tick/L1 data from JSONL file"""
        try:
            data = []
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        ts = datetime.fromisoformat(record['timestamp'].replace('T', ' ').replace('Z', ''))
                        # Validate required fields
                        if not record.get('symbol'):
                            logger.error(f"Missing symbol in JSONL data: {record}")
                            continue
                        data.append({
                            'timestamp': ts,
                            'data': record
                        })
                    except (json.JSONDecodeError, ValueError, KeyError) as e:
                        logger.warning(f"Skipping malformed JSONL line: {e}")
                        continue
            
            # Sort by timestamp
            data.sort(key=lambda x: x['timestamp'])
            logger.info(f"Loaded {len(data)} records from {file_path}")
            return data
            
        except Exception as e:
            logger.error(f"Error reading JSONL {file_path}: {e}")
            return []
    
    def load_symbol_data(self, symbol: str, date: str) -> List[Dict]:
        """Load all available data for a symbol on a date"""
        all_data = []
        
        # Try tick data CSV
        tick_csv = f"{self.data_dir}/raw_ticks/{symbol}/{symbol}_ticks_{date}.csv"
        if os.path.exists(tick_csv):
            tick_data = self._read_csv_data(tick_csv)
            for item in tick_data:
                item['data_type'] = 'tick'
                all_data.append(item)
        
        # Try L1 data CSV
        l1_csv = f"{self.data_dir}/raw_l1/{symbol}/{symbol}_l1_{date}.csv"
        if os.path.exists(l1_csv):
            l1_data = self._read_csv_data(l1_csv)
            for item in l1_data:
                item['data_type'] = 'l1'
                all_data.append(item)
        
        # Try captured tick data JSONL
        tick_jsonl = f"{self.data_dir}/captured/ticks/{symbol}_ticks_{date}.jsonl"
        if os.path.exists(tick_jsonl):
            tick_data = self._read_jsonl_data(tick_jsonl)
            for item in tick_data:
                item['data_type'] = 'tick'
                all_data.append(item)
        
        # Try captured L1 data JSONL
        l1_jsonl = f"{self.data_dir}/captured/l1/{symbol}_l1_{date}.jsonl"
        if os.path.exists(l1_jsonl):
            l1_data = self._read_jsonl_data(l1_jsonl)
            for item in l1_data:
                item['data_type'] = 'l1'
                all_data.append(item)
        
        # Sort all data by timestamp
        all_data.sort(key=lambda x: x['timestamp'])
        
        logger.info(f"Total data loaded for {symbol} on {date}: {len(all_data)} records")
        return all_data
    
    def _publish_to_redis(self, data_type: str, data: Dict):
        """Publish data to Redis in same format as live system"""
        try:
            # Validate symbol exists - fail fast
            symbol = data.get('symbol')
            if not symbol:
                logger.error(f"Missing required symbol field in data: {data}")
                return False
            
            # Normalize field names for live system compatibility
            if 'price' in data and 'trade_price' not in data:
                data['trade_price'] = data['price']
            if 'size' in data and 'trade_size' not in data:
                data['trade_size'] = data['size']
            
            # Use same Redis keys as live system
            if data_type == 'tick':
                key = f"realtime:ticks:{symbol}"
            elif data_type == 'l1':
                key = f"realtime:l1:{symbol}"
            else:
                key = f"realtime:data:{symbol}"
            
            # Add replay marker
            data['replay_timestamp'] = datetime.now().isoformat()
            data['is_replay'] = True
            
            # Publish to Redis
            self.redis_client.set(key, json.dumps(data, default=str), ex=300)  # 5min expiry
            self.redis_client.publish(f"updates:{data_type}", json.dumps(data, default=str))
            return True
            
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")
            return False
    
    def _replay_worker(self, data: List[Dict]):
        """Background thread that replays data with timing"""
        logger.info(f"🔄 Starting replay of {len(data)} records")
        
        with self._stats_lock:
            self._stats['start_time'] = time.time()
            self._stats['messages_sent'] = 0
        
        prev_timestamp = None
        
        for i, record in enumerate(data):
            # Check if we should stop
            if self._stop_event.is_set():
                logger.info("🛑 Replay stopped")
                break
            
            # Check if we should pause
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(0.1)
            
            # Calculate sleep time based on timestamp difference
            current_timestamp = record['timestamp']
            
            if prev_timestamp is not None:
                time_diff = (current_timestamp - prev_timestamp).total_seconds()
                if time_diff > 0:
                    # Sleep for the actual time difference (simple temporal replay)
                    sleep_time = min(time_diff, 5.0)  # Cap at 5 seconds max
                    time.sleep(sleep_time)
            
            # Send data to Redis - fail fast on critical errors
            if not self._publish_to_redis(record['data_type'], record['data']):
                logger.error(f"Failed to publish record {i+1}, continuing replay")
            
            # Update stats (thread-safe)
            with self._stats_lock:
                self._stats['messages_sent'] += 1
            prev_timestamp = current_timestamp
            
            # Log progress occasionally
            if (i + 1) % 1000 == 0:
                with self._stats_lock:
                    elapsed = time.time() - self._stats['start_time']
                    rate = self._stats['messages_sent'] / elapsed if elapsed > 0 else 0
                    logger.info(f"📊 Progress: {i+1}/{len(data)} messages ({rate:.1f} msg/sec)")
        
        with self._stats_lock:
            elapsed = time.time() - self._stats['start_time']
            logger.info(f"✅ Replay completed: {self._stats['messages_sent']} messages in {elapsed:.1f}s")
    
    def start_replay(self, symbol: str, date: str) -> bool:
        """Start replaying data for a symbol"""
        if self._replay_thread and self._replay_thread.is_alive():
            logger.warning("⚠️ Replay already running")
            return False
        
        # Load data with basic validation
        try:
            data = self.load_symbol_data(symbol, date)
            if not data:
                logger.error(f"❌ No data found for {symbol} on {date}")
                return False
        except Exception as e:
            logger.error(f"❌ Failed to load data for {symbol} on {date}: {e}")
            return False
        
        # Reset events
        self._stop_event.clear()
        self._pause_event.clear()
        
        # Start replay thread
        self._replay_thread = Thread(target=self._replay_worker, args=(data,), daemon=True)
        self._replay_thread.start()
        
        logger.info(f"🚀 Started replay for {symbol} on {date}")
        return True
    
    def pause_replay(self):
        """Pause ongoing replay"""
        self._pause_event.set()
        logger.info("⏸️ Replay paused")
    
    def resume_replay(self):
        """Resume paused replay"""
        self._pause_event.clear()
        logger.info("▶️ Replay resumed")
    
    def stop_replay(self):
        """Stop ongoing replay"""
        self._stop_event.set()
        if self._replay_thread:
            self._replay_thread.join(timeout=5.0)
        logger.info("🛑 Replay stopped")
    
    def get_status(self) -> Dict:
        """Get simple replay status"""
        is_running = self._replay_thread and self._replay_thread.is_alive()
        is_paused = self._pause_event.is_set()
        
        with self._stats_lock:
            elapsed = time.time() - self._stats['start_time'] if self._stats['start_time'] else 0
            rate = self._stats['messages_sent'] / elapsed if elapsed > 0 else 0
            messages_sent = self._stats['messages_sent']
        
        return {
            'running': is_running,
            'paused': is_paused,
            'messages_sent': messages_sent,
            'elapsed_seconds': elapsed,
            'messages_per_second': rate
        }
    
    def list_available_data(self) -> Dict[str, List[str]]:
        """List available data files"""
        available = {'symbols': set(), 'dates': set()}
        
        # Check raw_ticks directory
        tick_dir = f"{self.data_dir}/raw_ticks"
        if os.path.exists(tick_dir):
            for symbol_dir in os.listdir(tick_dir):
                symbol_path = os.path.join(tick_dir, symbol_dir)
                if os.path.isdir(symbol_path):
                    available['symbols'].add(symbol_dir)
                    for file in os.listdir(symbol_path):
                        if file.endswith('.csv') and '_ticks_' in file:
                            date = file.split('_ticks_')[1].replace('.csv', '')
                            available['dates'].add(date)
        
        # Check captured directory
        captured_dir = f"{self.data_dir}/captured/ticks"
        if os.path.exists(captured_dir):
            for file in os.listdir(captured_dir):
                if file.endswith('.jsonl') and '_ticks_' in file:
                    symbol = file.split('_ticks_')[0]
                    date = file.split('_ticks_')[1].replace('.jsonl', '')
                    available['symbols'].add(symbol)
                    available['dates'].add(date)
        
        return {
            'symbols': sorted(list(available['symbols'])),
            'dates': sorted(list(available['dates']))
        }


def main():
    """Simple command line interface"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Minimal Temporal Market Data Replayer")
    parser.add_argument('--symbol', help='Symbol to replay (e.g., AAPL)')
    parser.add_argument('--date', help='Date to replay (YYYYMMDD)')
    parser.add_argument('--list', action='store_true', help='List available data')
    
    args = parser.parse_args()
    
    replayer = SimpleTemporalReplayer()
    
    try:
        if args.list:
            available = replayer.list_available_data()
            print("\n📊 AVAILABLE DATA:")
            print(f"  📅 Dates: {', '.join(available['dates'])}")
            print(f"  🎯 Symbols: {', '.join(available['symbols'])}")
            return
        
        if not args.symbol or not args.date:
            print("❌ Both --symbol and --date are required for replay")
            return
        
        # Start replay
        if replayer.start_replay(args.symbol, args.date):
            print(f"\n🚀 Replaying {args.symbol} for {args.date}")
            print("Press Ctrl+C to stop\n")
            
            try:
                while True:
                    status = replayer.get_status()
                    if not status['running']:
                        break
                    
                    print(f"\r📊 Status: {status['messages_sent']} messages sent "
                          f"({status['messages_per_second']:.1f} msg/sec)", end='', flush=True)
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print("\n🛑 Stopping replay...")
                replayer.stop_replay()
        else:
            print(f"❌ Failed to start replay for {args.symbol} on {args.date}")
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        replayer.stop_replay()


if __name__ == '__main__':
    main()