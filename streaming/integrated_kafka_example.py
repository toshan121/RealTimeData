#!/usr/bin/env python3
"""
Integrated Kafka Streaming Example
- Demonstrates complete flow from historical data to GPU detection
- Shows dark pool detection in action
- Includes Redis state management
"""

import asyncio
import logging
from typing import List
import signal
import sys

# Import our components
from historical_kafka_streamer import HistoricalDataLoader, TemporalKafkaStreamer
from kafka_streaming_pipeline import StreamingAccumulationProcessor, RedisStateManager

logger = logging.getLogger(__name__)

class IntegratedStreamingSystem:
    """Complete streaming system from historical data to alerts"""
    
    def __init__(self, symbols: List[str], speed: float = 10.0):
        self.symbols = symbols
        self.speed = speed
        
        # Components
        self.data_loader = HistoricalDataLoader()
        self.kafka_streamer = TemporalKafkaStreamer(speed_multiplier=speed)
        self.gpu_processor = StreamingAccumulationProcessor(symbols)
        self.redis_state = RedisStateManager()
        
        # Control
        self.running = True
        
    async def initialize(self):
        """Initialize all components"""
        logger.info("Initializing integrated streaming system...")
        
        # Start Redis
        await self.redis_state.connect()
        
        # Load and store baselines
        await self._initialize_baselines()
        
        # Start Kafka streamer
        await self.kafka_streamer.start()
        
        # Start GPU processor
        await self.gpu_processor.start()
        
        logger.info("System initialized successfully")
        
    async def _initialize_baselines(self):
        """Initialize historical baselines in Redis"""
        logger.info("Calculating historical baselines...")
        
        # For each symbol, calculate baseline from first day
        for symbol in self.symbols:
            dates = self.data_loader.get_available_dates(symbol)
            if dates:
                # Load first day for baseline
                events = self.data_loader.load_day_events(symbol, dates[0])
                
                # Calculate simple baseline
                volumes = []
                spreads = []
                dark_count = 0
                
                for event in events:
                    if hasattr(event, 'size'):  # Tick event
                        volumes.append(event.size)
                        if event.get_dark_pool_confidence() > 0.5:
                            dark_count += 1
                    elif hasattr(event, 'spread'):  # Quote event
                        spreads.append(event.spread)
                        
                # Store baseline
                if volumes:
                    baseline = {
                        'volume_mean': sum(volumes) / len(volumes),
                        'volume_std': max(100, sum(volumes) / len(volumes) * 0.5),
                        'flow_mean': 0,
                        'flow_std': 100,
                        'spread_mean': sum(spreads) / len(spreads) if spreads else 0.01,
                        'spread_std': 0.005,
                        'dark_mean': dark_count / len(volumes) if volumes else 0.1,
                        'dark_std': 0.05
                    }
                    
                    await self.redis_state.store_baseline(symbol, baseline)
                    logger.info(f"Stored baseline for {symbol}: avg volume={baseline['volume_mean']:.0f}")
                    
    async def run(self):
        """Run the complete system"""
        # Get available dates
        dates = self.data_loader.get_available_dates(self.symbols[0])
        if len(dates) < 2:
            logger.error("Need at least 2 days of data")
            return
            
        # Use days 2-3 for streaming (day 1 was for baseline)
        start_date = dates[1] if len(dates) > 1 else dates[0]
        end_date = dates[2] if len(dates) > 2 else dates[1]
        
        logger.info(f"Streaming data from {start_date} to {end_date}")
        
        # Load events
        events = self.data_loader.load_date_range(self.symbols, start_date, end_date)
        logger.info(f"Loaded {len(events)} events to stream")
        
        # Run streaming and processing concurrently
        streaming_task = asyncio.create_task(
            self.kafka_streamer.stream_events(events)
        )
        processing_task = asyncio.create_task(
            self.gpu_processor.process_messages()
        )
        
        # Wait for streaming to complete or interruption
        try:
            await streaming_task
            logger.info("Streaming complete, waiting for final processing...")
            
            # Give processor time to handle final messages
            await asyncio.sleep(5)
            
            # Cancel processing
            processing_task.cancel()
            
        except asyncio.CancelledError:
            logger.info("System interrupted")
            
    async def shutdown(self):
        """Shutdown all components"""
        logger.info("Shutting down system...")
        
        await self.kafka_streamer.stop()
        await self.gpu_processor.stop()
        await self.redis_state.disconnect()
        
        logger.info("System shutdown complete")
        
    def get_stats(self):
        """Get system statistics"""
        stats = {
            'streamer': self.kafka_streamer.stats,
            'processor': self.gpu_processor.stats
        }
        return stats


async def demonstrate_dark_pool_detection():
    """Demonstrate dark pool detection capabilities"""
    logger.info("\n" + "="*60)
    logger.info("DARK POOL DETECTION DEMONSTRATION")
    logger.info("="*60)
    
    # Create minimal example
    from historical_kafka_streamer import TickEvent
    from datetime import datetime
    
    # Example 1: IQFeed condition code
    tick1 = TickEvent(
        timestamp=datetime.now(),
        symbol="AAPL",
        price=150.05,
        size=10000,
        conditions="D",  # Dark pool indicator
        bid=150.00,
        ask=150.10
    )
    
    logger.info(f"\nExample 1 - IQFeed Dark Pool Code:")
    logger.info(f"  Trade: {tick1.size} shares @ ${tick1.price}")
    logger.info(f"  Conditions: {tick1.conditions}")
    logger.info(f"  Dark pool by conditions: {tick1.is_dark_pool_by_conditions()}")
    logger.info(f"  Confidence: {tick1.get_dark_pool_confidence():.0%}")
    
    # Example 2: Trade outside NBBO
    tick2 = TickEvent(
        timestamp=datetime.now(),
        symbol="AAPL",
        price=149.95,  # Below bid!
        size=5000,
        conditions="",
        bid=150.00,
        ask=150.10
    )
    
    logger.info(f"\nExample 2 - Trade Outside NBBO:")
    logger.info(f"  Trade: {tick2.size} shares @ ${tick2.price}")
    logger.info(f"  NBBO: ${tick2.bid} x ${tick2.ask}")
    logger.info(f"  Dark pool by spread: {tick2.is_dark_pool_by_spread()}")
    logger.info(f"  Confidence: {tick2.get_dark_pool_confidence():.0%}")
    
    # Example 3: Both indicators
    tick3 = TickEvent(
        timestamp=datetime.now(),
        symbol="AAPL",
        price=150.15,  # Above ask
        size=25000,
        conditions="TRF",  # Trade Reporting Facility
        bid=150.00,
        ask=150.10
    )
    
    logger.info(f"\nExample 3 - Multiple Dark Pool Indicators:")
    logger.info(f"  Trade: {tick3.size} shares @ ${tick3.price}")
    logger.info(f"  NBBO: ${tick3.bid} x ${tick3.ask}")
    logger.info(f"  Conditions: {tick3.conditions}")
    logger.info(f"  Dark pool confidence: {tick3.get_dark_pool_confidence():.0%}")
    logger.info("="*60 + "\n")


async def main():
    """Main entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # First demonstrate dark pool detection
    await demonstrate_dark_pool_detection()
    
    # Get available symbols
    loader = HistoricalDataLoader()
    symbols = loader.get_available_symbols()
    
    if not symbols:
        logger.error("No historical data found! Please ensure data files exist in data/real_ticks/")
        return
        
    # Use up to 10 symbols
    test_symbols = symbols[:min(10, len(symbols))]
    logger.info(f"Using symbols: {test_symbols}")
    
    # Create integrated system
    system = IntegratedStreamingSystem(
        symbols=test_symbols,
        speed=100.0  # 100x speed for demo
    )
    
    # Setup signal handler
    def signal_handler(sig, frame):
        logger.info("Interrupt received, shutting down...")
        asyncio.create_task(system.shutdown())
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Initialize
        await system.initialize()
        
        # Run
        await system.run()
        
        # Show final stats
        stats = system.get_stats()
        logger.info("\n" + "="*60)
        logger.info("FINAL STATISTICS")
        logger.info("="*60)
        logger.info(f"Streamer stats: {stats['streamer']}")
        logger.info(f"Processor stats: {stats['processor']}")
        
    finally:
        await system.shutdown()


if __name__ == "__main__":
    logger.info("""
    ╔══════════════════════════════════════════════════════════╗
    ║  Integrated Kafka Streaming System                       ║
    ║  - Reads historical tick/L1 JSON data                    ║
    ║  - Streams to Kafka maintaining temporal order           ║
    ║  - Detects dark pools using 3 methods                    ║
    ║  - Processes with GPU acceleration                       ║
    ║  - Stores state in Redis                                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main())