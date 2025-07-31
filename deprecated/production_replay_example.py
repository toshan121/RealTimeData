#!/usr/bin/env python3
"""
PRODUCTION-READY MOCK IQFEED REPLAY SYSTEM
Ready for market open - tested and working!

Supports:
- Custom date selection (any date with ClickHouse data)
- Custom ticker list (any symbols in ClickHouse)
- L1 Quotes, L2 Order Book, and Trades
- Perfect temporal synchronization
- Exact IQFeed message formats
"""

import time
import logging
from datetime import datetime
from typing import List, Optional
from ingestion.clickhouse_mock_iqfeed import ClickHouseMockIQFeed, MockDataMode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProductionMockIQFeeder:
    """Production-ready mock IQFeed system with custom date/ticker selection."""
    
    def __init__(
        self,
        date: str = '2025-07-29',  # YYYY-MM-DD format
        symbols: List[str] = None,
        playback_speed: float = 1.0,  # 1.0 = real-time, 10.0 = 10x speed
        include_l2: bool = True,
        include_trades: bool = True,
        include_quotes: bool = True
    ):
        """
        Initialize production mock IQFeed system.
        
        Args:
            date: Date to replay (YYYY-MM-DD)
            symbols: List of symbols to replay
            playback_speed: Playback speed multiplier
            include_l2: Include L2 order book data
            include_trades: Include trade data
            include_quotes: Include L1 quote data
        """
        self.date = date
        self.symbols = symbols or ['TSLA', 'AAPL', 'MSFT', 'GOOGL', 'NVDA']
        self.playback_speed = playback_speed
        self.include_l2 = include_l2
        self.include_trades = include_trades
        self.include_quotes = include_quotes
        
        # Initialize mock IQFeed producer
        self.producer = ClickHouseMockIQFeed(
            mode=MockDataMode.HISTORICAL_REPLAY,
            playback_speed=playback_speed,
            start_date=date,
            end_date=date  # Single day replay
        )
        
        self.connected = False
        self.subscribed = False
    
    def connect(self) -> bool:
        """Connect to ClickHouse and initialize producer."""
        try:
            logger.info(f"🚀 Connecting to mock IQFeed for {self.date}")
            result = self.producer.connect()
            
            if result['success']:
                self.connected = True
                logger.info(f"✅ Connected successfully!")
                logger.info(f"   Session: {result['session_id']}")
                logger.info(f"   Data range: {result['data_range']}")
                return True
            else:
                logger.error(f"❌ Connection failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False
    
    def subscribe_symbols(self) -> bool:
        """Subscribe to all data types for specified symbols."""
        if not self.connected:
            logger.error("❌ Not connected - call connect() first")
            return False
        
        try:
            logger.info(f"📡 Subscribing to {len(self.symbols)} symbols...")
            
            for symbol in self.symbols:
                if self.include_l2:
                    self.producer.subscribe_l2_data(symbol)
                if self.include_trades:
                    self.producer.subscribe_trades(symbol)
                if self.include_quotes:
                    self.producer.subscribe_quotes(symbol)
                
                logger.info(f"   ✅ {symbol}: L2={self.include_l2}, "
                          f"Trades={self.include_trades}, Quotes={self.include_quotes}")
            
            self.subscribed = True
            
            # Wait a moment for data loading
            time.sleep(2)
            
            # Check status
            status = self.producer.get_status()
            logger.info(f"📊 Status: {status['active_subscriptions']} active subscriptions")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Subscription error: {e}")
            return False
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[dict]:
        """
        Get next message in exact IQFeed format.
        
        Returns:
            Dict with keys: symbol, message_type, raw_message, timestamp
            or None if no message available
        """
        if not self.subscribed:
            logger.error("❌ Not subscribed - call subscribe_symbols() first")
            return None
        
        return self.producer.get_next_message(timeout=timeout)
    
    def run_replay_demo(self, duration_seconds: int = 30):
        """Run a demo replay showing message types and rates."""
        if not self.subscribed:
            logger.error("❌ Not subscribed - call subscribe_symbols() first")
            return
        
        logger.info(f"🎬 Starting {duration_seconds}s demo replay...")
        
        start_time = time.time()
        message_counts = {'T': 0, 'Q': 0, 'U': 0, 'Other': 0}
        total_messages = 0
        
        while time.time() - start_time < duration_seconds:
            message = self.get_next_message(timeout=0.1)
            
            if message:
                total_messages += 1
                raw_msg = message.get('raw_message', '')
                msg_type = raw_msg.split(',')[0] if raw_msg else 'Other'
                
                message_counts[msg_type] = message_counts.get(msg_type, 0) + 1
                
                # Show first few messages of each type
                if message_counts[msg_type] <= 2:
                    logger.info(f"   📨 {msg_type}: {raw_msg[:80]}...")
                
                # Periodic stats
                if total_messages % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = total_messages / elapsed if elapsed > 0 else 0
                    logger.info(f"   📊 {total_messages} messages ({rate:.1f} msg/s)")
        
        # Final statistics
        elapsed = time.time() - start_time
        rate = total_messages / elapsed if elapsed > 0 else 0
        
        logger.info(f"🎯 DEMO COMPLETE:")
        logger.info(f"   - Total messages: {total_messages}")
        logger.info(f"   - Rate: {rate:.1f} messages/second")
        logger.info(f"   - Trades (T): {message_counts.get('T', 0)}")
        logger.info(f"   - Quotes (Q): {message_counts.get('Q', 0)}")
        logger.info(f"   - L2 Updates (U): {message_counts.get('U', 0)}")
    
    def disconnect(self):
        """Disconnect and cleanup."""
        if self.connected:
            logger.info("🔌 Disconnecting...")
            self.producer.disconnect()
            self.connected = False
            self.subscribed = False
            logger.info("✅ Disconnected")


def main():
    """Example usage for production."""
    print("🚀 PRODUCTION MOCK IQFEED SYSTEM")
    print("=" * 80)
    
    # Example 1: Default replay (recent data)
    print("\n📅 Example 1: Default settings")
    feeder = ProductionMockIQFeeder(
        date='2025-07-29',
        symbols=['TSLA', 'AAPL', 'MSFT'],
        playback_speed=5.0  # 5x speed for demo
    )
    
    if feeder.connect() and feeder.subscribe_symbols():
        feeder.run_replay_demo(duration_seconds=15)
    feeder.disconnect()
    
    print("\n" + "=" * 80)
    print("📊 PRODUCTION USAGE:")
    print("""
# For your GPU functions:
feeder = ProductionMockIQFeeder(
    date='2025-07-29',           # Any date with data
    symbols=['TSLA', 'AAPL'],    # Your ticker list
    playback_speed=1.0,          # Real-time
    include_l2=True,             # L2 order book
    include_trades=True,         # Trade executions
    include_quotes=True          # L1 quotes
)

feeder.connect()
feeder.subscribe_symbols()

# Get messages in exact IQFeed format
while True:
    message = feeder.get_next_message()
    if message:
        # Feed to your GPU functions
        print(message['raw_message'])
    """)
    print("=" * 80)


if __name__ == "__main__":
    main()