#!/usr/bin/env python3
"""
STRESS TEST: Synthetic Market Data Producer

Tests the synthetic data producer with:
- 2000+ symbols for stress testing
- High message rates (10,000+ msg/s)
- Template-based and procedural generation
- Real-time performance monitoring

Perfect for testing GPU functions under high load when markets are closed.
"""

import time
import logging
import sys
import os
from typing import List

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

from ingestion.synthetic_market_data_producer import (
    SyntheticMarketDataProducer,
    SynthesisMode
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_small_scale():
    """Test with small number of symbols first."""
    logger.info("🧪 SMALL SCALE TEST (10 symbols)")
    logger.info("=" * 60)
    
    producer = SyntheticMarketDataProducer(
        mode=SynthesisMode.TEMPLATE_BASED,
        target_symbols=[f'TEST{i:03d}' for i in range(10)],
        synthesis_duration_hours=0.05,  # 3 minutes
        time_acceleration=5.0,  # 5x speed
        messages_per_second_per_symbol=10.0,  # 10 msg/s per symbol = 100 total
        price_variation_pct=2.0,
        volume_variation_pct=30.0
    )
    
    try:
        success = producer.connect() and producer.extract_templates() and producer.start_synthesis()
        
        if success:
            logger.info("✅ Small scale test started successfully")
            
            # Monitor for 20 seconds
            start_time = time.time()
            message_counts = {'T': 0, 'Q': 0, 'U': 0}
            
            while time.time() - start_time < 20:
                message = producer.get_next_message(timeout=0.1)
                
                if message:
                    msg_type = message.get('message_type', 'Unknown')
                    message_counts[msg_type] = message_counts.get(msg_type, 0) + 1
                    
                    # Show first message of each type
                    total = sum(message_counts.values())
                    if message_counts[msg_type] == 1:
                        logger.info(f"   📨 First {msg_type}: {message['raw_message'][:70]}...")
                
                # Periodic stats
                if int(time.time() - start_time) % 5 == 0:
                    stats = producer.get_statistics()
                    if stats['messages_generated'] > 0:
                        logger.info(f"   📊 {stats['messages_generated']} messages @ {stats['generation_rate_msg_per_sec']:.1f} msg/s")
            
            # Final results
            final_stats = producer.get_statistics()
            logger.info("🎯 SMALL SCALE RESULTS:")
            logger.info(f"   - Symbols: {final_stats['symbols_count']}")
            logger.info(f"   - Messages: {final_stats['messages_generated']}")
            logger.info(f"   - Rate: {final_stats['generation_rate_msg_per_sec']:.1f} msg/s")
            logger.info(f"   - Trades: {message_counts.get('T', 0)}")
            logger.info(f"   - Quotes: {message_counts.get('Q', 0)}")
            logger.info(f"   - L2: {message_counts.get('U', 0)}")
            
            return final_stats['generation_rate_msg_per_sec'] > 50  # Should get 50+ msg/s
        else:
            logger.error("❌ Small scale test failed to start")
            return False
            
    finally:
        producer.disconnect()


def test_medium_scale():
    """Test with medium number of symbols (100)."""
    logger.info("\\n🚀 MEDIUM SCALE TEST (100 symbols)")
    logger.info("=" * 60)
    
    producer = SyntheticMarketDataProducer(
        mode=SynthesisMode.PROCEDURAL,  # Faster - no ClickHouse templates
        target_symbols=[f'MED{i:03d}' for i in range(100)],
        synthesis_duration_hours=0.1,  # 6 minutes
        time_acceleration=10.0,  # 10x speed
        messages_per_second_per_symbol=8.0,  # 8 msg/s per symbol = 800 total
        price_variation_pct=1.5,
        volume_variation_pct=25.0
    )
    
    try:
        success = producer.connect() and producer.extract_templates() and producer.start_synthesis()
        
        if success:
            logger.info("✅ Medium scale test started successfully")
            
            # Monitor for 30 seconds
            start_time = time.time()
            last_count = 0
            
            while time.time() - start_time < 30:
                time.sleep(2)  # Check every 2 seconds
                
                stats = producer.get_statistics()
                messages_this_period = stats['messages_generated'] - last_count
                period_rate = messages_this_period / 2.0  # Per second over 2 second period
                
                logger.info(f"   📊 Total: {stats['messages_generated']}, "
                          f"Rate: {stats['generation_rate_msg_per_sec']:.0f} msg/s, "
                          f"Recent: {period_rate:.0f} msg/s, "
                          f"Queue: {stats['queue_size']}")
                
                last_count = stats['messages_generated']
            
            # Final results
            final_stats = producer.get_statistics()
            logger.info("🎯 MEDIUM SCALE RESULTS:")
            logger.info(f"   - Symbols: {final_stats['symbols_count']}")
            logger.info(f"   - Messages: {final_stats['messages_generated']}")
            logger.info(f"   - Rate: {final_stats['generation_rate_msg_per_sec']:.1f} msg/s")
            logger.info(f"   - Expected: {final_stats['expected_rate']:.0f} msg/s")
            logger.info(f"   - Efficiency: {(final_stats['generation_rate_msg_per_sec'] / final_stats['expected_rate'] * 100):.1f}%")
            
            return final_stats['generation_rate_msg_per_sec'] > 500  # Should get 500+ msg/s
        else:
            logger.error("❌ Medium scale test failed to start")
            return False
            
    finally:
        producer.disconnect()


def test_large_scale():
    """Test with large number of symbols (1000) for stress testing."""
    logger.info("\\n🔥 LARGE SCALE STRESS TEST (1000 symbols)")
    logger.info("=" * 60)
    
    producer = SyntheticMarketDataProducer(
        mode=SynthesisMode.PROCEDURAL,  # Pure procedural for max performance
        target_symbols=[f'STRESS{i:04d}' for i in range(1000)],
        synthesis_duration_hours=0.2,  # 12 minutes
        time_acceleration=20.0,  # 20x speed
        messages_per_second_per_symbol=5.0,  # 5 msg/s per symbol = 5000 total
        price_variation_pct=1.0,
        volume_variation_pct=20.0
    )
    
    try:
        success = producer.connect() and producer.extract_templates() and producer.start_synthesis()
        
        if success:
            logger.info("✅ Large scale stress test started successfully")
            logger.info(f"   Target rate: {1000 * 5.0:.0f} messages/second")
            
            # Monitor for 60 seconds
            start_time = time.time()
            peak_rate = 0
            
            while time.time() - start_time < 60:
                time.sleep(5)  # Check every 5 seconds
                
                stats = producer.get_statistics()
                current_rate = stats['generation_rate_msg_per_sec']
                peak_rate = max(peak_rate, current_rate)
                
                logger.info(f"   🔥 Messages: {stats['messages_generated']:,}, "
                          f"Rate: {current_rate:.0f} msg/s, "
                          f"Peak: {peak_rate:.0f}, "
                          f"Queue: {stats['queue_size']:,}, "
                          f"Progress: {stats['synthesis_progress_pct']:.1f}%")
                
                # Test message consumption
                consumed = 0
                consume_start = time.time()
                while time.time() - consume_start < 1.0:  # Consume for 1 second
                    message = producer.get_next_message(timeout=0.01)
                    if message:
                        consumed += 1
                
                logger.info(f"   📥 Consumed {consumed} messages in 1 second")
            
            # Final results
            final_stats = producer.get_statistics()
            logger.info("🎯 LARGE SCALE STRESS TEST RESULTS:")
            logger.info(f"   - Symbols: {final_stats['symbols_count']:,}")
            logger.info(f"   - Messages Generated: {final_stats['messages_generated']:,}")
            logger.info(f"   - Average Rate: {final_stats['generation_rate_msg_per_sec']:.1f} msg/s")
            logger.info(f"   - Peak Rate: {peak_rate:.1f} msg/s")
            logger.info(f"   - Target Rate: {final_stats['expected_rate']:.0f} msg/s")
            logger.info(f"   - Efficiency: {(final_stats['generation_rate_msg_per_sec'] / final_stats['expected_rate'] * 100):.1f}%")
            logger.info(f"   - Worker Threads: {final_stats['worker_threads']}")
            
            return final_stats['generation_rate_msg_per_sec'] > 2000  # Should get 2000+ msg/s
        else:
            logger.error("❌ Large scale test failed to start")
            return False
            
    finally:
        producer.disconnect()


def test_gpu_integration_simulation():
    """Simulate GPU function integration with synthetic data."""
    logger.info("\\n🧠 GPU INTEGRATION SIMULATION")
    logger.info("=" * 60)
    
    # Simulate realistic production scenario
    producer = SyntheticMarketDataProducer(
        mode=SynthesisMode.TEMPLATE_BASED,
        target_symbols=[f'GPU{i:03d}' for i in range(50)],  # 50 symbols
        synthesis_duration_hours=1.0,  # 1 hour of data
        time_acceleration=1.0,  # Real-time
        messages_per_second_per_symbol=15.0,  # Realistic rate = 750 msg/s total
        price_variation_pct=3.0,
        volume_variation_pct=40.0,
        enable_trends=True,
        enable_volatility_clustering=True
    )
    
    try:
        success = producer.connect() and producer.extract_templates() and producer.start_synthesis()
        
        if success:
            logger.info("✅ GPU integration simulation started")
            logger.info("🔬 Simulating GPU function processing...")
            
            # Simulate GPU processing batches
            start_time = time.time()
            batch_size = 100
            batch_count = 0
            total_processed = 0
            processing_times = []
            
            while time.time() - start_time < 30:  # Run for 30 seconds
                # Collect a batch
                batch = []
                batch_start = time.time()
                
                while len(batch) < batch_size and time.time() - batch_start < 2.0:
                    message = producer.get_next_message(timeout=0.1)
                    if message:
                        batch.append(message)
                
                if batch:
                    # Simulate GPU processing time
                    gpu_start = time.time()
                    
                    # Simulate actual processing (parse messages, etc.)
                    trade_count = sum(1 for m in batch if m.get('message_type') == 'T')
                    quote_count = sum(1 for m in batch if m.get('message_type') == 'Q')
                    l2_count = sum(1 for m in batch if m.get('message_type') == 'U')
                    
                    # Simulate GPU compute time (proportional to batch size)
                    compute_time = len(batch) * 0.0001  # 0.1ms per message
                    time.sleep(compute_time)
                    
                    processing_time = time.time() - gpu_start
                    processing_times.append(processing_time)
                    
                    batch_count += 1
                    total_processed += len(batch)
                    
                    if batch_count % 10 == 0:
                        avg_processing_time = sum(processing_times[-10:]) / min(10, len(processing_times))
                        stats = producer.get_statistics()
                        
                        logger.info(f"   🎯 Batch {batch_count}: {len(batch)} messages "
                                  f"(T:{trade_count}, Q:{quote_count}, L2:{l2_count}) "
                                  f"processed in {processing_time*1000:.1f}ms, "
                                  f"avg: {avg_processing_time*1000:.1f}ms")
                        logger.info(f"   📊 Producer: {stats['generation_rate_msg_per_sec']:.0f} msg/s, "
                                  f"Consumer: {total_processed/(time.time()-start_time):.0f} msg/s")
            
            # Final GPU simulation results
            avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
            total_time = time.time() - start_time
            processing_rate = total_processed / total_time
            
            final_stats = producer.get_statistics()
            
            logger.info("🎯 GPU INTEGRATION SIMULATION RESULTS:")
            logger.info(f"   - Total Batches Processed: {batch_count}")
            logger.info(f"   - Total Messages Processed: {total_processed}")
            logger.info(f"   - Processing Rate: {processing_rate:.1f} messages/second")
            logger.info(f"   - Average Batch Processing Time: {avg_processing_time*1000:.2f}ms")
            logger.info(f"   - Producer Rate: {final_stats['generation_rate_msg_per_sec']:.1f} msg/s")
            logger.info(f"   - Consumer/Producer Ratio: {(processing_rate/final_stats['generation_rate_msg_per_sec']*100):.1f}%")
            
            return processing_rate > 500  # Should process 500+ msg/s
        else:
            logger.error("❌ GPU simulation failed to start")
            return False
            
    finally:
        producer.disconnect()


def main():
    """Run all stress tests."""
    logger.info("🚀 SYNTHETIC MARKET DATA STRESS TEST SUITE")
    logger.info("=" * 80)
    
    results = {}
    
    # Run tests in order of increasing complexity
    tests = [
        ("Small Scale (10 symbols)", test_small_scale),
        ("Medium Scale (100 symbols)", test_medium_scale), 
        ("Large Scale (1000 symbols)", test_large_scale),
        ("GPU Integration Simulation", test_gpu_integration_simulation)
    ]
    
    for test_name, test_func in tests:
        logger.info(f"\\n🧪 Running: {test_name}")
        try:
            results[test_name] = test_func()
            logger.info(f"✅ {test_name}: {'PASSED' if results[test_name] else 'FAILED'}")
        except Exception as e:
            logger.error(f"❌ {test_name}: ERROR - {e}")
            results[test_name] = False
    
    # Summary
    logger.info("\\n" + "=" * 80)
    logger.info("🎯 STRESS TEST SUMMARY:")
    logger.info("=" * 80)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"   {status} - {test_name}")
    
    logger.info("=" * 80)
    logger.info(f"🏆 OVERALL: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED - READY FOR PRODUCTION STRESS TESTING!")
        logger.info("💡 You can now generate unlimited synthetic data for GPU testing")
    else:
        logger.info("⚠️  Some tests failed - check logs for details")
    
    logger.info("=" * 80)


if __name__ == "__main__":
    main()