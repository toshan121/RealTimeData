#!/usr/bin/env python3
"""
Historical Data Kafka Streamer
- Reads historical tick/L1 data from JSON files
- Streams to Kafka in temporal order
- Simulates real-time data flow for backtesting
- Detects dark pools using multiple methods
"""

import asyncio
import json
import os
import heapq
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import logging
from pathlib import Path
import glob

from aiokafka import AIOKafkaProducer
import numpy as np

logger = logging.getLogger(__name__)

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = 'localhost:9092'
TICK_TOPIC = 'market.ticks'
QUOTE_TOPIC = 'market.quotes'
DARK_POOL_TOPIC = 'market.darkpool'

@dataclass
class HistoricalEvent:
    """Base class for historical events"""
    timestamp: datetime
    symbol: str
    sequence: int = 0
    
    def __lt__(self, other):
        # For heap ordering - earlier timestamps first
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        # If same timestamp, maintain sequence order
        return self.sequence < other.sequence

@dataclass
class TickEvent(HistoricalEvent):
    """Historical tick event"""
    price: float = 0.0
    size: int = 0
    bid: float = 0  # From tick data
    ask: float = 0  # From tick data
    exchange: str = ''
    conditions: str = ''
    
    def is_dark_pool_by_conditions(self) -> bool:
        """Method 1: Check IQFeed condition codes"""
        dark_indicators = ['D', 'MW', 'ADF', 'TRF']
        return any(ind in self.conditions for ind in dark_indicators)
    
    def is_dark_pool_by_spread(self) -> bool:
        """Method 2: Check if trade outside NBBO"""
        if self.bid > 0 and self.ask > 0:
            # Trade below bid or above ask (with small tolerance)
            return self.price < self.bid - 0.001 or self.price > self.ask + 0.001
        return False
    
    def get_dark_pool_confidence(self) -> float:
        """Combined dark pool detection confidence"""
        confidence = 0.0
        
        # Condition codes are most reliable
        if self.is_dark_pool_by_conditions():
            confidence += 0.7
            
        # Outside spread is strong indicator
        if self.is_dark_pool_by_spread():
            confidence += 0.3
            
        # Large odd lots often dark
        if self.size % 100 != 0 and self.size > 1000:
            confidence += 0.1
            
        return min(confidence, 1.0)

@dataclass
class QuoteEvent(HistoricalEvent):
    """Historical quote event"""
    bid: float = 0.0
    ask: float = 0.0
    bid_size: int = 0
    ask_size: int = 0
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid
    
    @property
    def spread_bps(self) -> float:
        mid = (self.bid + self.ask) / 2
        return (self.spread / mid) * 10000 if mid > 0 else 0


class HistoricalDataLoader:
    """Loads historical data from JSON files"""
    
    def __init__(self, data_dir: str = '../simulation/data'):
        self.tick_dir = os.path.join(data_dir, 'real_ticks')
        self.l1_dir = os.path.join(data_dir, 'l1_historical')
        
    def get_available_symbols(self) -> List[str]:
        """Get list of symbols with data"""
        symbols = set()
        
        # Check tick files
        tick_files = glob.glob(os.path.join(self.tick_dir, '*_*.json'))
        for file in tick_files:
            # Extract symbol from filename (SYMBOL_YYYYMMDD.json)
            symbol = os.path.basename(file).split('_')[0]
            symbols.add(symbol)
            
        return sorted(list(symbols))
    
    def get_available_dates(self, symbol: str) -> List[str]:
        """Get available dates for symbol"""
        dates = []
        
        # Check tick files
        pattern = os.path.join(self.tick_dir, f"{symbol}_*.json")
        files = glob.glob(pattern)
        
        for file in files:
            # Extract date from filename
            date = os.path.basename(file).split('_')[1].replace('.json', '')
            dates.append(date)
            
        return sorted(dates)
    
    def load_day_events(self, symbol: str, date: str) -> List[HistoricalEvent]:
        """Load all events for a symbol/date"""
        events = []
        
        # Load tick data
        tick_file = os.path.join(self.tick_dir, f"{symbol}_{date}.json")
        l1_file = os.path.join(self.l1_dir, f"{symbol}_{date}_l1.json")
        
        if not os.path.exists(tick_file):
            logger.warning(f"No tick data for {symbol} on {date}")
            return events
            
        # Load ticks
        with open(tick_file, 'r') as f:
            tick_data = json.load(f)
            
        # Load L1 data if available
        l1_lookup = {}
        if os.path.exists(l1_file):
            with open(l1_file, 'r') as f:
                l1_data = json.load(f)
                # Create timestamp lookup
                if 'ticks' in l1_data:
                    for l1_tick in l1_data['ticks']:
                        l1_lookup[l1_tick['timestamp']] = l1_tick
                        
        # Process ticks
        sequence = 0
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
            if tick['timestamp'] in l1_lookup:
                l1_tick = l1_lookup[tick['timestamp']]
                bid = l1_tick.get('bid', bid)
                ask = l1_tick.get('ask', ask)
                
                # Also create quote event from L1
                quote_event = QuoteEvent(
                    timestamp=timestamp,
                    symbol=symbol,
                    sequence=sequence,
                    bid=bid,
                    ask=ask,
                    bid_size=l1_tick.get('bid_size', 100),
                    ask_size=l1_tick.get('ask_size', 100)
                )
                events.append(quote_event)
                sequence += 1
            
            # Create tick event
            tick_event = TickEvent(
                timestamp=timestamp,
                symbol=symbol,
                sequence=sequence,
                price=tick['price'],
                size=tick['size'],
                exchange=tick.get('exchange', ''),
                conditions=tick.get('conditions', ''),
                bid=bid,
                ask=ask
            )
            events.append(tick_event)
            sequence += 1
            
        logger.info(f"Loaded {len(events)} events for {symbol} on {date}")
        return events
    
    def load_date_range(self, symbols: List[str], start_date: str, 
                       end_date: str) -> List[HistoricalEvent]:
        """Load events for multiple symbols across date range"""
        all_events = []
        
        # Convert dates
        current = datetime.strptime(start_date, '%Y%m%d')
        end = datetime.strptime(end_date, '%Y%m%d')
        
        while current <= end:
            if current.weekday() < 5:  # Weekday
                date_str = current.strftime('%Y%m%d')
                
                for symbol in symbols:
                    events = self.load_day_events(symbol, date_str)
                    all_events.extend(events)
                    
            current += timedelta(days=1)
            
        # Sort by timestamp and sequence
        all_events.sort()
        
        logger.info(f"Loaded {len(all_events)} total events for {len(symbols)} symbols")
        return all_events


class TemporalKafkaStreamer:
    """Streams historical data to Kafka in temporal order"""
    
    def __init__(self, speed_multiplier: float = 1.0):
        """
        Args:
            speed_multiplier: 1.0 = real-time, 10.0 = 10x speed, 0 = as fast as possible
        """
        self.speed_multiplier = speed_multiplier
        self.producer = None
        self.start_time = None
        self.base_timestamp = None
        
        # Statistics
        self.stats = {
            'ticks_sent': 0,
            'quotes_sent': 0,
            'dark_pool_detected': 0,
            'events_processed': 0
        }
        
    async def start(self):
        """Start Kafka producer"""
        self.producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode(),
            compression_type='snappy',
            linger_ms=5,  # Lower latency
            batch_size=16384
        )
        await self.producer.start()
        logger.info("Kafka producer started")
        
    async def stop(self):
        """Stop Kafka producer"""
        if self.producer:
            await self.producer.stop()
            
    async def stream_events(self, events: List[HistoricalEvent]):
        """Stream events maintaining temporal order"""
        if not events:
            logger.warning("No events to stream")
            return
            
        # Initialize timing
        self.start_time = asyncio.get_event_loop().time()
        self.base_timestamp = events[0].timestamp
        
        logger.info(f"Streaming {len(events)} events starting from {self.base_timestamp}")
        
        # Create event heap
        event_heap = list(events)
        heapq.heapify(event_heap)
        
        # Process events in order
        while event_heap:
            event = heapq.heappop(event_heap)
            
            # Wait if needed to maintain temporal order
            if self.speed_multiplier > 0:
                await self._wait_until(event.timestamp)
                
            # Process event
            await self._process_event(event)
            
            self.stats['events_processed'] += 1
            
            # Log progress every 1000 events
            if self.stats['events_processed'] % 1000 == 0:
                self._log_progress()
                
        # Final stats
        self._log_final_stats()
        
    async def _wait_until(self, event_time: datetime):
        """Wait until it's time to send this event"""
        # Calculate how long since base timestamp
        event_offset = (event_time - self.base_timestamp).total_seconds()
        
        # Scale by speed multiplier
        target_elapsed = event_offset / self.speed_multiplier
        
        # How long since we started
        current_elapsed = asyncio.get_event_loop().time() - self.start_time
        
        # Wait if needed
        wait_time = target_elapsed - current_elapsed
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            
    async def _process_event(self, event: HistoricalEvent):
        """Process and send event to appropriate Kafka topic"""
        if isinstance(event, TickEvent):
            await self._process_tick(event)
        elif isinstance(event, QuoteEvent):
            await self._process_quote(event)
            
    async def _process_tick(self, tick: TickEvent):
        """Process tick event"""
        # Convert to Kafka message format
        tick_msg = {
            'symbol': tick.symbol,
            'timestamp': tick.timestamp.isoformat(),
            'price': tick.price,
            'size': tick.size,
            'exchange': tick.exchange,
            'conditions': tick.conditions,
            'bid': tick.bid,
            'ask': tick.ask
        }
        
        # Send to tick topic
        await self.producer.send(
            TICK_TOPIC,
            key=tick.symbol.encode(),
            value=tick_msg
        )
        self.stats['ticks_sent'] += 1
        
        # Check for dark pool and send separate alert
        dark_confidence = tick.get_dark_pool_confidence()
        if dark_confidence > 0.5:
            await self._send_dark_pool_alert(tick, dark_confidence)
            
    async def _process_quote(self, quote: QuoteEvent):
        """Process quote event"""
        # Convert to Kafka message format
        quote_msg = {
            'symbol': quote.symbol,
            'timestamp': quote.timestamp.isoformat(),
            'bid': quote.bid,
            'ask': quote.ask,
            'bid_size': quote.bid_size,
            'ask_size': quote.ask_size,
            'spread': quote.spread,
            'spread_bps': quote.spread_bps
        }
        
        # Send to quote topic
        await self.producer.send(
            QUOTE_TOPIC,
            key=quote.symbol.encode(),
            value=quote_msg
        )
        self.stats['quotes_sent'] += 1
        
    async def _send_dark_pool_alert(self, tick: TickEvent, confidence: float):
        """Send dark pool detection alert"""
        alert_msg = {
            'symbol': tick.symbol,
            'timestamp': tick.timestamp.isoformat(),
            'price': tick.price,
            'size': tick.size,
            'confidence': confidence,
            'detection_methods': {
                'condition_codes': tick.is_dark_pool_by_conditions(),
                'outside_spread': tick.is_dark_pool_by_spread()
            },
            'bid': tick.bid,
            'ask': tick.ask,
            'conditions': tick.conditions
        }
        
        await self.producer.send(
            DARK_POOL_TOPIC,
            key=tick.symbol.encode(),
            value=alert_msg
        )
        self.stats['dark_pool_detected'] += 1
        
        # Log significant dark pool activity
        if tick.size > 10000:
            logger.warning(f"🌑 DARK POOL: {tick.symbol} - {tick.size:,} shares @ ${tick.price:.2f} "
                         f"(confidence: {confidence:.0%})")
            
    def _log_progress(self):
        """Log streaming progress"""
        elapsed = asyncio.get_event_loop().time() - self.start_time
        events_per_sec = self.stats['events_processed'] / elapsed if elapsed > 0 else 0
        
        logger.info(f"Progress: {self.stats['events_processed']:,} events, "
                   f"{events_per_sec:.0f} events/sec, "
                   f"{self.stats['dark_pool_detected']} dark pool trades")
        
    def _log_final_stats(self):
        """Log final statistics"""
        logger.info("Streaming complete!")
        logger.info(f"  Total events: {self.stats['events_processed']:,}")
        logger.info(f"  Ticks sent: {self.stats['ticks_sent']:,}")
        logger.info(f"  Quotes sent: {self.stats['quotes_sent']:,}")
        logger.info(f"  Dark pool detected: {self.stats['dark_pool_detected']:,}")


async def main():
    """Main entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize components
    loader = HistoricalDataLoader()
    streamer = TemporalKafkaStreamer(speed_multiplier=10.0)  # 10x speed
    
    # Get available data
    symbols = loader.get_available_symbols()
    logger.info(f"Found data for {len(symbols)} symbols: {symbols[:5]}...")
    
    if not symbols:
        logger.error("No historical data found!")
        return
        
    # Use first 10 symbols for demo
    test_symbols = symbols[:10]
    
    # Get date range (use available dates)
    dates = loader.get_available_dates(test_symbols[0])
    if len(dates) >= 2:
        start_date = dates[0]
        end_date = dates[1]
    else:
        logger.error("Need at least 2 days of data")
        return
        
    logger.info(f"Loading data from {start_date} to {end_date}")
    
    # Load historical data
    events = loader.load_date_range(test_symbols, start_date, end_date)
    
    # Start streaming
    await streamer.start()
    
    try:
        await streamer.stream_events(events)
    except KeyboardInterrupt:
        logger.info("Streaming interrupted")
    finally:
        await streamer.stop()


if __name__ == "__main__":
    asyncio.run(main())