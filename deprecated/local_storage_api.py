#!/usr/bin/env python3
"""
Local Storage API with ClickHouse-like interface
Stores data in optimized local format for backtesting
Real data only - NO MOCKS
"""

import os
import json
import logging
import pytz
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pickle
import gzip
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# US Eastern timezone
US_EASTERN = pytz.timezone('US/Eastern')
UTC = pytz.UTC

class DataValidationError(Exception):
    """Loud failure for data issues"""
    pass

class LocalStorageAPI:
    """Local storage with ClickHouse-like API"""
    
    def __init__(self, data_dir: str = None):
        """Initialize local storage"""
        
        if data_dir is None:
            # Use project root to ensure correct path resolution
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(project_root, 'data', 'storage')
        
        self.data_dir = data_dir
        self.tick_dir = os.path.join(data_dir, 'ticks')
        self.stats_dir = os.path.join(data_dir, 'stats')
        self.index_file = os.path.join(data_dir, 'data_index.json')
        
        # Create directories
        os.makedirs(self.tick_dir, exist_ok=True)
        os.makedirs(self.stats_dir, exist_ok=True)
        
        # Load or create index
        self.index = self._load_index()
        
        logger.info(f"✅ Local storage initialized at {data_dir}")
    
    def _load_index(self) -> Dict:
        """Load data availability index"""
        if os.path.exists(self.index_file):
            with open(self.index_file, 'r') as f:
                return json.load(f)
        return {'ticks': {}, 'stats': {}}
    
    def _save_index(self):
        """Save data index"""
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=2)
    
    def _convert_to_eastern(self, timestamp_str: str) -> Tuple[datetime, datetime]:
        """Convert timestamp to Eastern and UTC"""
        try:
            # Parse timestamp
            if '.' in timestamp_str:
                base_ts = timestamp_str.split('.')[0]
                dt = datetime.strptime(base_ts, '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            
            # Assume input is Eastern time from IQFeed
            dt_eastern = US_EASTERN.localize(dt)
            dt_utc = dt_eastern.astimezone(UTC)
            
            return dt_eastern, dt_utc
            
        except Exception as e:
            raise DataValidationError(f"❌ Invalid timestamp '{timestamp_str}': {e}")
    
    def store_ticks(self, symbol: str, date: str, ticks: List[Dict]) -> int:
        """Store tick data efficiently"""
        
        if not ticks:
            raise DataValidationError(f"❌ No ticks provided for {symbol} on {date}")
        
        # Validate timestamps are in order
        first_ts = self._convert_to_eastern(ticks[0]['timestamp'])[0]
        last_ts = self._convert_to_eastern(ticks[-1]['timestamp'])[0]
        
        if first_ts > last_ts:
            logger.warning(f"⚠️  Timestamps in reverse order - fixing")
            ticks = list(reversed(ticks))
        
        # Validate and prepare data
        validated_ticks = []
        errors = 0
        
        for i, tick in enumerate(ticks):
            try:
                # Required fields
                if 'timestamp' not in tick or 'price' not in tick:
                    errors += 1
                    continue
                
                # Validate price
                price = float(tick['price'])
                if price <= 0 or price > 100000:
                    logger.warning(f"⚠️  Suspicious price ${price} for {symbol}")
                    errors += 1
                    continue
                
                # Convert timestamp to Eastern
                dt_eastern, _ = self._convert_to_eastern(tick['timestamp'])
                
                validated_tick = {
                    'timestamp': dt_eastern.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                    'price': price,
                    'size': int(tick.get('size', 0)),
                    'bid': float(tick.get('bid', 0)) if tick.get('bid') else None,
                    'ask': float(tick.get('ask', 0)) if tick.get('ask') else None,
                    'exchange': tick.get('exchange', ''),
                    'conditions': tick.get('conditions', '')
                }
                
                validated_ticks.append(validated_tick)
                
            except Exception as e:
                logger.error(f"Error processing tick {i}: {e}")
                errors += 1
        
        if not validated_ticks:
            raise DataValidationError(f"❌ No valid ticks after validation")
        
        # Save to compressed file
        file_path = os.path.join(self.tick_dir, f"{symbol}_{date}.pkl.gz")
        
        try:
            with gzip.open(file_path, 'wb') as f:
                pickle.dump(validated_ticks, f)
            
            # Update index
            if symbol not in self.index['ticks']:
                self.index['ticks'][symbol] = {}
            
            self.index['ticks'][symbol][date] = {
                'count': len(validated_ticks),
                'first_timestamp': validated_ticks[0]['timestamp'],
                'last_timestamp': validated_ticks[-1]['timestamp'],
                'file_size': os.path.getsize(file_path)
            }
            
            self._save_index()
            
            logger.info(f"✅ Stored {len(validated_ticks)} ticks for {symbol} on {date}")
            if errors > 0:
                logger.warning(f"⚠️  {errors} ticks rejected due to validation")
            
            return len(validated_ticks)
            
        except Exception as e:
            raise DataValidationError(f"❌ Failed to store ticks: {e}")
    
    def get_ticks(self, symbol: str, date: str,
                  start_time: Optional[str] = None,
                  end_time: Optional[str] = None) -> List[Dict]:
        """Retrieve tick data"""
        
        file_path = os.path.join(self.tick_dir, f"{symbol}_{date}.pkl.gz")
        
        if not os.path.exists(file_path):
            logger.warning(f"No data for {symbol} on {date}")
            return []
        
        try:
            with gzip.open(file_path, 'rb') as f:
                ticks = pickle.load(f)
            
            # Filter by time if needed
            if start_time or end_time:
                filtered = []
                for tick in ticks:
                    ts = datetime.strptime(tick['timestamp'].split('.')[0], 
                                         '%Y-%m-%d %H:%M:%S')
                    
                    if start_time:
                        start_ts = datetime.strptime(start_time, '%H:%M:%S').time()
                        if ts.time() < start_ts:
                            continue
                    
                    if end_time:
                        end_ts = datetime.strptime(end_time, '%H:%M:%S').time()
                        if ts.time() > end_ts:
                            continue
                    
                    filtered.append(tick)
                
                ticks = filtered
            
            logger.info(f"Retrieved {len(ticks)} ticks for {symbol} on {date}")
            return ticks
            
        except Exception as e:
            logger.error(f"Failed to retrieve ticks: {e}")
            return []
    
    def check_data_exists(self, symbol: str, date: str, 
                         data_type: str = 'tick') -> bool:
        """Check if data exists"""
        
        if data_type == 'tick':
            return symbol in self.index['ticks'] and \
                   date in self.index['ticks'].get(symbol, {})
        
        return False
    
    def calculate_daily_stats(self, symbol: str, date: str) -> Dict:
        """Calculate daily statistics"""
        
        ticks = self.get_ticks(symbol, date)
        
        if not ticks:
            return {}
        
        # Calculate stats
        prices = [t['price'] for t in ticks]
        volumes = [t['size'] for t in ticks if t['size'] > 0]
        
        stats = {
            'symbol': symbol,
            'date': date,
            'open': prices[0],
            'high': max(prices),
            'low': min(prices),
            'close': prices[-1],
            'volume': sum(volumes),
            'tick_count': len(ticks),
            'vwap': sum(t['price'] * t['size'] for t in ticks if t['size'] > 0) / sum(volumes) if volumes else 0
        }
        
        # Calculate average spread
        spreads = []
        for tick in ticks:
            if tick.get('bid') and tick.get('ask'):
                spread = tick['ask'] - tick['bid']
                spreads.append(spread)
        
        stats['spread_avg'] = np.mean(spreads) if spreads else 0
        
        # Save stats
        stats_file = os.path.join(self.stats_dir, f"{symbol}_{date}_stats.json")
        with open(stats_file, 'w') as f:
            json.dump(stats, f)
        
        # Update index
        if symbol not in self.index['stats']:
            self.index['stats'][symbol] = {}
        
        self.index['stats'][symbol][date] = True
        self._save_index()
        
        return stats
    
    def get_gap_candidates(self, date: str, min_gap_pct: float = 10.0) -> List[Dict]:
        """Find stocks with overnight gaps"""
        
        gaps = []
        
        # Get previous trading day
        dt = datetime.strptime(date, '%Y%m%d')
        prev_dt = dt - timedelta(days=1)
        if prev_dt.weekday() == 6:  # Sunday
            prev_dt = prev_dt - timedelta(days=2)
        elif prev_dt.weekday() == 5:  # Saturday
            prev_dt = prev_dt - timedelta(days=1)
        
        prev_date = prev_dt.strftime('%Y%m%d')
        
        # Check all symbols
        for symbol in self.index.get('stats', {}):
            if prev_date in self.index['stats'][symbol] and \
               date in self.index['stats'][symbol]:
                
                # Load stats
                prev_stats_file = os.path.join(self.stats_dir, f"{symbol}_{prev_date}_stats.json")
                curr_stats_file = os.path.join(self.stats_dir, f"{symbol}_{date}_stats.json")
                
                try:
                    with open(prev_stats_file, 'r') as f:
                        prev_stats = json.load(f)
                    with open(curr_stats_file, 'r') as f:
                        curr_stats = json.load(f)
                    
                    # Calculate gap
                    gap_pct = ((curr_stats['open'] - prev_stats['close']) / 
                              prev_stats['close']) * 100
                    
                    if abs(gap_pct) >= min_gap_pct:
                        gaps.append({
                            'symbol': symbol,
                            'prev_close': prev_stats['close'],
                            'open': curr_stats['open'],
                            'high': curr_stats['high'],
                            'volume': curr_stats['volume'],
                            'gap_percent': gap_pct,
                            'high_percent': ((curr_stats['high'] - prev_stats['close']) / 
                                           prev_stats['close']) * 100
                        })
                
                except Exception as e:
                    logger.warning(f"Failed to process gap calculation for {symbol}: {e}")
        
        # Sort by gap size
        gaps.sort(key=lambda x: abs(x['gap_percent']), reverse=True)
        
        logger.info(f"Found {len(gaps)} gap candidates for {date}")
        return gaps
    
    def get_data_summary(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """Get summary of available data"""
        
        data = []
        
        for symbol, dates in self.index.get('ticks', {}).items():
            if symbols and symbol not in symbols:
                continue
            
            for date, info in dates.items():
                data.append({
                    'symbol': symbol,
                    'date': date,
                    'record_count': info['count'],
                    'first_timestamp': info['first_timestamp'],
                    'last_timestamp': info['last_timestamp'],
                    'file_size_kb': info['file_size'] / 1024
                })
        
        return pd.DataFrame(data)

def main():
    """Test local storage API"""
    
    # Initialize
    api = LocalStorageAPI()
    
    # Load sample data
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tick_dir = os.path.join(project_root, 'data', 'real_test_data')
    test_file = os.path.join(tick_dir, 'ABVX_20250722.json')
    
    if os.path.exists(test_file):
        with open(test_file, 'r') as f:
            ticks = json.load(f)
        
        # Store ticks
        stored = api.store_ticks('ABVX', '20250722', ticks[:1000])
        
        # Retrieve back
        retrieved = api.get_ticks('ABVX', '20250722')
        logger.info(f"Stored {stored}, retrieved {len(retrieved)} ticks")
        
        # Calculate stats
        stats = api.calculate_daily_stats('ABVX', '20250722')
        logger.info(f"Daily stats: {stats}")
        
        # Get summary
        summary = api.get_data_summary()
        logger.info(f"\nData summary:\n{summary}")

if __name__ == "__main__":
    main()