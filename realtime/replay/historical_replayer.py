#!/usr/bin/env python3
"""
Historical Data Replayer
- Replays historical tick and L1 data through Kafka pipeline
- Supports speed control (1x to 100x real-time)
- Maintains temporal order and realistic timing
- Compares replay performance against real-time metrics
"""

import os
import csv
import json
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Generator, Tuple
from dataclasses import dataclass
from collections import deque
import heapq
import statistics

# Local imports
from realtime.core.kafka_producer import RealTimeKafkaProducer
from realtime.core.redis_metrics import RedisMetrics
from realtime.core.iqfeed_realtime_client import RealTimeTickData, RealTimeL1Data

logger = logging.getLogger(__name__)

@dataclass
class ReplayEvent:
    """Event for replay queue with timestamp ordering"""
    timestamp: datetime
    event_type: str  # 'tick' or 'l1'
    symbol: str
    data: Dict
    
    def __lt__(self, other):
        return self.timestamp < other.timestamp

@dataclass
class ReplayMetrics:
    """Metrics for replay performance analysis"""
    events_replayed: int = 0
    symbols_replayed: int = 0
    replay_start_time: Optional[datetime] = None
    replay_end_time: Optional[datetime] = None
    speed_multiplier: float = 1.0
    data_start_time: Optional[datetime] = None
    data_end_time: Optional[datetime] = None
    events_per_second: float = 0
    timing_accuracy_ms: float = 0
    latency_overhead_ms: float = 0


class HistoricalDataReplayer:
    """
    High-fidelity historical data replayer
    Features:
    - Precise timing reproduction with configurable speed
    - Multi-symbol temporal synchronization
    - Performance comparison with real-time data
    - Realistic latency simulation
    - Comprehensive replay metrics
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.replay_config = config.get('replay', {})
        
        # Speed control
        self.speed_multiplier = self.replay_config.get('default_speed_multiplier', 1.0)
        self.max_speed = self.replay_config.get('max_speed_multiplier', 100.0)
        
        # Data sources
        self.historical_data_dir = "/home/tcr1n15/PycharmProjects/L2/data"
        self.recorded_data_dir = config.get('data_collection', {}).get('base_dir', '/tmp/realtime_data')
        
        # Components
        self.kafka_producer = RealTimeKafkaProducer(config)
        self.redis_metrics = RedisMetrics(config)
        
        # Replay state
        self.running = False
        self.paused = False
        self.event_queue = []  # Priority queue for events
        self.replay_thread = None
        
        # Metrics
        self.metrics = ReplayMetrics()
        self.timing_samples = deque(maxlen=1000)
        
        # Comparison metrics
        self.enable_comparison = self.replay_config.get('enable_comparison', True)
        self.comparison_tolerance_ms = self.replay_config.get('comparison_tolerance_ms', 5)
        
    def load_historical_data(self, symbols: List[str], date: str) -> bool:
        """Load historical data for replay"""
        logger.info(f"Loading historical data for {len(symbols)} symbols on {date}")
        
        events_loaded = 0
        symbols_loaded = 0
        
        for symbol in symbols:
            tick_events = self._load_tick_data(symbol, date)
            l1_events = self._load_l1_data(symbol, date)
            
            if tick_events or l1_events:
                symbols_loaded += 1
                events_loaded += len(tick_events) + len(l1_events)
                
                # Add events to priority queue
                for event in tick_events:
                    heapq.heappush(self.event_queue, event)
                
                for event in l1_events:
                    heapq.heappush(self.event_queue, event)
        
        logger.info(f"Loaded {events_loaded} events for {symbols_loaded} symbols")
        
        # Update metrics
        self.metrics.symbols_replayed = symbols_loaded
        
        # Set data time range
        if self.event_queue:
            self.metrics.data_start_time = self.event_queue[0].timestamp
            self.metrics.data_end_time = max(event.timestamp for event in self.event_queue)
        
        return events_loaded > 0
    
    def _load_tick_data(self, symbol: str, date: str) -> List[ReplayEvent]:
        """Load tick data for a symbol"""
        events = []
        
        # Try CSV format first (from historical downloads)
        csv_path = os.path.join(self.historical_data_dir, 'raw_ticks', symbol, f"{symbol}_ticks_{date}.csv")
        
        if os.path.exists(csv_path):
            events.extend(self._load_tick_csv(symbol, csv_path))
        
        # Try JSON format (from real-time recording)
        json_path = os.path.join(self.recorded_data_dir, 'ticks', f"{symbol}_ticks_{date}.jsonl")
        
        if os.path.exists(json_path):
            events.extend(self._load_tick_json(symbol, json_path))
        
        return events
    
    def _load_l1_data(self, symbol: str, date: str) -> List[ReplayEvent]:
        """Load L1 data for a symbol"""
        events = []
        
        # Try CSV format first
        csv_path = os.path.join(self.historical_data_dir, 'raw_l1', symbol, f"{symbol}_l1_{date}.csv")
        
        if os.path.exists(csv_path):
            events.extend(self._load_l1_csv(symbol, csv_path))
        
        # Try JSON format (from real-time recording)
        json_path = os.path.join(self.recorded_data_dir, 'l1', f"{symbol}_l1_{date}.jsonl")
        
        if os.path.exists(json_path):
            events.extend(self._load_l1_json(symbol, json_path))
        
        return events
    
    def _load_tick_csv(self, symbol: str, file_path: str) -> List[ReplayEvent]:
        """Load tick data from CSV file"""
        events = []
        
        try:
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # Parse timestamp
                        timestamp_str = row.get('timestamp', '')
                        timestamp = self._parse_timestamp(timestamp_str)
                        
                        if not timestamp:
                            continue
                        
                        # Create tick data
                        tick_data = {
                            'symbol': symbol,
                            'timestamp': timestamp_str,
                            'system_timestamp': datetime.now(timezone.utc).isoformat(),
                            'price': float(row.get('price', 0)),
                            'size': int(row.get('size', 0)),
                            'exchange': '',
                            'conditions': row.get('conditions', ''),
                            'iqfeed_latency_ms': 0,  # Will be simulated
                            'system_latency_ms': 0
                        }
                        
                        events.append(ReplayEvent(
                            timestamp=timestamp,
                            event_type='tick',
                            symbol=symbol,
                            data=tick_data
                        ))
                        
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Skipping malformed tick row: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"Error loading tick CSV {file_path}: {e}")
        
        return events
    
    def _load_l1_csv(self, symbol: str, file_path: str) -> List[ReplayEvent]:
        """Load L1 data from CSV file"""
        events = []
        
        try:
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # Parse timestamp
                        timestamp_str = row.get('timestamp', '')
                        timestamp = self._parse_timestamp(timestamp_str)
                        
                        if not timestamp:
                            continue
                        
                        # Create L1 data
                        l1_data = {
                            'symbol': symbol,
                            'timestamp': timestamp_str,
                            'system_timestamp': datetime.now(timezone.utc).isoformat(),
                            'bid': float(row.get('bid', 0)),
                            'ask': float(row.get('ask', 0)),
                            'bid_size': int(row.get('bid_size', 0)),
                            'ask_size': int(row.get('ask_size', 0)),
                            'last_trade_price': float(row.get('last_trade_price', 0)),
                            'last_trade_size': int(row.get('last_trade_size', 0)),
                            'iqfeed_latency_ms': 0,  # Will be simulated
                            'system_latency_ms': 0
                        }
                        
                        events.append(ReplayEvent(
                            timestamp=timestamp,
                            event_type='l1',
                            symbol=symbol,
                            data=l1_data
                        ))
                        
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Skipping malformed L1 row: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"Error loading L1 CSV {file_path}: {e}")
        
        return events
    
    def _load_tick_json(self, symbol: str, file_path: str) -> List[ReplayEvent]:
        """Load tick data from JSON Lines file"""
        events = []
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        timestamp = self._parse_timestamp(data.get('timestamp', ''))
                        
                        if timestamp:
                            events.append(ReplayEvent(
                                timestamp=timestamp,
                                event_type='tick',
                                symbol=symbol,
                                data=data
                            ))
                    except json.JSONDecodeError:
                        continue
        
        except Exception as e:
            logger.error(f"Error loading tick JSON {file_path}: {e}")
        
        return events
    
    def _load_l1_json(self, symbol: str, file_path: str) -> List[ReplayEvent]:
        """Load L1 data from JSON Lines file"""
        events = []
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        timestamp = self._parse_timestamp(data.get('timestamp', ''))
                        
                        if timestamp:
                            events.append(ReplayEvent(
                                timestamp=timestamp,
                                event_type='l1',
                                symbol=symbol,
                                data=data
                            ))
                    except json.JSONDecodeError:
                        continue
        
        except Exception as e:
            logger.error(f"Error loading L1 JSON {file_path}: {e}")
        
        return events
    
    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """Parse timestamp string into datetime object"""
        if not timestamp_str:
            return None
        
        try:
            # Try different formats
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(timestamp_str, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error parsing timestamp {timestamp_str}: {e}")
            return None
    
    def start_replay(self, speed_multiplier: float = None) -> bool:
        """Start replaying historical data"""
        if self.running:
            logger.warning("Replay already running")
            return False
        
        if not self.event_queue:
            logger.error("No events loaded for replay")
            return False
        
        # Set speed
        if speed_multiplier is not None:
            self.speed_multiplier = min(speed_multiplier, self.max_speed)
        
        # Initialize metrics
        self.metrics.replay_start_time = datetime.now(timezone.utc)
        self.metrics.speed_multiplier = self.speed_multiplier
        self.metrics.events_replayed = 0
        
        # Start replay thread
        self.running = True
        self.paused = False
        self.replay_thread = threading.Thread(target=self._replay_worker, daemon=True)
        self.replay_thread.start()
        
        logger.info(f"✓ Started replay with {len(self.event_queue)} events at {self.speed_multiplier}x speed")
        return True
    
    def pause_replay(self):
        """Pause replay"""
        self.paused = True
        logger.info("Replay paused")
    
    def resume_replay(self):
        """Resume replay"""
        self.paused = False
        logger.info("Replay resumed")
    
    def stop_replay(self):
        """Stop replay"""
        logger.info("Stopping replay...")
        
        self.running = False
        self.paused = False
        
        if self.replay_thread:
            self.replay_thread.join(timeout=5)
        
        # Update final metrics
        self.metrics.replay_end_time = datetime.now(timezone.utc)
        
        if self.metrics.replay_start_time:
            replay_duration = (self.metrics.replay_end_time - self.metrics.replay_start_time).total_seconds()
            if replay_duration > 0:
                self.metrics.events_per_second = self.metrics.events_replayed / replay_duration
        
        logger.info("✓ Replay stopped")
    
    def set_speed(self, speed_multiplier: float):
        """Change replay speed during replay"""
        self.speed_multiplier = min(speed_multiplier, self.max_speed)
        logger.info(f"Replay speed changed to {self.speed_multiplier}x")
    
    def _replay_worker(self):
        """Background replay worker thread"""
        logger.info("Replay worker started")
        
        last_event_time = None
        replay_start_real_time = time.time()
        
        while self.running and self.event_queue:
            try:
                # Handle pause
                while self.paused and self.running:
                    time.sleep(0.1)
                
                if not self.running:
                    break
                
                # Get next event
                if not self.event_queue:
                    break
                
                event = heapq.heappop(self.event_queue)
                
                # Calculate timing
                current_real_time = time.time()
                
                if last_event_time is not None:
                    # Calculate how much time should have passed
                    data_time_delta = (event.timestamp - last_event_time).total_seconds()
                    real_time_delta = data_time_delta / self.speed_multiplier
                    
                    # Calculate when this event should be sent
                    target_real_time = replay_start_real_time + ((event.timestamp - self.metrics.data_start_time).total_seconds() / self.speed_multiplier)
                    
                    # Wait if necessary
                    wait_time = target_real_time - current_real_time
                    if wait_time > 0:
                        time.sleep(wait_time)
                
                # Send event
                self._send_replay_event(event)
                
                # Update metrics
                self.metrics.events_replayed += 1
                last_event_time = event.timestamp
                
                # Record timing accuracy
                if last_event_time and self.metrics.data_start_time:
                    expected_time = replay_start_real_time + ((event.timestamp - self.metrics.data_start_time).total_seconds() / self.speed_multiplier)
                    actual_time = time.time()
                    timing_error_ms = abs(actual_time - expected_time) * 1000
                    self.timing_samples.append(timing_error_ms)
                
                # Update timing accuracy metric
                if self.timing_samples:
                    self.metrics.timing_accuracy_ms = statistics.mean(self.timing_samples)
                
            except Exception as e:
                logger.error(f"Error in replay worker: {e}")
        
        logger.info("Replay worker finished")
    
    def _send_replay_event(self, event: ReplayEvent):
        """Send replay event through Kafka"""
        try:
            # Simulate realistic latency
            simulated_latency = self._simulate_latency()
            
            # Update data with simulated latency
            event.data['iqfeed_latency_ms'] = simulated_latency
            event.data['system_latency_ms'] = 0.5  # Small processing latency
            event.data['system_timestamp'] = datetime.now(timezone.utc).isoformat()
            
            # Send to Kafka based on event type
            if event.event_type == 'tick':
                # Convert to RealTimeTickData structure
                tick_data = RealTimeTickData(**event.data)
                self.kafka_producer.send_tick_data(tick_data)
                
                # Update Redis metrics
                self.redis_metrics.record_message()
                
            elif event.event_type == 'l1':
                # Convert to RealTimeL1Data structure
                l1_data = RealTimeL1Data(**event.data)
                self.kafka_producer.send_l1_data(l1_data)
                
                # Update Redis metrics
                self.redis_metrics.update_l1_metrics(l1_data)
            
        except Exception as e:
            logger.error(f"Error sending replay event: {e}")
    
    def _simulate_latency(self) -> float:
        """Simulate realistic IQFeed latency"""
        # Simulate typical IQFeed latency distribution
        import random
        
        # Normal distribution with mean=2ms, std=1ms
        latency = max(0.1, random.normalvariate(2.0, 1.0))
        return round(latency, 2)
    
    def get_replay_status(self) -> Dict:
        """Get current replay status"""
        progress_percent = 0
        if self.metrics.data_start_time and self.metrics.data_end_time:
            total_events = self.metrics.events_replayed + len(self.event_queue)
            if total_events > 0:
                progress_percent = (self.metrics.events_replayed / total_events) * 100
        
        return {
            'running': self.running,
            'paused': self.paused,
            'progress_percent': progress_percent,
            'events_remaining': len(self.event_queue),
            'speed_multiplier': self.speed_multiplier,
            'metrics': {
                'events_replayed': self.metrics.events_replayed,
                'symbols_replayed': self.metrics.symbols_replayed,
                'events_per_second': self.metrics.events_per_second,
                'timing_accuracy_ms': self.metrics.timing_accuracy_ms,
                'replay_duration_seconds': (
                    (datetime.now(timezone.utc) - self.metrics.replay_start_time).total_seconds()
                    if self.metrics.replay_start_time else 0
                )
            }
        }
    
    def compare_with_realtime(self, realtime_metrics: Dict) -> Dict:
        """Compare replay performance with real-time metrics"""
        if not self.enable_comparison:
            return {}
        
        comparison = {
            'replay_vs_realtime': {},
            'performance_delta': {},
            'accuracy_assessment': 'unknown'
        }
        
        try:
            # Compare throughput
            replay_rate = self.metrics.events_per_second
            realtime_rate = realtime_metrics.get('messages_per_second', 0)
            
            comparison['replay_vs_realtime'] = {
                'replay_events_per_second': replay_rate,
                'realtime_events_per_second': realtime_rate,
                'throughput_ratio': replay_rate / realtime_rate if realtime_rate > 0 else 0
            }
            
            # Compare latency
            replay_latency = self.metrics.timing_accuracy_ms
            realtime_latency = realtime_metrics.get('avg_latency_ms', 0)
            
            comparison['performance_delta'] = {
                'latency_difference_ms': abs(replay_latency - realtime_latency),
                'latency_within_tolerance': abs(replay_latency - realtime_latency) <= self.comparison_tolerance_ms
            }
            
            # Overall accuracy assessment
            if comparison['performance_delta']['latency_within_tolerance']:
                comparison['accuracy_assessment'] = 'high'
            elif comparison['performance_delta']['latency_difference_ms'] <= self.comparison_tolerance_ms * 2:
                comparison['accuracy_assessment'] = 'medium'
            else:
                comparison['accuracy_assessment'] = 'low'
            
        except Exception as e:
            logger.error(f"Error comparing replay with real-time: {e}")
        
        return comparison
    
    def health_check(self) -> Dict[str, any]:
        """Perform replay health check"""
        health_status = {
            'status': 'healthy',
            'replay_active': self.running,
            'events_loaded': len(self.event_queue) + self.metrics.events_replayed,
            'timing_accuracy_ms': self.metrics.timing_accuracy_ms
        }
        
        # Check timing accuracy
        if self.metrics.timing_accuracy_ms > 10:
            health_status['status'] = 'warning'
        elif self.metrics.timing_accuracy_ms > 50:
            health_status['status'] = 'critical'
        
        return health_status