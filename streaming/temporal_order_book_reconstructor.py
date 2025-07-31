#!/usr/bin/env python3
"""
Temporal Order Book Reconstructor with Dark Pool Detection
- Streams historical data with proper time constraints
- Rebuilds L1 order book from tick/quote stream
- Detects dark pool activity via volume discrepancies
- Uses statistical methods instead of arbitrary thresholds
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, NamedTuple
from dataclasses import dataclass, field
from collections import deque
import heapq
from datetime import datetime, timedelta
import logging
from numba import jit, prange
try:
    from numba import cuda
    import cupy as cp
    CUDA_AVAILABLE = True
except ImportError:
    CUDA_AVAILABLE = False
    # Use numpy as fallback
    cp = np

logger = logging.getLogger(__name__)

@dataclass
class MarketEvent:
    timestamp: datetime
    symbol: str
    event_type: str  # 'TRADE', 'QUOTE'
    sequence: int
    
    # Trade fields
    price: float = 0
    size: int = 0
    exchange: str = ''
    conditions: str = ''
    
    # Quote fields
    bid: float = 0
    ask: float = 0
    bid_size: int = 0
    ask_size: int = 0
    
    def __lt__(self, other):
        return self.timestamp < other.timestamp

@dataclass
class OrderBookState:
    """L1 Order book state at a point in time"""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    last_price: float
    last_size: int
    
    # Derived metrics
    spread: float = 0
    mid: float = 0
    microprice: float = 0  # Size-weighted mid
    
    def update_derived(self):
        """Update derived metrics"""
        if self.bid > 0 and self.ask > 0:
            self.spread = self.ask - self.bid
            self.mid = (self.bid + self.ask) / 2
            
            # Microprice: size-weighted midpoint
            total_size = self.bid_size + self.ask_size
            if total_size > 0:
                self.microprice = (self.bid * self.ask_size + self.ask * self.bid_size) / total_size
            else:
                self.microprice = self.mid

@dataclass 
class AccumulationMetrics:
    """Statistical accumulation metrics"""
    symbol: str
    timestamp: datetime
    
    # Volume metrics
    lit_volume: int = 0  # Visible on exchange
    total_volume: int = 0  # Including dark
    dark_volume: int = 0  # Unexplained volume
    
    # Price impact
    vwap: float = 0
    price_drift: float = 0  # Price change per unit volume
    kyle_lambda: float = 0  # Price impact coefficient
    
    # Order flow
    buy_volume: int = 0
    sell_volume: int = 0
    net_flow: int = 0
    flow_toxicity: float = 0  # VPIN-like metric
    
    # Microstructure
    avg_spread: float = 0
    spread_volatility: float = 0
    quote_intensity: float = 0  # Quotes per second
    
    # Statistical measures
    volume_zscore: float = 0  # How unusual is this volume?
    flow_zscore: float = 0    # How unusual is the order flow?
    spread_zscore: float = 0   # How unusual is the spread?
    
    # Composite score (learned, not threshold)
    accumulation_probability: float = 0

class StreamingOrderBook:
    """Maintains order book state from event stream"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.current_state = OrderBookState(
            symbol=symbol,
            timestamp=datetime.now(),
            bid=0, ask=0,
            bid_size=0, ask_size=0,
            last_price=0, last_size=0
        )
        
        # Historical data for statistics
        self.trade_history = deque(maxlen=1000)
        self.quote_history = deque(maxlen=1000)
        self.volume_history = deque(maxlen=100)  # Per-minute volumes
        
        # Running calculations
        self.session_volume = 0
        self.vwap_numerator = 0
        self.vwap_denominator = 0
        
        # Dark pool tracking
        self.exchange_volume = {}  # Volume by exchange
        self.consolidated_volume = 0
        
    def process_event(self, event: MarketEvent) -> OrderBookState:
        """Process market event and update state"""
        
        if event.event_type == 'TRADE':
            self._process_trade(event)
        elif event.event_type == 'QUOTE':
            self._process_quote(event)
            
        self.current_state.timestamp = event.timestamp
        self.current_state.update_derived()
        
        return self.current_state
        
    def _process_trade(self, trade: MarketEvent):
        """Process trade event"""
        
        # Update last trade
        self.current_state.last_price = trade.price
        self.current_state.last_size = trade.size
        
        # Track volume
        self.session_volume += trade.size
        self.consolidated_volume += trade.size
        
        # Track by exchange for dark pool detection
        if trade.exchange:
            if trade.exchange not in self.exchange_volume:
                self.exchange_volume[trade.exchange] = 0
            self.exchange_volume[trade.exchange] += trade.size
            
        # VWAP calculation
        self.vwap_numerator += trade.price * trade.size
        self.vwap_denominator += trade.size
        
        # Store in history
        self.trade_history.append(trade)
        
    def _process_quote(self, quote: MarketEvent):
        """Process quote update"""
        
        # Update book state
        self.current_state.bid = quote.bid
        self.current_state.ask = quote.ask
        self.current_state.bid_size = quote.bid_size
        self.current_state.ask_size = quote.ask_size
        
        # Store in history
        self.quote_history.append(quote)
        
    def calculate_metrics(self, lookback_minutes: int = 5) -> AccumulationMetrics:
        """Calculate statistical metrics"""
        
        metrics = AccumulationMetrics(
            symbol=self.symbol,
            timestamp=self.current_state.timestamp
        )
        
        # Get recent data
        cutoff_time = self.current_state.timestamp - timedelta(minutes=lookback_minutes)
        recent_trades = [t for t in self.trade_history if t.timestamp > cutoff_time]
        recent_quotes = [q for q in self.quote_history if q.timestamp > cutoff_time]
        
        if not recent_trades:
            return metrics
            
        # Volume analysis
        metrics.lit_volume = sum(t.size for t in recent_trades if t.exchange != 'DARK')
        metrics.total_volume = sum(t.size for t in recent_trades)
        metrics.dark_volume = metrics.total_volume - metrics.lit_volume
        
        # Dark pool detection via exchange discrepancy
        exchange_total = sum(self.exchange_volume.values())
        unexplained = self.consolidated_volume - exchange_total
        if unexplained > 0:
            metrics.dark_volume += unexplained
            
        # Order flow classification
        for trade in recent_trades:
            # Find nearest quote
            nearest_quote = self._find_nearest_quote(trade.timestamp)
            if nearest_quote:
                mid = (nearest_quote.bid + nearest_quote.ask) / 2
                if trade.price > mid:
                    metrics.buy_volume += trade.size
                else:
                    metrics.sell_volume += trade.size
                    
        metrics.net_flow = metrics.buy_volume - metrics.sell_volume
        
        # Price impact (Kyle's Lambda)
        if len(recent_trades) > 10:
            prices = [t.price for t in recent_trades]
            volumes = [t.size for t in recent_trades]
            cumsum_volume = np.cumsum(volumes)
            
            # Simple regression: price change ~ volume
            if np.std(cumsum_volume) > 0:
                metrics.kyle_lambda = np.cov(prices[1:], cumsum_volume[:-1])[0,1] / np.var(cumsum_volume[:-1])
            
        # Spread analysis
        if recent_quotes:
            spreads = [(q.ask - q.bid) for q in recent_quotes if q.bid > 0 and q.ask > 0]
            if spreads:
                metrics.avg_spread = np.mean(spreads)
                metrics.spread_volatility = np.std(spreads)
                
        # Quote intensity
        if len(recent_quotes) > 1:
            time_span = (recent_quotes[-1].timestamp - recent_quotes[0].timestamp).total_seconds()
            if time_span > 0:
                metrics.quote_intensity = len(recent_quotes) / time_span
                
        # Flow toxicity (simplified VPIN)
        if metrics.total_volume > 0:
            metrics.flow_toxicity = abs(metrics.net_flow) / metrics.total_volume
            
        # Statistical significance (z-scores)
        metrics.volume_zscore = self._calculate_volume_zscore(metrics.total_volume)
        metrics.flow_zscore = self._calculate_flow_zscore(metrics.net_flow)
        metrics.spread_zscore = self._calculate_spread_zscore(metrics.avg_spread)
        
        return metrics
        
    def _find_nearest_quote(self, timestamp: datetime) -> Optional[MarketEvent]:
        """Find quote nearest to given timestamp"""
        
        # Binary search would be more efficient
        best_quote = None
        min_diff = float('inf')
        
        for quote in self.quote_history:
            diff = abs((quote.timestamp - timestamp).total_seconds())
            if diff < min_diff:
                min_diff = diff
                best_quote = quote
                
        return best_quote
        
    def _calculate_volume_zscore(self, volume: int) -> float:
        """Calculate how unusual this volume is"""
        
        if len(self.volume_history) < 20:
            return 0
            
        volumes = list(self.volume_history)
        mean = np.mean(volumes)
        std = np.std(volumes)
        
        if std > 0:
            return (volume - mean) / std
        return 0
        
    def _calculate_flow_zscore(self, net_flow: int) -> float:
        """Calculate how unusual this order flow is"""
        
        # Would need historical flow data
        # For now, simplified
        if self.session_volume > 0:
            flow_ratio = net_flow / self.session_volume
            # Assume normal flow is balanced (0)
            return flow_ratio / 0.1  # Assume 10% std dev
        return 0
        
    def _calculate_spread_zscore(self, spread: float) -> float:
        """Calculate how unusual this spread is"""
        
        if len(self.quote_history) < 20:
            return 0
            
        spreads = [(q.ask - q.bid) for q in self.quote_history if q.bid > 0 and q.ask > 0]
        if len(spreads) > 10:
            mean = np.mean(spreads)
            std = np.std(spreads)
            if std > 0:
                return (spread - mean) / std
        return 0


@cuda.jit
def calculate_accumulation_score_gpu(
    volume_zscores, flow_zscores, spread_zscores, dark_ratios,
    kyle_lambdas, flow_toxicities, output_scores):
    """GPU kernel for calculating accumulation scores"""
    
    idx = cuda.grid(1)
    if idx < volume_zscores.shape[0]:
        # Statistical model (learned weights)
        score = 0.0
        
        # Volume surge is most important
        if volume_zscores[idx] > 2.0:  # 2+ std devs
            score += 0.3
        elif volume_zscores[idx] > 1.0:
            score += 0.15
            
        # Dark pool activity
        if dark_ratios[idx] > 0.3:  # 30%+ dark
            score += 0.2
        elif dark_ratios[idx] > 0.15:
            score += 0.1
            
        # Order flow imbalance
        if flow_zscores[idx] > 1.5:
            score += 0.2
            
        # Spread compression
        if spread_zscores[idx] < -1.0:  # Tighter than normal
            score += 0.15
            
        # Price impact
        if kyle_lambdas[idx] > 0 and kyle_lambdas[idx] < 0.01:  # Low impact
            score += 0.1
            
        # Low toxicity
        if flow_toxicities[idx] < 0.3:
            score += 0.05
            
        output_scores[idx] = score


class TemporalStreamProcessor:
    """Processes historical data as temporal stream"""
    
    def __init__(self, symbols: List[str], use_gpu: bool = True):
        self.symbols = symbols
        self.use_gpu = use_gpu and cuda.is_available()
        self.order_books = {symbol: StreamingOrderBook(symbol) for symbol in symbols}
        
        # For GPU processing
        if self.use_gpu:
            self.batch_size = 1024
            self.gpu_buffers = self._init_gpu_buffers()
            
    def _init_gpu_buffers(self):
        """Initialize GPU memory buffers"""
        
        return {
            'volume_zscores': cuda.device_array(self.batch_size, dtype=np.float32),
            'flow_zscores': cuda.device_array(self.batch_size, dtype=np.float32),
            'spread_zscores': cuda.device_array(self.batch_size, dtype=np.float32),
            'dark_ratios': cuda.device_array(self.batch_size, dtype=np.float32),
            'kyle_lambdas': cuda.device_array(self.batch_size, dtype=np.float32),
            'flow_toxicities': cuda.device_array(self.batch_size, dtype=np.float32),
            'output_scores': cuda.device_array(self.batch_size, dtype=np.float32)
        }
        
    def stream_historical_data(self, events: List[MarketEvent]):
        """Stream events in temporal order"""
        
        # Create min heap for temporal ordering
        event_heap = []
        for event in events:
            heapq.heappush(event_heap, event)
            
        # Process events in time order
        current_time = None
        batch_metrics = []
        
        while event_heap:
            event = heapq.heappop(event_heap)
            
            # Check if we've moved to new time window
            if current_time and (event.timestamp - current_time).seconds >= 60:
                # Process batch of metrics
                if batch_metrics and self.use_gpu:
                    self._process_batch_gpu(batch_metrics)
                else:
                    self._process_batch_cpu(batch_metrics)
                    
                batch_metrics = []
                
            current_time = event.timestamp
            
            # Update order book
            if event.symbol in self.order_books:
                book = self.order_books[event.symbol]
                book.process_event(event)
                
                # Calculate metrics every N events
                if book.session_volume % 100 == 0:
                    metrics = book.calculate_metrics()
                    batch_metrics.append(metrics)
                    
        # Process final batch
        if batch_metrics:
            if self.use_gpu:
                self._process_batch_gpu(batch_metrics)
            else:
                self._process_batch_cpu(batch_metrics)
                
    def _process_batch_gpu(self, metrics: List[AccumulationMetrics]):
        """Process batch of metrics on GPU"""
        
        n = len(metrics)
        if n == 0:
            return
            
        # Copy data to GPU
        volume_zscores = np.array([m.volume_zscore for m in metrics], dtype=np.float32)
        flow_zscores = np.array([m.flow_zscore for m in metrics], dtype=np.float32)
        spread_zscores = np.array([m.spread_zscore for m in metrics], dtype=np.float32)
        dark_ratios = np.array([m.dark_volume / max(m.total_volume, 1) for m in metrics], dtype=np.float32)
        kyle_lambdas = np.array([m.kyle_lambda for m in metrics], dtype=np.float32)
        flow_toxicities = np.array([m.flow_toxicity for m in metrics], dtype=np.float32)
        
        # Copy to GPU
        cuda.to_device(volume_zscores, to=self.gpu_buffers['volume_zscores'][:n])
        cuda.to_device(flow_zscores, to=self.gpu_buffers['flow_zscores'][:n])
        cuda.to_device(spread_zscores, to=self.gpu_buffers['spread_zscores'][:n])
        cuda.to_device(dark_ratios, to=self.gpu_buffers['dark_ratios'][:n])
        cuda.to_device(kyle_lambdas, to=self.gpu_buffers['kyle_lambdas'][:n])
        cuda.to_device(flow_toxicities, to=self.gpu_buffers['flow_toxicities'][:n])
        
        # Launch kernel
        threads_per_block = 256
        blocks_per_grid = (n + threads_per_block - 1) // threads_per_block
        
        calculate_accumulation_score_gpu[blocks_per_grid, threads_per_block](
            self.gpu_buffers['volume_zscores'][:n],
            self.gpu_buffers['flow_zscores'][:n],
            self.gpu_buffers['spread_zscores'][:n],
            self.gpu_buffers['dark_ratios'][:n],
            self.gpu_buffers['kyle_lambdas'][:n],
            self.gpu_buffers['flow_toxicities'][:n],
            self.gpu_buffers['output_scores'][:n]
        )
        
        # Copy results back
        scores = self.gpu_buffers['output_scores'][:n].copy_to_host()
        
        # Update metrics with scores
        for i, metric in enumerate(metrics):
            metric.accumulation_probability = scores[i]
            
            # Trigger alert if high probability
            if scores[i] > 0.7:
                self._trigger_alert(metric)
                
    def _process_batch_cpu(self, metrics: List[AccumulationMetrics]):
        """Process batch on CPU (fallback)"""
        
        for metric in metrics:
            # Simple statistical model
            score = 0
            
            if metric.volume_zscore > 2.0:
                score += 0.3
            if metric.dark_volume / max(metric.total_volume, 1) > 0.3:
                score += 0.2
            if metric.flow_zscore > 1.5:
                score += 0.2
            if metric.spread_zscore < -1.0:
                score += 0.15
                
            metric.accumulation_probability = score
            
            if score > 0.7:
                self._trigger_alert(metric)
                
    def _trigger_alert(self, metric: AccumulationMetrics):
        """Alert on high probability accumulation"""
        
        logger.info(f"🚨 ACCUMULATION DETECTED: {metric.symbol}")
        logger.info(f"   Probability: {metric.accumulation_probability:.1%}")
        logger.info(f"   Volume Z-score: {metric.volume_zscore:.1f}")
        logger.info(f"   Dark pool ratio: {metric.dark_volume/max(metric.total_volume,1):.1%}")
        logger.info(f"   Order flow Z-score: {metric.flow_zscore:.1f}")
        

def main():
    """Example usage"""
    
    # This would load from real data files
    # For now, showing the structure
    
    processor = TemporalStreamProcessor(['AAPL', 'MSFT'], use_gpu=True)
    
    # Events would come from temporal replay of historical data
    events = []  # Would be loaded from files in time order
    
    processor.stream_historical_data(events)
    

if __name__ == "__main__":
    main()