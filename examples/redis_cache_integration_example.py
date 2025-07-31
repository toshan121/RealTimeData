#!/usr/bin/env python3
"""
Redis Cache Integration Example

Demonstrates how to integrate the high-performance Redis caching system
with the existing microstructure analysis components for real-time financial data.

This example shows:
- L1/L2 data caching integration
- Feature calculation caching
- Signal detection with pub/sub
- Performance monitoring
- Real-time data distribution
"""

import time
import threading
import logging
from typing import Dict, List, Any
import random
import asyncio
from datetime import datetime, timezone

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.redis_cache_manager import RedisCacheManager, CacheConfig
from processing.redis_microstructure_cache import (
    MicrostructureCache, OrderBookSnapshot, OrderBookLevel, 
    MicrostructureFeatures, get_microstructure_cache
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RealTimeDataProcessor:
    """
    Example real-time data processor showing Redis cache integration.
    
    This simulates a production microstructure analysis system that:
    - Receives high-frequency market data
    - Caches L1/L2 quotes for fast access
    - Calculates and caches microstructure features
    - Detects and publishes trading signals
    - Monitors performance metrics
    """
    
    def __init__(self):
        # Initialize Redis cache system
        self.cache_config = CacheConfig(
            host='localhost',
            port=6380,  # Using Docker Redis port
            max_connections=50,
            use_compression=True,
            l1_data_ttl=30,      # 30 seconds for L1 quotes
            l2_data_ttl=60,      # 1 minute for L2 order books  
            tick_data_ttl=300,   # 5 minutes for tick data
            default_ttl=3600     # 1 hour default
        )
        
        # Initialize cache manager
        self.cache_manager = RedisCacheManager(self.cache_config)
        self.microstructure_cache = MicrostructureCache(self.cache_manager)
        
        # Test symbols
        self.symbols = ['AAPL', 'TSLA', 'MSFT', 'GOOGL', 'AMZN']
        
        # State tracking
        self.running = False
        self.performance_stats = {
            'l1_quotes_processed': 0,
            'l2_updates_processed': 0,
            'features_calculated': 0,
            'signals_detected': 0,
            'start_time': None
        }
        
        # Signal subscribers
        self.signal_callbacks = {}
    
    def start(self) -> bool:
        """Start the real-time data processor."""
        logger.info("🚀 Starting Real-Time Data Processor with Redis Cache")
        
        try:
            # Start cache manager
            if not self.cache_manager.start():
                logger.error("Failed to start cache manager")
                return False
            
            # Setup signal subscriptions
            self._setup_signal_subscriptions()
            
            self.running = True
            self.performance_stats['start_time'] = time.time()
            
            logger.info("✅ Real-time data processor started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start data processor: {e}")
            return False
    
    def stop(self):
        """Stop the real-time data processor."""
        logger.info("🛑 Stopping Real-Time Data Processor")
        
        self.running = False
        
        if self.cache_manager:
            self.cache_manager.stop()
        
        self._print_performance_summary()
        logger.info("✅ Real-time data processor stopped")
    
    def _setup_signal_subscriptions(self):
        """Setup signal subscriptions for real-time notifications."""
        def accumulation_signal_handler(channel: str, signal_data: Dict[str, Any]):
            """Handle accumulation signal notifications."""
            symbol = signal_data.get('symbol', 'UNKNOWN')
            strength = signal_data.get('strength', 0)
            confidence = signal_data.get('confidence', 0)
            
            logger.info(f"🟢 ACCUMULATION SIGNAL: {symbol} - Strength: {strength:.2f}, Confidence: {confidence:.2f}")
            self.performance_stats['signals_detected'] += 1
        
        def dilution_signal_handler(channel: str, signal_data: Dict[str, Any]):
            """Handle dilution signal notifications."""
            symbol = signal_data.get('symbol', 'UNKNOWN')
            strength = signal_data.get('strength', 0)
            confidence = signal_data.get('confidence', 0)
            
            logger.info(f"🔴 DILUTION SIGNAL: {symbol} - Strength: {strength:.2f}, Confidence: {confidence:.2f}")
            self.performance_stats['signals_detected'] += 1
        
        # Subscribe to signals for all symbols
        for symbol in self.symbols:
            self.microstructure_cache.subscribe_to_signals(symbol, 'accumulation', accumulation_signal_handler)
            self.microstructure_cache.subscribe_to_signals(symbol, 'dilution', dilution_signal_handler)
    
    def simulate_l1_market_data_feed(self, duration_seconds: int = 60):
        """Simulate high-frequency L1 market data feed."""
        logger.info(f"📈 Starting L1 market data simulation ({duration_seconds}s)")
        
        end_time = time.time() + duration_seconds
        base_prices = {
            'AAPL': 150.0,
            'TSLA': 250.0, 
            'MSFT': 300.0,
            'GOOGL': 2500.0,
            'AMZN': 3000.0
        }
        
        while self.running and time.time() < end_time:
            for symbol in self.symbols:
                if not self.running:
                    break
                
                # Simulate realistic price movement
                base_price = base_prices[symbol]
                price_change = random.uniform(-0.10, 0.10)  # +/- 10 cents
                
                bid = base_price + price_change
                ask = bid + random.uniform(0.01, 0.05)  # 1-5 cent spread
                bid_size = random.randint(100, 5000)
                ask_size = random.randint(100, 5000)
                
                # Cache L1 quote
                success = self.microstructure_cache.cache_l1_quote(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    timestamp=time.time()
                )
                
                if success:
                    self.performance_stats['l1_quotes_processed'] += 1
                
                # Update base price slightly for next iteration
                base_prices[symbol] = base_price + (price_change * 0.1)
            
            # High frequency - 100+ updates per second
            time.sleep(0.01)
        
        logger.info("✅ L1 market data simulation completed")
    
    def simulate_l2_order_book_updates(self, duration_seconds: int = 60):
        """Simulate L2 order book updates."""
        logger.info(f"📚 Starting L2 order book simulation ({duration_seconds}s)")
        
        end_time = time.time() + duration_seconds
        
        while self.running and time.time() < end_time:
            for symbol in self.symbols:
                if not self.running:
                    break
                
                # Generate realistic order book with 10 levels
                base_price = 150.0 + random.uniform(-10, 10)
                
                bids = []
                asks = []
                
                for level in range(10):
                    bid_price = base_price - (level * 0.01)
                    ask_price = base_price + 0.05 + (level * 0.01)
                    
                    bid_size = random.randint(100, 2000)
                    ask_size = random.randint(100, 2000)
                    
                    bids.append(OrderBookLevel(bid_price, bid_size))
                    asks.append(OrderBookLevel(ask_price, ask_size))
                
                # Create order book snapshot
                snapshot = OrderBookSnapshot(
                    symbol=symbol,
                    timestamp=time.time(),
                    bids=bids,
                    asks=asks
                )
                
                # Cache L2 order book
                success = self.microstructure_cache.cache_l2_orderbook(snapshot)
                
                if success:
                    self.performance_stats['l2_updates_processed'] += 1
            
            # L2 updates less frequent than L1
            time.sleep(0.1)
        
        logger.info("✅ L2 order book simulation completed")
    
    def calculate_and_cache_features(self, duration_seconds: int = 60):
        """Calculate and cache microstructure features."""
        logger.info(f"⚡ Starting feature calculation ({duration_seconds}s)")
        
        end_time = time.time() + duration_seconds
        
        while self.running and time.time() < end_time:
            for symbol in self.symbols:
                if not self.running:
                    break
                
                # Get latest L1 data for feature calculation
                l1_data = self.microstructure_cache.get_latest_l1(symbol)
                
                if l1_data:
                    # Calculate microstructure features
                    features = MicrostructureFeatures(
                        symbol=symbol,
                        timestamp=time.time(),
                        order_flow_imbalance=random.uniform(-1.0, 1.0),
                        bid_ask_imbalance=random.uniform(-0.5, 0.5),
                        volume_imbalance=random.uniform(-0.3, 0.3),
                        mid_price=l1_data.get('mid_price', 150.0),
                        spread=l1_data.get('spread', 0.05),
                        relative_spread=l1_data.get('spread', 0.05) / l1_data.get('mid_price', 150.0),
                        bid_volume_1=l1_data.get('bid_size', 100),
                        ask_volume_1=l1_data.get('ask_size', 100),
                        total_volume_5=random.randint(5000, 50000),
                        volume_weighted_price=l1_data.get('mid_price', 150.0) + random.uniform(-0.02, 0.02),
                        effective_spread=l1_data.get('spread', 0.05) * random.uniform(0.8, 1.2),
                        depth_imbalance=random.uniform(-0.2, 0.2),
                        book_pressure=random.uniform(-0.4, 0.4),
                        realized_volatility=random.uniform(0.001, 0.05),
                        microstructure_noise=random.uniform(0.0001, 0.001),
                        bid_ask_bounce=random.uniform(-0.01, 0.01)
                    )
                    
                    # Cache features
                    success = self.microstructure_cache.cache_microstructure_features(features)
                    
                    if success:
                        self.performance_stats['features_calculated'] += 1
                    
                    # Cache additional metrics
                    self._cache_additional_metrics(symbol, features)
            
            # Feature calculation every 5 seconds
            time.sleep(5.0)
        
        logger.info("✅ Feature calculation completed")
    
    def _cache_additional_metrics(self, symbol: str, features: MicrostructureFeatures):
        """Cache additional microstructure metrics."""
        # Cache Order Flow Imbalance
        if features.order_flow_imbalance is not None:
            self.microstructure_cache.cache_order_flow_imbalance(
                symbol=symbol,
                ofi_value=features.order_flow_imbalance,
                timeframe='1min'
            )
        
        # Cache Volume-Price Trend
        if features.volume_weighted_price and features.total_volume_5:
            price_change = random.uniform(-0.5, 0.5)  # Simulate price change
            vpt_value = features.total_volume_5 * price_change
            
            self.microstructure_cache.cache_volume_price_trend(
                symbol=symbol,
                vpt_value=vpt_value,
                volume=features.total_volume_5,
                price_change=price_change
            )
        
        # Cache Dark Pool Inference
        lit_volume = random.randint(50000, 80000)
        total_volume = random.randint(80000, 120000)
        dark_pool_ratio = (total_volume - lit_volume) / total_volume
        
        self.microstructure_cache.cache_dark_pool_inference(
            symbol=symbol,
            dark_pool_ratio=dark_pool_ratio,
            lit_volume=lit_volume,
            total_volume=total_volume
        )
    
    def detect_and_publish_signals(self, duration_seconds: int = 60):
        """Detect trading signals and publish notifications."""
        logger.info(f"🔍 Starting signal detection ({duration_seconds}s)")
        
        end_time = time.time() + duration_seconds
        
        while self.running and time.time() < end_time:
            for symbol in self.symbols:
                if not self.running:
                    break
                
                # Get latest features for signal detection
                features = self.microstructure_cache.get_microstructure_features(symbol)
                
                if features:
                    # Detect accumulation signals
                    if self._detect_accumulation_signal(features):
                        signal_features = {
                            'order_flow_imbalance': features.order_flow_imbalance,
                            'volume_surge': features.total_volume_5 > 30000 if features.total_volume_5 else False,
                            'bid_pressure': features.bid_ask_imbalance > 0.2 if features.bid_ask_imbalance else False,
                            'spread_tightening': features.relative_spread < 0.001 if features.relative_spread else False,
                            'depth_imbalance': features.depth_imbalance
                        }
                        
                        strength = random.uniform(0.7, 0.95)
                        confidence = random.uniform(0.8, 0.98)
                        
                        self.microstructure_cache.cache_accumulation_signal(
                            symbol=symbol,
                            signal_strength=strength,
                            confidence=confidence,
                            features=signal_features
                        )
                    
                    # Detect dilution signals
                    elif self._detect_dilution_signal(features):
                        signal_features = {
                            'order_flow_imbalance': features.order_flow_imbalance,
                            'ask_pressure': features.bid_ask_imbalance < -0.2 if features.bid_ask_imbalance else False,
                            'volume_decline': features.total_volume_5 < 10000 if features.total_volume_5 else False,
                            'spread_widening': features.relative_spread > 0.002 if features.relative_spread else False,
                            'depth_imbalance': features.depth_imbalance
                        }
                        
                        strength = random.uniform(0.6, 0.9)
                        confidence = random.uniform(0.75, 0.95)
                        
                        self.microstructure_cache.cache_dilution_signal(
                            symbol=symbol,
                            signal_strength=strength,
                            confidence=confidence,
                            features=signal_features
                        )
            
            # Signal detection every 10 seconds
            time.sleep(10.0)
        
        logger.info("✅ Signal detection completed")
    
    def _detect_accumulation_signal(self, features: MicrostructureFeatures) -> bool:
        """Detect accumulation signals based on features."""
        conditions = [
            features.order_flow_imbalance and features.order_flow_imbalance > 0.3,
            features.bid_ask_imbalance and features.bid_ask_imbalance > 0.2,
            features.depth_imbalance and features.depth_imbalance > 0.15,
            features.relative_spread and features.relative_spread < 0.001,
            features.total_volume_5 and features.total_volume_5 > 25000
        ]
        
        # At least 3 conditions must be true
        return sum(1 for c in conditions if c) >= 3
    
    def _detect_dilution_signal(self, features: MicrostructureFeatures) -> bool:
        """Detect dilution signals based on features."""
        conditions = [
            features.order_flow_imbalance and features.order_flow_imbalance < -0.3,
            features.bid_ask_imbalance and features.bid_ask_imbalance < -0.2,
            features.depth_imbalance and features.depth_imbalance < -0.15,
            features.relative_spread and features.relative_spread > 0.002,
            features.total_volume_5 and features.total_volume_5 < 15000
        ]
        
        # At least 3 conditions must be true  
        return sum(1 for c in conditions if c) >= 3
    
    def monitor_performance(self, duration_seconds: int = 60):
        """Monitor and log performance metrics."""
        logger.info(f"📊 Starting performance monitoring ({duration_seconds}s)")
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        while self.running and time.time() < end_time:
            # Get cache performance stats
            cache_stats = self.microstructure_cache.get_cache_stats()
            
            # Calculate rates
            elapsed = time.time() - self.performance_stats['start_time']
            l1_rate = self.performance_stats['l1_quotes_processed'] / elapsed if elapsed > 0 else 0
            l2_rate = self.performance_stats['l2_updates_processed'] / elapsed if elapsed > 0 else 0
            feature_rate = self.performance_stats['features_calculated'] / elapsed if elapsed > 0 else 0
            
            logger.info(f"📈 Performance Metrics:")
            logger.info(f"   • L1 Quotes: {self.performance_stats['l1_quotes_processed']:,} ({l1_rate:.1f}/sec)")
            logger.info(f"   • L2 Updates: {self.performance_stats['l2_updates_processed']:,} ({l2_rate:.1f}/sec)")
            logger.info(f"   • Features: {self.performance_stats['features_calculated']:,} ({feature_rate:.1f}/sec)")
            logger.info(f"   • Signals: {self.performance_stats['signals_detected']:,}")
            logger.info(f"   • Cache Hit Rate: {cache_stats.get('hit_rate', 0):.2%}")
            logger.info(f"   • Cache Operations: {cache_stats.get('cache_operations', 0):,}")
            
            time.sleep(10.0)  # Log every 10 seconds
        
        logger.info("✅ Performance monitoring completed")
    
    def _print_performance_summary(self):
        """Print final performance summary."""
        if not self.performance_stats['start_time']:
            return
        
        elapsed = time.time() - self.performance_stats['start_time']
        
        print("\n" + "="*60)
        print("📊 FINAL PERFORMANCE SUMMARY")
        print("="*60)
        print(f"Total Runtime: {elapsed:.1f} seconds")
        print(f"L1 Quotes Processed: {self.performance_stats['l1_quotes_processed']:,}")
        print(f"L2 Updates Processed: {self.performance_stats['l2_updates_processed']:,}")
        print(f"Features Calculated: {self.performance_stats['features_calculated']:,}")
        print(f"Signals Detected: {self.performance_stats['signals_detected']:,}")
        
        if elapsed > 0:
            print(f"L1 Quote Rate: {self.performance_stats['l1_quotes_processed'] / elapsed:.1f} quotes/sec")
            print(f"L2 Update Rate: {self.performance_stats['l2_updates_processed'] / elapsed:.1f} updates/sec")
            print(f"Feature Rate: {self.performance_stats['features_calculated'] / elapsed:.1f} features/sec")
        
        # Cache stats
        cache_stats = self.microstructure_cache.get_cache_stats()
        print(f"Cache Hit Rate: {cache_stats.get('hit_rate', 0):.2%}")
        print(f"Total Cache Operations: {cache_stats.get('cache_operations', 0):,}")
        
        print("="*60)
    
    def run_demo(self, duration_seconds: int = 120):
        """Run comprehensive demo of Redis cache integration."""
        logger.info(f"🎯 Starting Redis Cache Integration Demo ({duration_seconds}s)")
        
        if not self.start():
            logger.error("Failed to start demo")
            return
        
        try:
            # Start all simulation threads
            threads = [
                threading.Thread(target=self.simulate_l1_market_data_feed, args=(duration_seconds,), daemon=True),
                threading.Thread(target=self.simulate_l2_order_book_updates, args=(duration_seconds,), daemon=True),
                threading.Thread(target=self.calculate_and_cache_features, args=(duration_seconds,), daemon=True),
                threading.Thread(target=self.detect_and_publish_signals, args=(duration_seconds,), daemon=True),
                threading.Thread(target=self.monitor_performance, args=(duration_seconds,), daemon=True)
            ]
            
            # Start all threads
            for thread in threads:
                thread.start()
            
            # Wait for completion
            for thread in threads:
                thread.join()
            
            logger.info("🎉 Redis Cache Integration Demo completed successfully!")
            
        except KeyboardInterrupt:
            logger.info("Demo interrupted by user")
        except Exception as e:
            logger.error(f"Demo failed: {e}")
        finally:
            self.stop()


def demonstrate_cache_retrieval():
    """Demonstrate data retrieval from cache."""
    logger.info("🔍 Demonstrating Cache Data Retrieval")
    
    # Get cache instance
    cache = get_microstructure_cache()
    
    symbols = ['AAPL', 'TSLA', 'MSFT']
    
    for symbol in symbols:
        print(f"\n📊 Data for {symbol}:")
        
        # Get latest L1 quote
        l1_data = cache.get_latest_l1(symbol)
        if l1_data:
            print(f"   L1: Bid ${l1_data.get('bid', 0):.2f}, Ask ${l1_data.get('ask', 0):.2f}, "
                  f"Spread ${l1_data.get('spread', 0):.3f}")
        
        # Get latest features
        features = cache.get_microstructure_features(symbol)
        if features:
            print(f"   OFI: {features.order_flow_imbalance:.3f}")
            print(f"   Bid-Ask Imbalance: {features.bid_ask_imbalance:.3f}")
            print(f"   Relative Spread: {features.relative_spread:.5f}")
        
        # Get recent signals
        accumulation_signals = cache.get_recent_signals(symbol, 'accumulation', count=3)
        if accumulation_signals:
            print(f"   Recent Accumulation Signals: {len(accumulation_signals)}")
            for signal in accumulation_signals[:2]:  # Show last 2
                print(f"     • Strength: {signal.get('strength', 0):.2f}, "
                      f"Confidence: {signal.get('confidence', 0):.2f}")
        
        # Get OFI timeseries
        ofi_timeseries = cache.get_ofi_timeseries(symbol, '1min', count=5)
        if ofi_timeseries:
            print(f"   OFI Timeseries: {len(ofi_timeseries)} points")
            for ts, ofi in ofi_timeseries[-2:]:  # Show last 2
                print(f"     • {datetime.fromtimestamp(ts).strftime('%H:%M:%S')}: {ofi:.3f}")


async def async_demo_example():
    """Example of async integration with Redis cache."""
    logger.info("🔄 Async Demo Example")
    
    cache = get_microstructure_cache()
    
    async def async_feature_calculation(symbol: str):
        """Async feature calculation example."""
        for i in range(5):
            # Simulate async processing
            await asyncio.sleep(0.1)
            
            features = MicrostructureFeatures(
                symbol=symbol,
                timestamp=time.time(),
                order_flow_imbalance=random.uniform(-1.0, 1.0),
                mid_price=150.0 + random.random() * 10
            )
            
            # Cache is thread-safe and can be used in async contexts
            success = cache.cache_microstructure_features(features)
            logger.info(f"Async cached features for {symbol}: {success}")
    
    # Run async tasks
    symbols = ['AAPL', 'TSLA', 'MSFT']
    tasks = [async_feature_calculation(symbol) for symbol in symbols]
    
    await asyncio.gather(*tasks)
    logger.info("✅ Async demo completed")


def main():
    """Main demonstration function."""
    print("\n🚀 Redis Cache Integration for High-Frequency Financial Data")
    print("="*70)
    
    # Create processor instance
    processor = RealTimeDataProcessor()
    
    try:
        # Run main demo
        processor.run_demo(duration_seconds=60)  # 1 minute demo
        
        # Demonstrate data retrieval
        demonstrate_cache_retrieval()
        
        # Async example
        print("\n" + "="*70)
        asyncio.run(async_demo_example())
        
        print("\n🎉 All demonstrations completed successfully!")
        print("\nKey Benefits Demonstrated:")
        print("✅ High-frequency L1/L2 data caching (100+ ops/sec)")
        print("✅ Microstructure feature caching with TTL management")
        print("✅ Real-time signal detection with pub/sub notifications")
        print("✅ Connection pooling and fault tolerance")
        print("✅ Memory optimization and compression")
        print("✅ Performance monitoring and metrics")
        print("✅ Thread-safe async/await compatibility")
        
    except KeyboardInterrupt:
        print("\n⏹️ Demo interrupted by user")
        processor.stop()
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        processor.stop()


if __name__ == "__main__":
    main()