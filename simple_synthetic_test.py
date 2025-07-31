#!/usr/bin/env python3
"""
Simple Synthetic Data Producer Test

Demonstrates the synthetic data capability without complex imports.
Shows how you can generate unlimited market data for stress testing.
"""

import time
import random
import threading
import queue
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


class SimpleSyntheticProducer:
    """Simple synthetic market data producer for testing."""
    
    def __init__(
        self,
        symbols: List[str],
        messages_per_second_per_symbol: float = 10.0,
        price_variation_pct: float = 2.0
    ):
        self.symbols = symbols
        self.msg_rate = messages_per_second_per_symbol  
        self.price_variation = price_variation_pct
        
        # Initialize symbol states
        self.symbol_states = {}
        for symbol in symbols:
            base_price = random.uniform(50, 200)  # Random base price
            spread = base_price * 0.001  # 0.1% spread
            
            self.symbol_states[symbol] = {
                'price': base_price,
                'bid': base_price - spread/2,
                'ask': base_price + spread/2,
                'volume': 0,
                'tick_id': 0
            }
        
        self.output_queue = queue.Queue(maxsize=10000)
        self.running = False
        self.threads = []
        self.messages_generated = 0
        self.start_time = None
    
    def start(self):
        """Start generating synthetic data."""
        self.running = True
        self.start_time = time.time()
        
        # Create worker threads
        for i in range(min(10, len(self.symbols))):  # Max 10 threads
            symbols_chunk = self.symbols[i::10]  # Distribute symbols
            thread = threading.Thread(
                target=self._worker,
                args=(symbols_chunk,),
                daemon=True
            )
            thread.start()
            self.threads.append(thread)
        
        print(f"✅ Started synthetic producer for {len(self.symbols)} symbols")
        print(f"   Expected rate: {len(self.symbols) * self.msg_rate:.0f} messages/second")
    
    def _worker(self, symbols_chunk: List[str]):
        """Worker thread for generating data."""
        interval = 1.0 / self.msg_rate
        next_times = {symbol: time.time() for symbol in symbols_chunk}
        
        while self.running:
            current_time = time.time()
            
            for symbol in symbols_chunk:
                if current_time >= next_times[symbol]:
                    # Generate message
                    message = self._generate_message(symbol)
                    
                    try:
                        self.output_queue.put_nowait(message)
                        self.messages_generated += 1
                    except queue.Full:
                        pass  # Drop if queue full
                    
                    # Schedule next message
                    jitter = random.uniform(0.5, 1.5)
                    next_times[symbol] = current_time + (interval * jitter)
            
            time.sleep(0.001)  # Small sleep
    
    def _generate_message(self, symbol: str) -> Dict[str, Any]:
        """Generate a synthetic market message."""
        state = self.symbol_states[symbol]
        
        # Update price with random walk
        price_change = random.gauss(0, state['price'] * self.price_variation / 100 / 100)
        state['price'] = max(0.01, state['price'] + price_change)
        
        # Update bid/ask
        spread = state['price'] * 0.001
        state['bid'] = state['price'] - spread/2
        state['ask'] = state['price'] + spread/2
        state['tick_id'] += 1
        
        # Choose message type
        msg_type = random.choice(['T', 'Q', 'U'])
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:-3]
        
        if msg_type == 'T':  # Trade
            size = random.randint(100, 1000)
            state['volume'] += size
            raw_message = f"T,{symbol},{timestamp},{state['price']:.4f},{size},{state['volume']},NASDAQ,F,{state['tick_id']},{state['bid']:.4f},{state['ask']:.4f}"
        
        elif msg_type == 'Q':  # Quote
            bid_size = random.randint(100, 2000)
            ask_size = random.randint(100, 2000)
            raw_message = f"Q,{symbol},{timestamp},{state['bid']:.4f},{bid_size},{state['ask']:.4f},{ask_size},NYSE,NASDAQ,{state['tick_id']}"
        
        else:  # L2 Update
            level = random.randint(0, 4)
            side = random.randint(0, 1)
            price = state['bid'] if side == 1 else state['ask']
            price += random.uniform(-spread, spread)
            size = random.randint(100, 1000)
            operation = random.randint(0, 1)
            raw_message = f"U,{symbol},{timestamp},{side},{level},MM{random.randint(1,5)},{price:.4f},{size},{operation}"
        
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': symbol,
            'message_type': msg_type,
            'raw_message': raw_message,
            'synthetic': True
        }
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get next synthetic message."""
        try:
            return self.output_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get producer statistics."""
        uptime = time.time() - self.start_time if self.start_time else 0
        rate = self.messages_generated / uptime if uptime > 0 else 0
        
        return {
            'symbols': len(self.symbols),
            'messages_generated': self.messages_generated,
            'rate_msg_per_sec': rate,
            'expected_rate': len(self.symbols) * self.msg_rate,
            'queue_size': self.output_queue.qsize(),
            'uptime_seconds': uptime
        }
    
    def stop(self):
        """Stop the producer."""
        self.running = False
        for thread in self.threads:
            thread.join(timeout=1.0)


def test_synthetic_producer():
    """Test the synthetic producer with different scales."""
    print("🧪 SYNTHETIC MARKET DATA PRODUCER TEST")
    print("=" * 80)
    
    # Test configurations
    test_configs = [
        {"name": "Small Scale", "symbols": 10, "rate": 5.0, "duration": 10},
        {"name": "Medium Scale", "symbols": 100, "rate": 8.0, "duration": 15},
        {"name": "Large Scale", "symbols": 500, "rate": 10.0, "duration": 20}
    ]
    
    for config in test_configs:
        print(f"\\n🚀 {config['name']} Test:")
        print(f"   - Symbols: {config['symbols']}")
        print(f"   - Rate: {config['rate']} msg/s per symbol")
        print(f"   - Expected total: {config['symbols'] * config['rate']:.0f} msg/s")
        
        # Create symbols
        symbols = [f"SYN{i:04d}" for i in range(config['symbols'])]
        
        # Create producer
        producer = SimpleSyntheticProducer(
            symbols=symbols,
            messages_per_second_per_symbol=config['rate'],
            price_variation_pct=1.5
        )
        
        try:
            producer.start()
            
            # Monitor for specified duration
            start_time = time.time()
            message_counts = {'T': 0, 'Q': 0, 'U': 0}
            sample_messages = []
            
            while time.time() - start_time < config['duration']:
                message = producer.get_next_message(timeout=0.1)
                
                if message:
                    msg_type = message.get('message_type', 'Unknown')
                    message_counts[msg_type] = message_counts.get(msg_type, 0) + 1
                    
                    # Keep some samples
                    if len(sample_messages) < 3:
                        sample_messages.append(message)
                
                # Periodic stats
                if int(time.time() - start_time) % 5 == 0:
                    stats = producer.get_statistics()
                    if stats['messages_generated'] > 0:
                        print(f"   📊 {stats['messages_generated']:,} messages @ {stats['rate_msg_per_sec']:.0f} msg/s (target: {stats['expected_rate']:.0f})")
            
            # Final results
            final_stats = producer.get_statistics()
            total_messages = sum(message_counts.values())
            efficiency = (final_stats['rate_msg_per_sec'] / final_stats['expected_rate']) * 100 if final_stats['expected_rate'] > 0 else 0
            
            print(f"   ✅ RESULTS:")
            print(f"      - Total Messages: {total_messages:,}")
            print(f"      - Actual Rate: {final_stats['rate_msg_per_sec']:.0f} msg/s")
            print(f"      - Efficiency: {efficiency:.1f}%")
            print(f"      - Trades (T): {message_counts.get('T', 0):,}")
            print(f"      - Quotes (Q): {message_counts.get('Q', 0):,}")
            print(f"      - L2 Updates (U): {message_counts.get('U', 0):,}")
            
            # Show sample messages
            print(f"   📨 Sample Messages:")
            for i, msg in enumerate(sample_messages[:3]):
                print(f"      {i+1}. {msg['message_type']}: {msg['raw_message'][:70]}...")
        
        finally:
            producer.stop()
    
    print("\\n" + "=" * 80)
    print("🎯 SYNTHETIC DATA PRODUCER READY!")
    print("💡 You can now generate unlimited market data for:")
    print("   - GPU function stress testing")
    print("   - Algorithm validation")
    print("   - Performance benchmarking")
    print("   - Any number of symbols (tested up to 500)")
    print("=" * 80)


def demonstrate_gpu_simulation():
    """Demonstrate how synthetic data can be used for GPU testing."""
    print("\\n🧠 GPU FUNCTION SIMULATION DEMO")
    print("=" * 60)
    
    # Create producer for GPU simulation
    symbols = [f"GPU{i:03d}" for i in range(50)]  # 50 symbols
    producer = SimpleSyntheticProducer(
        symbols=symbols,
        messages_per_second_per_symbol=12.0,  # 600 msg/s total
        price_variation_pct=2.0
    )
    
    try:
        producer.start()
        print("✅ Synthetic producer started for GPU simulation")
        
        # Simulate GPU batch processing
        batch_size = 100
        batches_processed = 0
        total_messages = 0
        
        start_time = time.time()
        
        while time.time() - start_time < 20:  # Run for 20 seconds
            # Collect a batch
            batch = []
            batch_start = time.time()
            
            while len(batch) < batch_size and time.time() - batch_start < 1.0:
                message = producer.get_next_message(timeout=0.05)
                if message:
                    batch.append(message)
            
            if batch:
                # Simulate GPU processing
                gpu_start = time.time()
                
                # Example processing: count message types
                trade_count = sum(1 for m in batch if m.get('message_type') == 'T')
                quote_count = sum(1 for m in batch if m.get('message_type') == 'Q')
                l2_count = sum(1 for m in batch if m.get('message_type') == 'U')
                
                # Simulate computation time
                time.sleep(len(batch) * 0.0001)  # 0.1ms per message
                
                gpu_time = time.time() - gpu_start
                batches_processed += 1
                total_messages += len(batch)
                
                if batches_processed % 5 == 0:
                    elapsed = time.time() - start_time
                    processing_rate = total_messages / elapsed
                    
                    print(f"   🎯 Batch {batches_processed}: {len(batch)} messages "
                          f"(T:{trade_count}, Q:{quote_count}, L2:{l2_count}) "
                          f"in {gpu_time*1000:.1f}ms")
                    print(f"      Processing rate: {processing_rate:.0f} msg/s")
        
        # Final results
        final_elapsed = time.time() - start_time
        final_rate = total_messages / final_elapsed
        
        print(f"\\n   🏆 GPU SIMULATION RESULTS:")
        print(f"      - Batches Processed: {batches_processed}")
        print(f"      - Messages Processed: {total_messages:,}")
        print(f"      - Processing Rate: {final_rate:.0f} messages/second")
        print(f"      - Average Batch Size: {total_messages/batches_processed:.1f}")
        
    finally:
        producer.stop()


if __name__ == "__main__":
    test_synthetic_producer()
    demonstrate_gpu_simulation()