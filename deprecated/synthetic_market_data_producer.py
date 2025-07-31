"""
Synthetic Market Data Producer

Creates realistic market data by:
1. Using real ClickHouse data as templates
2. Applying controlled variations (price walks, volume changes)
3. Generating data for unlimited symbols
4. Maintaining realistic temporal patterns and intensity
5. Supporting stress testing with 2000+ symbols

Perfect for testing GPU functions when you need more data than available in ClickHouse.
"""

import logging
import threading
import time
import random
import math
import queue
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import clickhouse_connect

from clickhouse_mock_iqfeed import MockMessage
from exceptions import ProcessingError, DataValidationError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SynthesisMode(Enum):
    """Data synthesis modes."""
    TEMPLATE_BASED = "template_based"      # Use real data as templates with variations
    PROCEDURAL = "procedural"              # Generate from scratch with realistic patterns
    HYBRID = "hybrid"                      # Mix template data with procedural generation


@dataclass
class MarketTemplate:
    """Template extracted from real market data."""
    symbol: str
    base_price: float
    price_volatility: float
    spread_avg: float
    spread_volatility: float
    volume_avg: int
    volume_volatility: float
    tick_frequency: float  # Messages per second
    l2_depth_levels: int
    quote_trade_ratio: float  # Quotes per trade
    l2_quote_ratio: float     # L2 updates per quote
    

@dataclass
class SyntheticSymbolState:
    """Current state for synthetic symbol generation."""
    symbol: str
    current_price: float
    current_bid: float
    current_ask: float
    current_spread: float
    price_trend: float  # Drift direction
    volatility: float
    last_trade_size: int
    total_volume: int
    tick_counter: int
    l2_book: Dict[int, Dict[str, Tuple[float, int]]]  # level -> {side: (price, size)}
    last_message_time: datetime
    

class SyntheticMarketDataProducer:
    """
    Produces unlimited synthetic market data based on real patterns.
    
    Can scale to 2000+ symbols for stress testing while maintaining
    realistic temporal intensity and market microstructure patterns.
    """
    
    def __init__(
        self,
        mode: SynthesisMode = SynthesisMode.TEMPLATE_BASED,
        clickhouse_host: str = 'localhost',
        clickhouse_port: int = 8123,
        clickhouse_database: str = 'l2_market_data',
        clickhouse_username: str = 'l2_user',
        clickhouse_password: str = 'l2_secure_pass',
        target_symbols: List[str] = None,
        synthesis_duration_hours: float = 8.0,  # Market day
        time_acceleration: float = 1.0,  # 1.0 = real-time
        messages_per_second_per_symbol: float = 10.0,  # Realistic intensity
        price_variation_pct: float = 2.0,  # Max price variation %
        volume_variation_pct: float = 50.0,  # Max volume variation %
        enable_trends: bool = True,  # Enable price trends
        enable_volatility_clustering: bool = True  # Realistic vol patterns
    ):
        """
        Initialize synthetic market data producer.
        
        Args:
            mode: Synthesis mode (template-based, procedural, hybrid)
            target_symbols: Symbols to generate (can be unlimited)
            synthesis_duration_hours: How many hours of data to generate
            time_acceleration: Speed multiplier (10.0 = 10x real-time)
            messages_per_second_per_symbol: Message intensity per symbol
            price_variation_pct: Maximum price variation percentage
            volume_variation_pct: Maximum volume variation percentage
            enable_trends: Enable realistic price trends
            enable_volatility_clustering: Enable volatility clustering
        """
        # Configuration
        self.mode = mode
        self.target_symbols = target_symbols or self._generate_symbol_list(100)
        self.synthesis_duration_hours = synthesis_duration_hours
        self.time_acceleration = time_acceleration
        self.msg_rate_per_symbol = messages_per_second_per_symbol
        self.price_variation_pct = price_variation_pct
        self.volume_variation_pct = volume_variation_pct
        self.enable_trends = enable_trends
        self.enable_volatility_clustering = enable_volatility_clustering
        
        # ClickHouse connection for templates
        self.clickhouse_host = clickhouse_host
        self.clickhouse_port = clickhouse_port
        self.clickhouse_database = clickhouse_database
        self.clickhouse_username = clickhouse_username
        self.clickhouse_password = clickhouse_password
        self._client: Optional[clickhouse_connect.driver.Client] = None
        
        # Templates and synthesis
        self.templates: Dict[str, MarketTemplate] = {}
        self.symbol_states: Dict[str, SyntheticSymbolState] = {}
        
        # Output and control
        self._output_queue: queue.Queue = queue.Queue(maxsize=100000)
        self._running = False
        self._producer_threads: List[threading.Thread] = []
        self._start_time: Optional[datetime] = None
        self._synthetic_start_time: Optional[datetime] = None
        
        # Statistics
        self._messages_generated = 0
        self._stats_lock = threading.Lock()
        
        logger.info(f"Synthetic market data producer initialized:")
        logger.info(f"  Mode: {mode.value}")
        logger.info(f"  Symbols: {len(self.target_symbols)}")
        logger.info(f"  Duration: {synthesis_duration_hours:.1f} hours")
        logger.info(f"  Rate: {messages_per_second_per_symbol:.1f} msg/s/symbol")
        logger.info(f"  Total rate: {len(self.target_symbols) * messages_per_second_per_symbol:.0f} msg/s")
    
    def _generate_symbol_list(self, count: int) -> List[str]:
        """Generate a list of synthetic symbol names."""
        # Common prefixes for realistic symbols
        prefixes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'M', 'N', 'P', 'R', 'S', 'T', 'V', 'W', 'X', 'Z']
        suffixes = ['X', 'Y', 'Z', 'T', 'C', 'P', 'M', 'N', 'L', 'R']
        
        symbols = []
        for i in range(count):
            if i < 50:  # Some real-looking symbols
                symbols.append(f"{random.choice(prefixes)}{random.choice(['A', 'E', 'I', 'O'])}{random.choice(suffixes)}{random.choice(suffixes)}")
            else:  # More systematic for large counts
                symbols.append(f"SYN{i:04d}")
        
        return symbols
    
    def connect(self) -> bool:
        """Connect to ClickHouse for template extraction."""
        try:
            if self.mode == SynthesisMode.PROCEDURAL:
                logger.info("Procedural mode - skipping ClickHouse connection")
                return True
            
            logger.info("Connecting to ClickHouse for template extraction")
            
            self._client = clickhouse_connect.get_client(
                host=self.clickhouse_host,
                port=self.clickhouse_port,
                database=self.clickhouse_database,
                username=self.clickhouse_username,
                password=self.clickhouse_password,
                connect_timeout=30,
                send_receive_timeout=120,
                interface='http',
                compress=True
            )
            
            # Test connection
            result = self._client.query("SELECT 1 as test")
            if not (result.result_rows and result.result_rows[0][0] == 1):
                raise ProcessingError("Connection test failed", "synthetic_producer")
            
            logger.info("✅ Connected to ClickHouse successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to ClickHouse: {e}")
            return False
    
    def extract_templates(self) -> bool:
        """Extract market data templates from ClickHouse."""
        if self.mode == SynthesisMode.PROCEDURAL:
            logger.info("Procedural mode - creating default templates")
            self._create_default_templates()
            return True
        
        try:
            logger.info("Extracting market data templates from ClickHouse...")
            
            # Get available symbols and their characteristics
            template_query = """
            WITH trade_stats AS (
                SELECT 
                    symbol,
                    count() as trade_count,
                    avg(trade_price) as avg_price,
                    stddevSamp(trade_price) as price_volatility,
                    avg(trade_size) as avg_volume,
                    stddevSamp(trade_size) as volume_volatility
                FROM trades
                WHERE date >= '2025-07-29'
                GROUP BY symbol
            ),
            quote_stats AS (
                SELECT 
                    symbol,
                    count() as quote_count,
                    avg(ask_price - bid_price) as avg_spread,
                    stddevSamp(ask_price - bid_price) as spread_volatility
                FROM quotes
                WHERE date >= '2025-07-29'
                GROUP BY symbol
            ),
            l2_stats AS (
                SELECT 
                    symbol,
                    count() as l2_count,
                    max(level) as max_level
                FROM l2_updates  
                WHERE date >= '2025-07-29'
                GROUP BY symbol
            )
            SELECT 
                t.symbol,
                t.avg_price,
                t.price_volatility,
                q.avg_spread,
                q.spread_volatility,
                t.avg_volume,
                t.volume_volatility,
                t.trade_count,
                q.quote_count,
                l.l2_count,
                l.max_level
            FROM trade_stats t
            LEFT JOIN quote_stats q ON t.symbol = q.symbol
            LEFT JOIN l2_stats l ON t.symbol = l.symbol
            WHERE t.trade_count > 10
            ORDER BY t.trade_count DESC
            """
            
            result = self._client.query(template_query)
            
            if not result.result_rows:
                logger.warning("No template data found, using defaults")
                self._create_default_templates()
                return True
            
            # Process template data
            for row in result.result_rows:
                symbol = row[0]
                avg_price = float(row[1]) if row[1] else 100.0
                price_vol = float(row[2]) if row[2] else 2.0
                avg_spread = float(row[3]) if row[3] else 0.01
                spread_vol = float(row[4]) if row[4] else 0.005
                avg_volume = int(row[5]) if row[5] else 100
                volume_vol = float(row[6]) if row[6] else 50.0
                trade_count = int(row[7]) if row[7] else 10
                quote_count = int(row[8]) if row[8] else 20
                l2_count = int(row[9]) if row[9] else 30
                max_level = int(row[10]) if row[10] else 5
                
                # Calculate derived metrics
                total_messages = trade_count + quote_count + l2_count
                tick_frequency = total_messages / (8 * 3600)  # Assume 8-hour day
                quote_trade_ratio = quote_count / max(trade_count, 1)
                l2_quote_ratio = l2_count / max(quote_count, 1)
                
                template = MarketTemplate(
                    symbol=symbol,
                    base_price=avg_price,
                    price_volatility=price_vol,
                    spread_avg=avg_spread,
                    spread_volatility=spread_vol,
                    volume_avg=avg_volume,
                    volume_volatility=volume_vol,
                    tick_frequency=tick_frequency,
                    l2_depth_levels=min(max_level, 10),
                    quote_trade_ratio=quote_trade_ratio,
                    l2_quote_ratio=l2_quote_ratio
                )
                
                self.templates[symbol] = template
            
            logger.info(f"✅ Extracted {len(self.templates)} market templates")
            
            # Use templates to initialize synthetic symbols
            self._initialize_synthetic_symbols()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to extract templates: {e}")
            return False
    
    def _create_default_templates(self):
        """Create default templates for procedural generation."""
        base_templates = [
            # Large cap tech-like
            MarketTemplate("TEMPLATE_LARGE", 150.0, 3.0, 0.01, 0.005, 500, 200.0, 15.0, 5, 2.0, 1.5),
            # Mid cap growth-like  
            MarketTemplate("TEMPLATE_MID", 75.0, 5.0, 0.02, 0.01, 300, 150.0, 10.0, 4, 1.8, 1.2),
            # Small cap volatile-like
            MarketTemplate("TEMPLATE_SMALL", 25.0, 8.0, 0.05, 0.02, 200, 100.0, 8.0, 3, 1.5, 1.0),
            # Penny stock-like
            MarketTemplate("TEMPLATE_PENNY", 5.0, 15.0, 0.10, 0.05, 1000, 500.0, 5.0, 2, 1.2, 0.8)
        ]
        
        for template in base_templates:
            self.templates[template.symbol] = template
        
        logger.info(f"✅ Created {len(base_templates)} default templates")
        self._initialize_synthetic_symbols()
    
    def _initialize_synthetic_symbols(self):
        """Initialize synthetic symbol states."""
        logger.info(f"Initializing {len(self.target_symbols)} synthetic symbols...")
        
        for symbol in self.target_symbols:
            # Choose a template (cycle through available templates)
            template_key = list(self.templates.keys())[hash(symbol) % len(self.templates)]
            template = self.templates[template_key]
            
            # Add controlled variation to base parameters
            price_factor = 1.0 + random.uniform(-0.2, 0.2)  # ±20% price variation
            vol_factor = 1.0 + random.uniform(-0.3, 0.3)    # ±30% volatility variation
            
            base_price = template.base_price * price_factor
            spread = template.spread_avg * (1.0 + random.uniform(-0.5, 0.5))
            
            # Initialize L2 book
            l2_book = {}
            for level in range(template.l2_depth_levels):
                bid_price = base_price - spread * (level + 1)
                ask_price = base_price + spread * (level + 1)
                size = random.randint(100, 1000)
                
                l2_book[level] = {
                    'bid': (bid_price, size),
                    'ask': (ask_price, size)
                }
            
            state = SyntheticSymbolState(
                symbol=symbol,
                current_price=base_price,
                current_bid=base_price - spread/2,
                current_ask=base_price + spread/2,
                current_spread=spread,
                price_trend=random.uniform(-0.001, 0.001) if self.enable_trends else 0.0,
                volatility=template.price_volatility * vol_factor,
                last_trade_size=template.volume_avg,
                total_volume=0,
                tick_counter=0,
                l2_book=l2_book,
                last_message_time=datetime.now(timezone.utc)
            )
            
            self.symbol_states[symbol] = state
        
        logger.info(f"✅ Initialized {len(self.symbol_states)} synthetic symbols")
    
    def start_synthesis(self) -> bool:
        """Start synthetic data generation."""
        if not self.symbol_states:
            logger.error("❌ No symbols initialized - call extract_templates() first")
            return False
        
        logger.info("🚀 Starting synthetic market data generation")
        
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        self._synthetic_start_time = datetime.now(timezone.utc)
        
        # Create producer threads (one per symbol or grouped for efficiency)
        symbols_per_thread = max(1, len(self.target_symbols) // 50)  # Max 50 threads
        symbol_chunks = [
            self.target_symbols[i:i + symbols_per_thread]
            for i in range(0, len(self.target_symbols), symbols_per_thread)
        ]
        
        for i, symbol_chunk in enumerate(symbol_chunks):
            thread = threading.Thread(
                target=self._synthesis_worker,
                args=(symbol_chunk, i),
                name=f"synth-worker-{i}",
                daemon=True
            )
            thread.start()
            self._producer_threads.append(thread)
        
        logger.info(f"✅ Started {len(self._producer_threads)} synthesis threads")
        logger.info(f"   Expected rate: {len(self.target_symbols) * self.msg_rate_per_symbol:.0f} messages/second")
        
        return True
    
    def _synthesis_worker(self, symbols: List[str], worker_id: int):
        """Worker thread for synthetic data generation."""
        logger.info(f"Synthesis worker {worker_id} started for {len(symbols)} symbols")
        
        # Calculate timing
        interval_per_symbol = 1.0 / (self.msg_rate_per_symbol * self.time_acceleration)
        
        next_message_times = {
            symbol: datetime.now(timezone.utc) + timedelta(seconds=random.uniform(0, interval_per_symbol))
            for symbol in symbols
        }
        
        while self._running:
            current_time = datetime.now(timezone.utc)
            
            # Check if synthesis duration exceeded
            if (current_time - self._start_time).total_seconds() > self.synthesis_duration_hours * 3600:
                logger.info(f"Worker {worker_id}: Synthesis duration completed")
                break
            
            for symbol in symbols:
                if current_time >= next_message_times[symbol]:
                    # Generate next message for this symbol
                    message = self._generate_synthetic_message(symbol, current_time)
                    
                    if message:
                        try:
                            self._output_queue.put_nowait(message)
                            with self._stats_lock:
                                self._messages_generated += 1
                        except queue.Full:
                            pass  # Drop message if queue full
                    
                    # Schedule next message
                    next_interval = interval_per_symbol * random.uniform(0.5, 1.5)  # Add jitter
                    next_message_times[symbol] = current_time + timedelta(seconds=next_interval)
            
            # Small sleep to prevent busy waiting
            time.sleep(0.001)
        
        logger.info(f"Synthesis worker {worker_id} stopped")
    
    def _generate_synthetic_message(self, symbol: str, current_time: datetime) -> Optional[Dict[str, Any]]:
        """Generate a single synthetic message for a symbol."""
        state = self.symbol_states[symbol]
        template = self.templates[list(self.templates.keys())[hash(symbol) % len(self.templates)]]
        
        # Update symbol state with controlled random walk
        self._update_symbol_state(state, template)
        
        # Choose message type based on template ratios
        rand = random.random()
        
        if rand < 0.4:  # 40% trades
            return self._generate_trade_message(state, current_time)
        elif rand < 0.7:  # 30% quotes
            return self._generate_quote_message(state, current_time)
        else:  # 30% L2 updates
            return self._generate_l2_message(state, current_time)
    
    def _update_symbol_state(self, state: SyntheticSymbolState, template: MarketTemplate):
        """Update symbol state with realistic price movement."""
        # Price random walk with trend and volatility clustering
        dt = 1.0 / (24 * 3600)  # Assume 1-second intervals normalized to daily
        
        # Volatility clustering
        if self.enable_volatility_clustering:
            vol_factor = 1.0 + 0.1 * math.sin(time.time() * 0.001)  # Slow volatility cycle
            current_vol = state.volatility * vol_factor
        else:
            current_vol = state.volatility
        
        # Price change with trend and random component
        trend_component = state.price_trend * dt
        random_component = random.gauss(0, current_vol * math.sqrt(dt))
        price_change = trend_component + random_component
        
        # Apply percentage limits
        max_change = state.current_price * (self.price_variation_pct / 100.0) * dt
        price_change = max(-max_change, min(max_change, price_change))
        
        # Update price
        state.current_price = max(0.01, state.current_price + price_change)
        
        # Update spread (mean-reverting)
        spread_target = template.spread_avg * (state.current_price / template.base_price)
        spread_change = (spread_target - state.current_spread) * 0.1 + random.gauss(0, template.spread_volatility * 0.1)
        state.current_spread = max(0.001, state.current_spread + spread_change)
        
        # Update bid/ask
        half_spread = state.current_spread / 2
        state.current_bid = state.current_price - half_spread
        state.current_ask = state.current_price + half_spread
        
        # Occasionally reverse trend
        if random.random() < 0.001:  # 0.1% chance per update
            state.price_trend *= -0.8
        
        # Update tick counter
        state.tick_counter += 1
    
    def _generate_trade_message(self, state: SyntheticSymbolState, timestamp: datetime) -> Dict[str, Any]:
        """Generate synthetic trade message."""
        # Trade price near current price with small variation
        trade_price = state.current_price + random.gauss(0, state.current_spread * 0.3)
        trade_price = max(0.01, trade_price)
        
        # Volume with variation
        base_volume = self.templates[list(self.templates.keys())[0]].volume_avg
        volume_factor = 1.0 + random.uniform(-self.volume_variation_pct/100, self.volume_variation_pct/100)
        trade_size = max(1, int(base_volume * volume_factor))
        
        state.total_volume += trade_size
        state.last_trade_size = trade_size
        
        # Create IQFeed trade message
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]
        raw_message = (f"T,{state.symbol},{timestamp_str},{trade_price:.4f},{trade_size},"
                      f"{state.total_volume},NASDAQ,F,{state.tick_counter},"
                      f"{state.current_bid:.4f},{state.current_ask:.4f}")
        
        return {
            'timestamp': timestamp.isoformat(),
            'symbol': state.symbol,
            'message_type': 'T',
            'raw_message': raw_message,
            'tick_id': state.tick_counter,
            'synthetic': True
        }
    
    def _generate_quote_message(self, state: SyntheticSymbolState, timestamp: datetime) -> Dict[str, Any]:
        """Generate synthetic quote message."""
        # Add small variations to bid/ask
        bid = state.current_bid + random.gauss(0, state.current_spread * 0.1)
        ask = state.current_ask + random.gauss(0, state.current_spread * 0.1)
        
        # Ensure ask > bid
        if ask <= bid:
            mid = (bid + ask) / 2
            spread = state.current_spread
            bid = mid - spread/2
            ask = mid + spread/2
        
        bid_size = random.randint(100, 2000)
        ask_size = random.randint(100, 2000)
        
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]
        raw_message = (f"Q,{state.symbol},{timestamp_str},{bid:.4f},{bid_size},"
                      f"{ask:.4f},{ask_size},NYSE,NASDAQ,{state.tick_counter}")
        
        return {
            'timestamp': timestamp.isoformat(),
            'symbol': state.symbol,
            'message_type': 'Q',
            'raw_message': raw_message,
            'tick_id': state.tick_counter,
            'synthetic': True
        }
    
    def _generate_l2_message(self, state: SyntheticSymbolState, timestamp: datetime) -> Dict[str, Any]:
        """Generate synthetic L2 update message."""
        # Choose random level and side
        max_level = len(state.l2_book)
        level = random.randint(0, max_level - 1)
        side = random.choice(['bid', 'ask'])
        side_num = 1 if side == 'bid' else 0
        
        # Update the level
        if level in state.l2_book and side in state.l2_book[level]:
            old_price, old_size = state.l2_book[level][side]
            
            # Small price movement
            price_change = random.gauss(0, state.current_spread * 0.05)
            new_price = max(0.01, old_price + price_change)
            
            # Size change
            size_change = random.randint(-50, 100)
            new_size = max(100, old_size + size_change)
            
            state.l2_book[level][side] = (new_price, new_size)
        else:
            # Initialize level if doesn't exist
            base_price = state.current_bid if side == 'bid' else state.current_ask
            level_offset = state.current_spread * (level + 1)
            new_price = base_price - level_offset if side == 'bid' else base_price + level_offset
            new_size = random.randint(100, 1000)
            
            if level not in state.l2_book:
                state.l2_book[level] = {}
            state.l2_book[level][side] = (new_price, new_size)
        
        new_price, new_size = state.l2_book[level][side]
        operation = random.choice([0, 1])  # Insert/Update
        
        timestamp_str = timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]
        raw_message = (f"U,{state.symbol},{timestamp_str},{side_num},{level},MM{random.randint(1,5)},"
                      f"{new_price:.4f},{new_size},{operation}")
        
        return {
            'timestamp': timestamp.isoformat(),
            'symbol': state.symbol,
            'message_type': 'U',
            'raw_message': raw_message,
            'tick_id': state.tick_counter,
            'synthetic': True
        }
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get next synthetic message."""
        try:
            return self._output_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get synthesis statistics."""
        with self._stats_lock:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds() if self._start_time else 0
            rate = self._messages_generated / uptime if uptime > 0 else 0
            
            return {
                'running': self._running,
                'symbols_count': len(self.target_symbols),
                'messages_generated': self._messages_generated,
                'generation_rate_msg_per_sec': rate,
                'uptime_seconds': uptime,
                'queue_size': self._output_queue.qsize(),
                'worker_threads': len(self._producer_threads),
                'expected_rate': len(self.target_symbols) * self.msg_rate_per_symbol,
                'synthesis_progress_pct': (uptime / (self.synthesis_duration_hours * 3600)) * 100 if self.synthesis_duration_hours > 0 else 0
            }
    
    def stop(self):
        """Stop synthetic data generation."""
        logger.info("Stopping synthetic market data generation")
        self._running = False
        
        # Wait for worker threads
        for thread in self._producer_threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
        
        logger.info("✅ Synthetic market data generation stopped")
    
    def disconnect(self):
        """Disconnect and cleanup."""
        self.stop()
        
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"Error closing ClickHouse client: {e}")
            finally:
                self._client = None


def main():
    """Example usage of synthetic market data producer."""
    logger.info("🧪 SYNTHETIC MARKET DATA PRODUCER TEST")
    logger.info("=" * 80)
    
    # Test with template-based synthesis
    producer = SyntheticMarketDataProducer(
        mode=SynthesisMode.TEMPLATE_BASED,
        target_symbols=['SYNTHETIC_AAPL', 'SYNTHETIC_TSLA', 'SYNTHETIC_MSFT'],
        synthesis_duration_hours=0.1,  # 6 minutes for demo
        time_acceleration=10.0,  # 10x speed
        messages_per_second_per_symbol=5.0,  # 5 msg/s per symbol
        price_variation_pct=1.0,  # 1% price variation
        volume_variation_pct=20.0  # 20% volume variation
    )
    
    try:
        # Initialize
        if not producer.connect():
            logger.error("Failed to connect")
            return
        
        if not producer.extract_templates():
            logger.error("Failed to extract templates")
            return
        
        # Start synthesis
        if not producer.start_synthesis():
            logger.error("Failed to start synthesis")
            return
        
        # Monitor for a while
        start_time = time.time()
        message_counts = {'T': 0, 'Q': 0, 'U': 0}
        
        logger.info("🎬 Collecting synthetic messages...")
        
        while time.time() - start_time < 30:  # 30 seconds
            message = producer.get_next_message(timeout=0.5)
            
            if message:
                msg_type = message.get('message_type', 'Unknown')
                message_counts[msg_type] = message_counts.get(msg_type, 0) + 1
                
                # Show first few messages
                total = sum(message_counts.values())
                if total <= 5:
                    logger.info(f"   📨 {msg_type}: {message['raw_message'][:80]}...")
                
                if total % 50 == 0:
                    stats = producer.get_statistics()
                    logger.info(f"   📊 Progress: {total} messages ({stats['generation_rate_msg_per_sec']:.1f} msg/s)")
        
        # Final statistics
        final_stats = producer.get_statistics()
        logger.info("🎯 SYNTHESIS TEST COMPLETE:")
        logger.info(f"   - Total messages: {final_stats['messages_generated']}")
        logger.info(f"   - Generation rate: {final_stats['generation_rate_msg_per_sec']:.1f} msg/s")
        logger.info(f"   - Trades (T): {message_counts.get('T', 0)}")
        logger.info(f"   - Quotes (Q): {message_counts.get('Q', 0)}")
        logger.info(f"   - L2 Updates (U): {message_counts.get('U', 0)}")
        
    finally:
        producer.disconnect()


if __name__ == "__main__":
    main()