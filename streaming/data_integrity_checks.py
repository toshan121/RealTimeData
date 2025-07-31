#!/usr/bin/env python3
"""
Data Integrity Checks for Trading Simulator
Comprehensive validation and anomaly detection throughout the pipeline
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


class DataIntegrityChecker:
    """Comprehensive data integrity and anomaly detection"""
    
    def __init__(self):
        # Track data quality metrics
        self.missing_data_count = 0
        self.invalid_data_count = 0
        self.anomaly_count = 0
        
        # Historical data for validation
        self.price_history = {}
        self.spread_history = {}
        self.volume_history = {}
        
        # Anomaly thresholds
        self.max_price_change_pct = 0.10  # 10% max price move
        self.max_spread_ratio = 0.05  # 5% of price max spread
        self.min_bid_ask_ratio = 0.90  # Bid should be > 90% of ask
        self.max_size_ratio = 100  # Max size vs avg ratio
        
        # Track last known good state
        self.last_good_state = {}
        
        # Statistics
        self.checks_performed = 0
        self.issues_found = []
        
        # Track data ordering
        self.data_ordering = {}  # symbol -> 'ascending', 'descending', or 'mixed'
        
    def validate_tick_data(self, ticks: List[Dict]) -> Tuple[bool, List[str]]:
        """Validate tick data structure and values INCLUDING TIMESTAMP ORDER"""
        issues = []
        
        if not ticks:
            return False, ["No tick data provided"]
            
        # CRITICAL: Check timestamp ordering
        timestamps = [tick.get('timestamp', '') for tick in ticks]
        if len(timestamps) > 1:
            # Check if chronologically ordered
            is_ascending = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))
            is_descending = all(timestamps[i] >= timestamps[i+1] for i in range(len(timestamps)-1))
            
            if is_descending and not is_ascending:
                issues.append("CRITICAL: Data is in REVERSE chronological order (newest first)")
                issues.append(f"First timestamp (CLOSING): {timestamps[0]}")
                issues.append(f"Last timestamp (OPENING): {timestamps[-1]}")
                issues.append("PRICES: First price = CLOSE, Last price = OPEN")
                
                # Extract symbol if available
                symbol = ticks[0].get('symbol', 'UNKNOWN')
                self.data_ordering[symbol] = 'descending'
                
            elif is_ascending and not is_descending:
                # Normal order
                symbol = ticks[0].get('symbol', 'UNKNOWN')
                self.data_ordering[symbol] = 'ascending'
            else:
                issues.append("WARNING: Data has mixed timestamp ordering!")
                symbol = ticks[0].get('symbol', 'UNKNOWN')
                self.data_ordering[symbol] = 'mixed'
                
        # Sample validation on first few ticks
        sample_size = min(100, len(ticks))
        
        for i, tick in enumerate(ticks[:sample_size]):
            # Check required fields
            required_fields = ['timestamp', 'price', 'size']
            missing = [f for f in required_fields if f not in tick]
            if missing:
                issues.append(f"Tick {i} missing fields: {missing}")
                continue
                
            # Basic value validation
            if tick['price'] <= 0:
                issues.append(f"Tick {i}: Invalid price {tick['price']}")
            if tick['size'] < 0:
                issues.append(f"Tick {i}: Invalid size {tick['size']}")
                
        return len(issues) == 0, issues
        
    def check_tick_data(self, symbol: str, price: float, size: int, 
                       bid: float, ask: float, conditions: str, 
                       timestamp: datetime) -> Tuple[bool, List[str]]:
        """
        Check tick data for anomalies and integrity issues
        Returns (is_valid, list_of_issues)
        """
        issues = []
        self.checks_performed += 1
        
        # 1. Basic validation
        if price <= 0:
            issues.append(f"Invalid price: {price}")
            self.invalid_data_count += 1
            
        if size < 0:
            issues.append(f"Invalid size: {size}")
            self.invalid_data_count += 1
            
        # 2. Bid/Ask validation - more lenient
        if bid > 0 and ask > 0:
            if bid > ask:
                issues.append(f"Crossed market: bid {bid} > ask {ask}")
                self.anomaly_count += 1
                
            spread = ask - bid
            # Only flag truly excessive spreads (>10% for low-priced stocks)
            max_spread = max(0.02, price * self.max_spread_ratio)  # Min 2 cents
            if spread > max_spread:
                issues.append(f"Excessive spread: ${spread:.3f} ({spread/price*100:.1f}% of price)")
                self.anomaly_count += 1
                
            # Remove the bid/ask ratio check - it's too strict
        
        # 3. Price movement validation
        if symbol in self.price_history and self.price_history[symbol]:
            last_prices = list(self.price_history[symbol])
            last_price = last_prices[-1]
            
            price_change = abs(price - last_price) / last_price
            if price_change > self.max_price_change_pct:
                issues.append(f"Excessive price move: {price_change*100:.1f}% from ${last_price:.2f} to ${price:.2f}")
                self.anomaly_count += 1
                
            # Check for stuck prices (no movement in many ticks)
            if len(last_prices) >= 100 and all(p == price for p in last_prices[-50:]):
                issues.append(f"Price stuck at ${price:.2f} for 50+ ticks")
                self.anomaly_count += 1
        
        # 4. Volume anomaly detection  
        if symbol in self.volume_history and len(self.volume_history[symbol]) >= 100:
            volumes = list(self.volume_history[symbol])
            avg_volume = np.mean(volumes)
            
            if size > avg_volume * self.max_size_ratio:
                issues.append(f"Abnormal size: {size} (avg: {avg_volume:.0f})")
                self.anomaly_count += 1
                
        # 5. Timestamp validation - HANDLE REVERSE ORDER
        if symbol in self.last_good_state:
            last_timestamp = self.last_good_state[symbol]['timestamp']
            
            # Check ordering based on what we know about this symbol
            if symbol in self.data_ordering:
                if self.data_ordering[symbol] == 'descending':
                    # Reverse order - timestamps should be decreasing
                    if timestamp > last_timestamp:
                        issues.append(f"Timestamp order violation (expecting descending): {timestamp} > {last_timestamp}")
                elif self.data_ordering[symbol] == 'ascending':
                    # Normal order - timestamps should be increasing
                    if timestamp < last_timestamp:
                        issues.append(f"Timestamp order violation (expecting ascending): {timestamp} < {last_timestamp}")
            else:
                # We don't know the order yet, so check both ways
                if timestamp < last_timestamp:
                    # Could be backward timestamp or descending order
                    pass  # Don't flag as issue yet
                    
            # Check for large time gaps (> 1 minute during market hours)
            time_diff = abs((timestamp - last_timestamp).total_seconds())
            if 9.5 <= timestamp.hour <= 16 and time_diff > 60:
                issues.append(f"Large time gap: {time_diff:.0f}s")
                self.missing_data_count += 1
        
        # 6. Trading conditions validation
        if conditions:
            # Check for unusual conditions
            unusual_conditions = set(conditions) - set('ETMWNOISC')
            if unusual_conditions:
                issues.append(f"Unusual conditions: {unusual_conditions}")
                
        # Update history
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=1000)
            self.volume_history[symbol] = deque(maxlen=1000)
            
        self.price_history[symbol].append(price)
        self.volume_history[symbol].append(size)
        
        # Save good state if valid
        if not issues:
            self.last_good_state[symbol] = {
                'price': price,
                'size': size,
                'bid': bid,
                'ask': ask,
                'timestamp': timestamp
            }
            
        # Log issues if found (only log critical ones to avoid spam)
        if issues:
            self.issues_found.extend([(timestamp, symbol, issue) for issue in issues])
            # Only log critical issues, not common ones like zero sizes
            critical_issues = [i for i in issues if 'Invalid' in i or 'Excessive' in i or 'Crossed' in i or 'CRITICAL' in i]
            if critical_issues:
                logger.warning(f"Data integrity issues for {symbol}: {', '.join(critical_issues)}")
            
        return len(issues) == 0, issues
    
    def check_quote_data(self, symbol: str, bid: float, ask: float,
                        bid_size: int, ask_size: int, 
                        timestamp: datetime) -> Tuple[bool, List[str]]:
        """Check quote data integrity"""
        issues = []
        self.checks_performed += 1
        
        # 1. Basic validation
        if bid <= 0 or ask <= 0:
            issues.append(f"Invalid quote: bid={bid}, ask={ask}")
            self.invalid_data_count += 1
            return False, issues
            
        if bid_size < 0 or ask_size < 0:
            issues.append(f"Invalid sizes: bid_size={bid_size}, ask_size={ask_size}")
            self.invalid_data_count += 1
            
        # 2. Spread validation - more lenient
        spread = ask - bid
        if spread < 0:  # Only negative spreads are truly invalid
            issues.append(f"Invalid spread: {spread}")
            self.invalid_data_count += 1
        elif spread == 0:
            # Zero spread is OK (can happen at close or in fast markets)
            pass
            
        if symbol not in self.spread_history:
            self.spread_history[symbol] = deque(maxlen=1000)
            
        if spread >= 0:  # Only track valid spreads
            self.spread_history[symbol].append(spread)
        
        # Check for spread anomalies only if we have history
        if spread > 0 and len(self.spread_history[symbol]) >= 100:
            spreads = list(self.spread_history[symbol])
            avg_spread = np.mean(spreads[-100:-10]) if len(spreads) > 110 else np.mean(spreads)
            
            if avg_spread > 0 and spread > avg_spread * 10:  # More lenient - 10x instead of 5x
                issues.append(f"Spread 10x normal: ${spread:.3f} vs avg ${avg_spread:.3f}")
                self.anomaly_count += 1
                
        # 3. Size validation - zero sizes are valid (no liquidity)
        # Don't flag this as an issue, just track it
        if bid_size == 0 and ask_size == 0:
            # This is valid - market might have no liquidity temporarily
            pass
            
        # Log issues (only critical ones)
        if issues:
            self.issues_found.extend([(timestamp, symbol, issue) for issue in issues])
            # Only log critical issues 
            critical_issues = [i for i in issues if 'Invalid' in i and 'sizes are zero' not in i]
            if critical_issues:
                logger.warning(f"Quote integrity issues for {symbol}: {', '.join(critical_issues)}")
            
        return len(issues) == 0, issues
    
    def check_position_data(self, symbol: str, entry_price: float,
                           current_price: float, position_size: int,
                           stop_loss: float) -> Tuple[bool, List[str]]:
        """Check position data for anomalies"""
        issues = []
        
        # 1. Price sanity checks
        if entry_price <= 0 or current_price <= 0:
            issues.append(f"Invalid prices: entry={entry_price}, current={current_price}")
            
        # 2. Position size validation
        if position_size <= 0:
            issues.append(f"Invalid position size: {position_size}")
            
        if position_size > 10000:
            issues.append(f"Excessive position size: {position_size}")
            
        # 3. Stop loss validation
        if stop_loss <= 0:
            issues.append(f"Invalid stop loss: {stop_loss}")
            
        if stop_loss >= entry_price:
            issues.append(f"Stop loss {stop_loss} >= entry {entry_price}")
            
        # 4. Risk validation
        risk_pct = (entry_price - stop_loss) / entry_price
        if risk_pct > 0.10:  # 10% max risk
            issues.append(f"Excessive risk: {risk_pct*100:.1f}%")
            
        return len(issues) == 0, issues
    
    def check_microstructure_signals(self, signals: Dict[str, float]) -> Tuple[bool, List[str]]:
        """Validate microstructure signals"""
        issues = []
        
        # Check OFI ratio bounds
        if 'ofi_ratio' in signals:
            if abs(signals['ofi_ratio']) > 1:
                issues.append(f"OFI ratio out of bounds: {signals['ofi_ratio']}")
                
        # Check VPIN bounds  
        if 'vpin' in signals:
            if not 0 <= signals['vpin'] <= 1:
                issues.append(f"VPIN out of bounds: {signals['vpin']}")
                
        # Check dark ratio
        if 'dark_ratio' in signals:
            if not 0 <= signals['dark_ratio'] <= 1:
                issues.append(f"Dark ratio out of bounds: {signals['dark_ratio']}")
                
        # Check correlations
        if 'kyle_lambda' in signals:
            if not 0 <= signals['kyle_lambda'] <= 1:
                issues.append(f"Kyle's lambda out of bounds: {signals['kyle_lambda']}")
                
        return len(issues) == 0, issues
    
    def check_order_execution(self, order: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate order execution data"""
        issues = []
        
        # Required fields
        required = ['action', 'symbol', 'size', 'price']
        for field in required:
            if field not in order:
                issues.append(f"Missing required field: {field}")
                
        if issues:
            return False, issues
            
        # Price validation
        if order['price'] <= 0:
            issues.append(f"Invalid order price: {order['price']}")
            
        # Size validation  
        if order['size'] <= 0:
            issues.append(f"Invalid order size: {order['size']}")
            
        # Action validation
        valid_actions = ['ENTRY', 'EXIT', 'SCALE_IN', 'SCALE_OUT']
        if order['action'] not in valid_actions:
            issues.append(f"Invalid action: {order['action']}")
            
        # Exit reason validation
        if order['action'] == 'EXIT' and 'reason' not in order:
            issues.append("Exit order missing reason")
            
        return len(issues) == 0, issues
    
    def get_summary(self) -> Dict:
        """Get summary of data integrity checks"""
        return {
            'checks_performed': self.checks_performed,
            'missing_data_count': self.missing_data_count,
            'invalid_data_count': self.invalid_data_count,
            'anomaly_count': self.anomaly_count,
            'total_issues': len(self.issues_found),
            'issue_rate': len(self.issues_found) / self.checks_performed if self.checks_performed > 0 else 0,
            'recent_issues': self.issues_found[-10:] if self.issues_found else [],
            'data_ordering': self.data_ordering
        }
    
    def log_summary(self):
        """Log a summary of integrity checks"""
        summary = self.get_summary()
        
        logger.info("=" * 60)
        logger.info("DATA INTEGRITY SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total checks performed: {summary['checks_performed']:,}")
        logger.info(f"Missing data instances: {summary['missing_data_count']:,}")
        logger.info(f"Invalid data instances: {summary['invalid_data_count']:,}")
        logger.info(f"Anomalies detected: {summary['anomaly_count']:,}")
        logger.info(f"Total issues found: {summary['total_issues']:,}")
        logger.info(f"Issue rate: {summary['issue_rate']*100:.2f}%")
        
        # Log data ordering findings
        if summary['data_ordering']:
            logger.info("\nData Ordering Detection:")
            for symbol, order in summary['data_ordering'].items():
                if order == 'descending':
                    logger.warning(f"  {symbol}: REVERSE chronological order (newest first)")
                elif order == 'ascending':
                    logger.info(f"  {symbol}: Normal chronological order")
                else:
                    logger.warning(f"  {symbol}: Mixed/unknown order")
        
        if summary['recent_issues']:
            logger.info("\nRecent issues:")
            for timestamp, symbol, issue in summary['recent_issues'][-5:]:
                logger.info(f"  {timestamp} - {symbol}: {issue}")


class TradingSystemValidator:
    """Validate trading system behavior and catch logic errors"""
    
    def __init__(self):
        self.position_history = {}
        self.pnl_history = []
        self.order_consistency_errors = 0
        self.risk_violations = 0
        
    def validate_position_consistency(self, symbol: str, position: Any) -> List[str]:
        """Check position internal consistency"""
        issues = []
        
        # Entry/exit size consistency
        total_entries = sum(position.entry_sizes)
        total_exits = sum(position.exit_sizes)
        current_pos = position.current_position
        
        if current_pos != total_entries - total_exits:
            issues.append(f"Position size mismatch: {current_pos} != {total_entries} - {total_exits}")
            self.order_consistency_errors += 1
            
        # Price consistency
        if position.entry_prices and min(position.entry_prices) <= 0:
            issues.append(f"Invalid entry prices: {position.entry_prices}")
            
        if position.exit_prices and min(position.exit_prices) <= 0:
            issues.append(f"Invalid exit prices: {position.exit_prices}")
            
        # P&L consistency
        if position.is_closed:
            calculated_pnl = sum(p * s for p, s in zip(position.exit_prices, position.exit_sizes)) - \
                           sum(p * s for p, s in zip(position.entry_prices, position.entry_sizes))
            
            if abs(calculated_pnl - position.realized_pnl) > 0.01:
                issues.append(f"P&L mismatch: {calculated_pnl:.2f} != {position.realized_pnl:.2f}")
                
        return issues
    
    def validate_risk_management(self, position: Any, current_price: float) -> List[str]:
        """Validate risk management rules"""
        issues = []
        
        # Check stop loss
        if current_price < position.stop_loss_price * 0.95:
            issues.append(f"Price {current_price:.2f} significantly below stop {position.stop_loss_price:.2f}")
            self.risk_violations += 1
            
        # Check position sizing
        if position.current_position > 2000:
            issues.append(f"Excessive position size: {position.current_position}")
            self.risk_violations += 1
            
        return issues
    
    def validate_order_sequence(self, orders: List[Dict]) -> List[str]:
        """Validate order sequence logic"""
        issues = []
        
        # Check for duplicate orders
        recent_orders = {}
        for order in orders[-100:]:
            key = (order['symbol'], order['action'], order.get('timestamp'))
            if key in recent_orders:
                issues.append(f"Duplicate order detected: {order}")
                
            recent_orders[key] = order
            
        # Check for rapid fire orders
        symbol_orders = {}
        for order in orders[-50:]:
            symbol = order['symbol']
            if symbol not in symbol_orders:
                symbol_orders[symbol] = []
            symbol_orders[symbol].append(order)
            
        for symbol, sym_orders in symbol_orders.items():
            if len(sym_orders) > 10:
                issues.append(f"Rapid fire orders for {symbol}: {len(sym_orders)} orders")
                
        return issues