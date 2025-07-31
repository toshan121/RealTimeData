#!/usr/bin/env python3
"""
Temporal Data Streamer
- Loads historical tick/quote data and streams in proper time order
- Simulates real-time data flow for backtesting
- Detects dark pool prints via IQFeed TRUE tick analysis
"""

import json
import os
import heapq
from datetime import datetime, timedelta
from typing import List, Dict, Iterator, Tuple
from collections import defaultdict
import numpy as np
import pandas as pd
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class TickEvent:
    """Normalized tick event"""
    timestamp: datetime
    symbol: str
    price: float
    size: int
    bid: float
    ask: float
    exchange: str = ''
    conditions: str = ''
    sequence: int = 0
    
    def __lt__(self, other):
        # For heap ordering
        return self.timestamp < other.timestamp
    
    @property
    def is_dark_pool(self) -> bool:
        """Detect dark pool prints from IQFeed conditions"""
        # IQFeed dark pool indicators
        dark_indicators = ['D', 'MW', 'ADF', 'TRF']
        return any(ind in self.conditions for ind in dark_indicators)
    
    @property
    def is_odd_lot(self) -> bool:
        """Check if odd lot (< 100 shares)"""
        return self.size < 100
    
    @property
    def trade_location(self) -> float:
        """Where in spread did trade occur? 0=bid, 1=ask"""
        if self.bid > 0 and self.ask > 0 and self.ask > self.bid:
            return (self.price - self.bid) / (self.ask - self.bid)
        return 0.5


class TemporalDataStreamer:
    """Streams historical data in temporal order"""
    
    def __init__(self, data_dir: str = 'simulation/data'):
        self.tick_dir = os.path.join(data_dir, 'real_ticks')
        self.l1_dir = os.path.join(data_dir, 'l1_historical')
        
    def load_day_data(self, symbol: str, date: str) -> List[TickEvent]:
        """Load and merge tick + L1 data for a day"""
        
        events = []
        
        # Load tick data
        tick_file = os.path.join(self.tick_dir, f"{symbol}_{date}.json")
        if os.path.exists(tick_file):
            with open(tick_file, 'r') as f:
                tick_data = json.load(f)
                
            # Load L1 data if available
            l1_data = {}
            l1_file = os.path.join(self.l1_dir, f"{symbol}_{date}_l1.json")
            if os.path.exists(l1_file):
                with open(l1_file, 'r') as f:
                    l1_json = json.load(f)
                    if 'ticks' in l1_json:
                        l1_data = {t['timestamp']: t for t in l1_json['ticks']}
            
            # Create events
            for i, tick in enumerate(tick_data):
                # Parse timestamp
                ts_str = tick['timestamp']
                if '.' in ts_str:
                    ts_str = ts_str.split('.')[0]
                timestamp = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                
                # Get bid/ask from tick or L1
                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)
                
                # Override with L1 data if available
                if tick['timestamp'] in l1_data:
                    l1_tick = l1_data[tick['timestamp']]
                    bid = l1_tick.get('bid', bid)
                    ask = l1_tick.get('ask', ask)
                
                event = TickEvent(
                    timestamp=timestamp,
                    symbol=symbol,
                    price=tick['price'],
                    size=tick['size'],
                    bid=bid,
                    ask=ask,
                    exchange=tick.get('exchange', ''),
                    conditions=tick.get('conditions', ''),
                    sequence=i
                )
                
                events.append(event)
                
        return events
    
    def stream_events(self, symbols: List[str], start_date: str, 
                     end_date: str) -> Iterator[TickEvent]:
        """Stream events across multiple symbols in time order"""
        
        # Convert dates
        current = datetime.strptime(start_date, '%Y%m%d')
        end = datetime.strptime(end_date, '%Y%m%d')
        
        # Load all data into heap
        event_heap = []
        
        while current <= end:
            if current.weekday() < 5:  # Weekday
                date_str = current.strftime('%Y%m%d')
                
                for symbol in symbols:
                    events = self.load_day_data(symbol, date_str)
                    for event in events:
                        heapq.heappush(event_heap, event)
                        
            current += timedelta(days=1)
        
        # Stream events in order
        while event_heap:
            yield heapq.heappop(event_heap)
    
    def analyze_dark_pool_activity(self, events: List[TickEvent]) -> Dict:
        """Analyze dark pool activity in events"""
        
        total_volume = 0
        dark_volume = 0
        exchange_volume = defaultdict(int)
        
        for event in events:
            if event.size > 0:
                total_volume += event.size
                
                if event.is_dark_pool:
                    dark_volume += event.size
                
                if event.exchange:
                    exchange_volume[event.exchange] += event.size
        
        # Detect unexplained volume
        explained_volume = sum(exchange_volume.values())
        unexplained_volume = total_volume - explained_volume
        
        return {
            'total_volume': total_volume,
            'dark_volume': dark_volume,
            'dark_ratio': dark_volume / total_volume if total_volume > 0 else 0,
            'unexplained_volume': unexplained_volume,
            'unexplained_ratio': unexplained_volume / total_volume if total_volume > 0 else 0,
            'exchange_breakdown': dict(exchange_volume)
        }


class StatisticalAccumulationDetector:
    """Statistical approach to accumulation detection"""
    
    def __init__(self, lookback_window: int = 20):
        self.lookback_window = lookback_window
        self.symbol_baselines = {}
        
    def fit_baseline(self, symbol: str, historical_events: List[TickEvent]):
        """Fit statistical baseline for symbol"""
        
        # Group by time windows
        windows = defaultdict(list)
        
        for event in historical_events:
            # 5-minute windows
            window_time = event.timestamp.replace(
                minute=(event.timestamp.minute // 5) * 5,
                second=0, microsecond=0
            )
            windows[window_time].append(event)
        
        # Calculate statistics per window
        volume_stats = []
        flow_stats = []
        spread_stats = []
        dark_stats = []
        
        for window_time, events in sorted(windows.items()):
            # Volume
            volume = sum(e.size for e in events if e.size > 0)
            volume_stats.append(volume)
            
            # Order flow
            buy_volume = sum(e.size for e in events 
                           if e.size > 0 and e.trade_location > 0.6)
            sell_volume = sum(e.size for e in events 
                            if e.size > 0 and e.trade_location < 0.4)
            net_flow = buy_volume - sell_volume
            flow_stats.append(net_flow)
            
            # Spread
            spreads = [(e.ask - e.bid) for e in events 
                      if e.bid > 0 and e.ask > 0]
            if spreads:
                avg_spread = np.mean(spreads)
                spread_stats.append(avg_spread)
            
            # Dark pool
            dark_volume = sum(e.size for e in events 
                            if e.size > 0 and e.is_dark_pool)
            dark_ratio = dark_volume / volume if volume > 0 else 0
            dark_stats.append(dark_ratio)
        
        # Store baseline statistics
        self.symbol_baselines[symbol] = {
            'volume_mean': np.mean(volume_stats),
            'volume_std': np.std(volume_stats),
            'flow_mean': np.mean(flow_stats),
            'flow_std': np.std(flow_stats),
            'spread_mean': np.mean(spread_stats) if spread_stats else 0,
            'spread_std': np.std(spread_stats) if spread_stats else 0,
            'dark_mean': np.mean(dark_stats),
            'dark_std': np.std(dark_stats)
        }
        
        logger.info(f"Fitted baseline for {symbol}:")
        logger.info(f"  Volume: {self.symbol_baselines[symbol]['volume_mean']:.0f} "
                   f"± {self.symbol_baselines[symbol]['volume_std']:.0f}")
        logger.info(f"  Dark ratio: {self.symbol_baselines[symbol]['dark_mean']:.1%} "
                   f"± {self.symbol_baselines[symbol]['dark_std']:.1%}")
    
    def detect_anomalies(self, symbol: str, recent_events: List[TickEvent]) -> Dict:
        """Detect anomalies using statistical approach"""
        
        if symbol not in self.symbol_baselines:
            return {'anomaly_score': 0, 'anomalies': []}
        
        baseline = self.symbol_baselines[symbol]
        
        # Calculate current window stats
        volume = sum(e.size for e in recent_events if e.size > 0)
        
        buy_volume = sum(e.size for e in recent_events 
                       if e.size > 0 and e.trade_location > 0.6)
        sell_volume = sum(e.size for e in recent_events 
                        if e.size > 0 and e.trade_location < 0.4)
        net_flow = buy_volume - sell_volume
        
        dark_volume = sum(e.size for e in recent_events 
                        if e.size > 0 and e.is_dark_pool)
        dark_ratio = dark_volume / volume if volume > 0 else 0
        
        # Calculate z-scores
        volume_z = self._zscore(volume, baseline['volume_mean'], baseline['volume_std'])
        flow_z = self._zscore(net_flow, baseline['flow_mean'], baseline['flow_std'])
        dark_z = self._zscore(dark_ratio, baseline['dark_mean'], baseline['dark_std'])
        
        # Composite anomaly score (Mahalanobis distance approximation)
        anomaly_score = np.sqrt(volume_z**2 + flow_z**2 + dark_z**2) / np.sqrt(3)
        
        # Identify specific anomalies
        anomalies = []
        if volume_z > 2.5:
            anomalies.append(f"Volume surge ({volume_z:.1f}σ)")
        if flow_z > 2.0:
            anomalies.append(f"Buy pressure ({flow_z:.1f}σ)")
        if dark_z > 2.0:
            anomalies.append(f"Dark activity ({dark_z:.1f}σ)")
        
        # Special patterns
        if volume_z > 2 and flow_z > 1.5 and dark_z > 1:
            anomalies.append("STEALTH ACCUMULATION PATTERN")
        
        return {
            'anomaly_score': anomaly_score,
            'anomalies': anomalies,
            'volume_z': volume_z,
            'flow_z': flow_z,
            'dark_z': dark_z,
            'volume': volume,
            'dark_ratio': dark_ratio,
            'buy_ratio': buy_volume / volume if volume > 0 else 0
        }
    
    def _zscore(self, value: float, mean: float, std: float) -> float:
        """Calculate z-score"""
        if std > 0:
            return (value - mean) / std
        return 0


def demonstrate_temporal_streaming():
    """Demonstrate temporal streaming with statistical detection"""
    
    # Initialize components
    streamer = TemporalDataStreamer()
    detector = StatisticalAccumulationDetector()
    
    # Test symbols
    symbols = ['ABVX', 'ANEB', 'PAPL']
    
    # First, fit baselines on day 1
    logger.info("Fitting statistical baselines...")
    for symbol in symbols:
        events = streamer.load_day_data(symbol, '20250721')
        if events:
            detector.fit_baseline(symbol, events)
    
    # Now stream day 2 and detect anomalies
    logger.info("\nStreaming day 2 data...")
    
    # Group events by symbol and time window
    window_events = defaultdict(lambda: defaultdict(list))
    
    for event in streamer.stream_events(symbols, '20250722', '20250722'):
        # 5-minute windows
        window_time = event.timestamp.replace(
            minute=(event.timestamp.minute // 5) * 5,
            second=0, microsecond=0
        )
        window_events[event.symbol][window_time].append(event)
        
        # Check for anomalies every 100 events
        symbol_events = window_events[event.symbol][window_time]
        if len(symbol_events) >= 100:
            result = detector.detect_anomalies(event.symbol, symbol_events)
            
            if result['anomaly_score'] > 2.5:
                logger.info(f"\n🚨 ANOMALY DETECTED: {event.symbol} at {window_time}")
                logger.info(f"   Score: {result['anomaly_score']:.2f}")
                logger.info(f"   Volume: {result['volume']:,} ({result['volume_z']:.1f}σ)")
                logger.info(f"   Dark ratio: {result['dark_ratio']:.1%} ({result['dark_z']:.1f}σ)")
                logger.info(f"   Buy ratio: {result['buy_ratio']:.1%}")
                logger.info(f"   Anomalies: {', '.join(result['anomalies'])}")
    
    # Analyze dark pool activity
    logger.info("\n" + "="*60)
    logger.info("DARK POOL ANALYSIS")
    logger.info("="*60)
    
    for symbol in symbols:
        all_events = streamer.load_day_data(symbol, '20250722')
        if all_events:
            dark_analysis = streamer.analyze_dark_pool_activity(all_events)
            logger.info(f"\n{symbol}:")
            logger.info(f"  Total volume: {dark_analysis['total_volume']:,}")
            logger.info(f"  Dark volume: {dark_analysis['dark_volume']:,} "
                       f"({dark_analysis['dark_ratio']:.1%})")
            logger.info(f"  Unexplained: {dark_analysis['unexplained_volume']:,} "
                       f"({dark_analysis['unexplained_ratio']:.1%})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demonstrate_temporal_streaming()