"""
IQFeed Message Parser

Following PROJECT_ROADMAP.md Phase 1.2: Parse every IQFeed message type with 100% accuracy
Following RULES.md: Structured error handling, no silent failures

Parses IQFeed Level 2, trades, and quotes messages with microsecond precision.
NO MOCKS - Only real IQFeed message formats.
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional
import logging
from dataclasses import dataclass

from .exceptions import MessageParsingError, DataIntegrityError

# Configure logging for loud failures
logger = logging.getLogger(__name__)


@dataclass
class ParsingStatistics:
    """Statistics for message parsing performance monitoring."""
    total_messages: int = 0
    successful_parses: int = 0
    failed_parses: int = 0
    l2_messages: int = 0
    trade_messages: int = 0
    quote_messages: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        return self.successful_parses / self.total_messages if self.total_messages > 0 else 0.0


class IQFeedMessageParser:
    """
    Parses IQFeed messages with strict validation and error handling.
    
    Implements microsecond precision timestamp parsing and comprehensive
    data validation as specified in PROJECT_ROADMAP.md Phase 1.2.
    """
    
    def __init__(self):
        """Initialize parser with statistics tracking."""
        self.stats = ParsingStatistics()
        
        # Timestamp patterns for different IQFeed timestamp formats
        self.timestamp_patterns = [
            # Full microsecond precision: YYYYMMDDHHMMSSSSSSSS
            re.compile(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{6})$'),
            # Millisecond precision: YYYYMMDDHHMMSSSS
            re.compile(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{3})$'),
            # Second precision: YYYYMMDDHHMMSS
            re.compile(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$')
        ]
        
        logger.info("IQFeed message parser initialized")
    
    def _validate_financial_data_security(self, price: float, size: int, symbol: str, field_name: str) -> Optional[str]:
        """
        SECURITY: Comprehensive financial data validation to prevent corruption and attacks.
        
        Args:
            price: Price to validate
            size: Size to validate  
            symbol: Symbol for context
            field_name: Field name for error reporting
            
        Returns:
            Error message if invalid, None if valid
        """
        # Price validation
        if price is None:
            return f"{field_name} price cannot be None for {symbol}"
            
        if not isinstance(price, (int, float)):
            return f"{field_name} price must be numeric for {symbol}, got {type(price).__name__}"
            
        # SECURITY: Prevent negative prices - critical financial data corruption
        if price < 0:
            return f"{field_name} price cannot be negative for {symbol}: {price}"
            
        # SECURITY: Prevent zero prices in most contexts (except for delete operations)
        if price == 0 and field_name not in ['delete', 'zero_size']:
            return f"{field_name} price cannot be zero for {symbol}: {price}"
            
        # SECURITY: Prevent unreasonably high prices (potential overflow/corruption)
        if price > 1000000.0:  # $1M per share is unreasonable
            return f"{field_name} price unreasonably high for {symbol}: {price} (max $1M)"
            
        # SECURITY: Prevent microscopic prices that could indicate corruption
        if 0 < price < 0.0001:  # Less than 1/100th of a cent
            return f"{field_name} price too small for {symbol}: {price} (min $0.0001)"
            
        # Size validation  
        if size is None:
            return f"{field_name} size cannot be None for {symbol}"
            
        if not isinstance(size, int):
            return f"{field_name} size must be integer for {symbol}, got {type(size).__name__}"
            
        # SECURITY: Prevent negative sizes (except for special delete operations)
        if size < 0 and field_name not in ['delete', 'adjustment']:
            return f"{field_name} size cannot be negative for {symbol}: {size}"
            
        # SECURITY: Prevent unreasonably large sizes (potential overflow)
        if size > 100000000:  # 100M shares is unreasonable for single order
            return f"{field_name} size unreasonably large for {symbol}: {size} (max 100M)"
            
        return None  # Valid data
    
    def _validate_symbol_field_security(self, symbol: str, context: str = "message") -> Optional[str]:
        """
        SECURITY: Validate symbol field in parsed messages.
        
        Args:
            symbol: Symbol to validate
            context: Context for error reporting
            
        Returns:
            Error message if invalid, None if valid
        """
        if not symbol:
            return f"Empty symbol in {context}"
            
        if not isinstance(symbol, str):
            return f"Symbol must be string in {context}, got {type(symbol).__name__}"
            
        # Remove dangerous whitespace
        sanitized = symbol.strip()
        if not sanitized:
            return f"Symbol is whitespace-only in {context}"
            
        # Length check
        if len(sanitized) > 10:
            return f"Symbol too long in {context}: {len(sanitized)} chars (max 10)"
            
        # Character validation
        import re
        if not re.match(r'^[A-Z0-9._-]+$', sanitized.upper()):
            return f"Symbol contains invalid characters in {context}: '{sanitized}'"
            
        return None  # Valid symbol
    
    def parse_l2_message(self, message: str) -> Dict[str, Any]:
        """
        Parse IQFeed Level 2 order book message.
        
        Handles multiple L2 message formats:
        - L2: Level 2 order book snapshot/update
        - U: Order book update (insert/update)
        - M: Market maker update
        - D: Order book delete
        - L: Legacy Level 2 format
        
        Args:
            message: Raw L2 message string
            
        Returns:
            Dictionary with parsed L2 data
            
        Raises:
            MessageParsingError: If parsing fails with detailed context
        """
        self.stats.total_messages += 1
        
        try:
            parts = message.strip().split(',')
            message_type = parts[0]
            
            # Handle different L2 message types
            if message_type == 'U':
                return self._parse_l2_update_message(parts, message)
            elif message_type == 'M':
                return self._parse_l2_market_maker_message(parts, message)
            elif message_type == 'D':
                return self._parse_l2_delete_message(parts, message)
            elif message_type in ['L2', 'L']:
                return self._parse_l2_standard_message(parts, message)
            else:
                raise MessageParsingError(
                    f"Unknown L2 message type: {message_type}",
                    message, "L2"
                )
                
        except MessageParsingError:
            self.stats.failed_parses += 1
            raise
        except Exception as e:
            self.stats.failed_parses += 1
            raise MessageParsingError(
                f"Unexpected error parsing L2 message: {e}",
                message, "L2"
            )
    
    def _parse_l2_standard_message(self, parts: list, original_message: str) -> Dict[str, Any]:
        """Parse standard L2 message format."""
        if len(parts) < 10:
            raise MessageParsingError(
                f"Insufficient L2 message fields: expected 10, got {len(parts)}",
                original_message, "L2"
            )
        
        # Validate message type
        if parts[0] not in ['L2', 'L']:
            raise MessageParsingError(
                f"Invalid L2 message type: {parts[0]}",
                original_message, "L2"
            )
            
        # Parse and validate each field with SECURITY checks
        symbol = parts[1].strip()
        symbol_error = self._validate_symbol_field_security(symbol, "L2 message")
        if symbol_error:
            raise MessageParsingError(
                f"Symbol validation failed: {symbol_error}",
                original_message, "L2"
            )
            
        try:
            level = int(parts[2])
            if level < 0 or level > 20:  # Reasonable level range
                raise ValueError(f"Level out of range: {level}")
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid level: {parts[2]} ({e})",
                original_message, "L2"
            )
            
        market_maker = parts[3].strip()
        if not market_maker:
            raise MessageParsingError(
                f"Empty market maker field",
                original_message, "L2"
            )
        
        try:
            operation = int(parts[4])
            if operation not in [0, 1, 2]:  # Add, Update, Delete
                raise ValueError(f"Invalid operation code: {operation}")
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid operation: {parts[4]} ({e})",
                original_message, "L2"
            )
        
        try:
            side = int(parts[5])
            if side not in [0, 1]:  # Ask, Bid
                raise ValueError(f"Invalid side code: {side}")
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid side: {parts[5]} ({e})",
                original_message, "L2"
            )
        
        try:
            price = float(parts[6])
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid price format: {parts[6]} ({e})",
                original_message, "L2"
            )
            
        try:
            size = int(parts[7])
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid size format: {parts[7]} ({e})",
                original_message, "L2"
            )
            
        # SECURITY: Comprehensive financial data validation
        price_size_error = self._validate_financial_data_security(price, size, symbol, "L2")
        if price_size_error:
            raise MessageParsingError(
                f"Financial data validation failed: {price_size_error}",
                original_message, "L2"
            )
        
        try:
            tick_id = int(parts[8])
            if tick_id < 0:
                raise ValueError(f"Negative tick ID: {tick_id}")
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid tick_id: {parts[8]} ({e})",
                original_message, "L2"
            )
        
        # Parse timestamp with microsecond precision
        timestamp = self._parse_timestamp(parts[9], original_message, "L2")
        
        # Create parsed result
        parsed = {
            'timestamp': timestamp,
            'symbol': symbol,
            'level': level,
            'market_maker': market_maker,
            'operation': operation,
            'side': side,
            'price': price,
            'size': size,
            'tick_id': tick_id
        }
        
        self.stats.successful_parses += 1
        self.stats.l2_messages += 1
        
        return parsed
    
    def parse_trade_message(self, message: str) -> Dict[str, Any]:
        """
        Parse IQFeed trade execution message with enhanced tick data support.
        
        Supports multiple trade formats:
        - Standard: T,symbol,timestamp,price,size,total_volume,market_center,conditions,tick_id,bid,ask
        - High-frequency: T,symbol,timestamp,price,size,conditions,market_center
        - Extended: T,symbol,timestamp,price,size,total_volume,market_center,conditions,tick_id,bid,ask,basis
        
        Args:
            message: Raw trade message string
            
        Returns:
            Dictionary with parsed trade data
            
        Raises:
            MessageParsingError: If parsing fails
        """
        self.stats.total_messages += 1
        
        try:
            parts = message.strip().split(',')
            
            # Variable length message support for different tick formats
            if len(parts) < 6:
                raise MessageParsingError(
                    f"Insufficient trade message fields: expected at least 6, got {len(parts)}",
                    message, "trades"
                )
            
            # Validate message type
            if parts[0] != 'T':
                raise MessageParsingError(
                    f"Invalid trade message type: {parts[0]}",
                    message, "trades"
                )
            
            # Parse and validate fields with SECURITY checks
            symbol = parts[1].strip()
            symbol_error = self._validate_symbol_field_security(symbol, "trade message")
            if symbol_error:
                raise MessageParsingError(f"Symbol validation failed: {symbol_error}", message, "trades")
            
            timestamp = self._parse_timestamp(parts[2], message, "trades")
            
            try:
                trade_price = float(parts[3])
            except ValueError as e:
                raise MessageParsingError(
                    f"Invalid trade price format: {parts[3]} ({e})",
                    message, "trades"
                )
            
            try:
                trade_size = int(parts[4])
            except ValueError as e:
                raise MessageParsingError(
                    f"Invalid trade size format: {parts[4]} ({e})",
                    message, "trades"
                )
                
            # SECURITY: Comprehensive financial data validation
            price_size_error = self._validate_financial_data_security(trade_price, trade_size, symbol, "trade")
            if price_size_error:
                raise MessageParsingError(
                    f"Trade data validation failed: {price_size_error}",
                    message, "trades"
                )
            
            # Parse remaining fields based on message length (handles different formats)
            total_volume = 0
            trade_market_center = ""
            trade_conditions = ""
            tick_id = 0
            bid_price = 0.0
            ask_price = 0.0
            basis = ""
            
            if len(parts) >= 7:  # Has total_volume or conditions field
                if len(parts) == 7:
                    # High-frequency format: T,symbol,timestamp,price,size,conditions,market_center
                    trade_conditions = parts[5].strip()
                    trade_market_center = parts[6].strip()
                else:
                    # Standard format with total_volume
                    try:
                        total_volume = int(parts[5])
                        if total_volume < 0:
                            raise ValueError(f"Negative total volume: {total_volume}")
                    except ValueError as e:
                        raise MessageParsingError(
                            f"Invalid total volume: {parts[5]} ({e})",
                            message, "trades"
                        )
            
            if len(parts) >= 8:
                trade_market_center = parts[6].strip()
                trade_conditions = parts[7].strip()
            
            if len(parts) >= 9:
                try:
                    tick_id = int(parts[8])
                    if tick_id < 0:
                        raise ValueError(f"Negative tick ID: {tick_id}")
                except ValueError as e:
                    raise MessageParsingError(
                        f"Invalid tick_id: {parts[8]} ({e})",
                        message, "trades"
                    )
            
            if len(parts) >= 11:  # Has bid/ask prices
                try:
                    bid_price = float(parts[9])
                    ask_price = float(parts[10])
                    
                    # SECURITY: Validate bid/ask prices when present
                    if bid_price > 0:
                        bid_error = self._validate_financial_data_security(bid_price, 1, symbol, "bid")
                        if bid_error:
                            raise MessageParsingError(
                                f"Bid price validation failed: {bid_error}",
                                message, "trades"
                            )
                            
                    if ask_price > 0:
                        ask_error = self._validate_financial_data_security(ask_price, 1, symbol, "ask")
                        if ask_error:
                            raise MessageParsingError(
                                f"Ask price validation failed: {ask_error}",
                                message, "trades"
                            )
                    
                    # Check for crossed quotes (bid >= ask) when both are present
                    if bid_price > 0 and ask_price > 0 and bid_price >= ask_price:
                        logger.warning(f"Crossed quotes detected: bid={bid_price}, ask={ask_price} for {symbol}")
                        # Log but don't fail - crossed quotes can occur temporarily in real markets
                        
                except ValueError as e:
                    raise MessageParsingError(
                        f"Invalid bid/ask price format: {parts[9]}/{parts[10]} ({e})",
                        message, "trades"
                    )
            
            if len(parts) >= 12:  # Extended format with basis
                basis = parts[11].strip()
            
            # Calculate derived fields for high-frequency tick analysis
            is_uptick = None
            is_downtick = None
            at_bid = None
            at_ask = None
            
            if bid_price > 0 and ask_price > 0:
                mid_price = (bid_price + ask_price) / 2
                at_bid = abs(trade_price - bid_price) < abs(trade_price - ask_price)
                at_ask = abs(trade_price - ask_price) < abs(trade_price - bid_price)
                
                # Determine tick direction relative to mid-price
                if trade_price > mid_price:
                    is_uptick = True
                    is_downtick = False
                elif trade_price < mid_price:
                    is_uptick = False
                    is_downtick = True
            
            parsed = {
                'timestamp': timestamp,
                'symbol': symbol,
                'trade_price': trade_price,
                'trade_size': trade_size,
                'total_volume': total_volume,
                'trade_market_center': trade_market_center,
                'trade_conditions': trade_conditions,
                'tick_id': tick_id,
                'bid_price': bid_price,
                'ask_price': ask_price,
                'basis': basis,
                
                # High-frequency tick analysis fields
                'at_bid': at_bid,
                'at_ask': at_ask,
                'is_uptick': is_uptick,
                'is_downtick': is_downtick,
                'is_high_frequency': len(parts) <= 7,  # High-frequency format indicator
                'message_length': len(parts)  # For debugging format variations
            }
            
            self.stats.successful_parses += 1
            self.stats.trade_messages += 1
            
            return parsed
            
        except MessageParsingError:
            self.stats.failed_parses += 1
            raise
        except Exception as e:
            self.stats.failed_parses += 1
            raise MessageParsingError(
                f"Unexpected error parsing trade message: {e}",
                message, "trades"
            )
    
    def parse_quote_message(self, message: str) -> Dict[str, Any]:
        """
        Parse IQFeed NBBO quote message.
        
        Format: Q,symbol,timestamp,bid_price,bid_size,ask_price,ask_size,bid_market_center,ask_market_center,tick_id
        
        Args:
            message: Raw quote message string
            
        Returns:
            Dictionary with parsed quote data
            
        Raises:
            MessageParsingError: If parsing fails
        """
        self.stats.total_messages += 1
        
        try:
            parts = message.strip().split(',')
            
            if len(parts) < 9:
                raise MessageParsingError(
                    f"Insufficient quote message fields: expected 9, got {len(parts)}",
                    message, "quotes"
                )
            
            # Validate message type
            if parts[0] != 'Q':
                raise MessageParsingError(
                    f"Invalid quote message type: {parts[0]}",
                    message, "quotes"
                )
            
            symbol = parts[1].strip()
            symbol_error = self._validate_symbol_field_security(symbol, "quote message")
            if symbol_error:
                raise MessageParsingError(f"Symbol validation failed: {symbol_error}", message, "quotes")
                
            timestamp = self._parse_timestamp(parts[2], message, "quotes")
            
            try:
                bid_price = float(parts[3])
                bid_size = int(parts[4])
                ask_price = float(parts[5])
                ask_size = int(parts[6])
            except ValueError as e:
                raise MessageParsingError(
                    f"Invalid quote data format: {e}",
                    message, "quotes"
                )
                
            # SECURITY: Comprehensive validation of bid data
            bid_error = self._validate_financial_data_security(bid_price, bid_size, symbol, "bid")
            if bid_error:
                raise MessageParsingError(
                    f"Bid validation failed: {bid_error}",
                    message, "quotes"
                )
                
            # SECURITY: Comprehensive validation of ask data
            ask_error = self._validate_financial_data_security(ask_price, ask_size, symbol, "ask")
            if ask_error:
                raise MessageParsingError(
                    f"Ask validation failed: {ask_error}",
                    message, "quotes"
                )
                
            # SECURITY: Check for crossed quotes (critical market data corruption)
            if bid_price >= ask_price:
                raise MessageParsingError(
                    f"Crossed quotes detected: bid={bid_price} >= ask={ask_price} for {symbol} - indicates data corruption",
                    message, "quotes"
                )
                
            # SECURITY: Check for unrealistic spreads (potential data corruption)
            spread = ask_price - bid_price
            if spread > ask_price * 0.1:  # Spread > 10% of ask price
                raise MessageParsingError(
                    f"Unrealistic spread detected: {spread:.4f} ({spread/ask_price*100:.1f}% of ask) for {symbol} - indicates data corruption",
                    message, "quotes"
                )
            
            bid_market_center = parts[7].strip()
            ask_market_center = parts[8].strip()
            
            try:
                tick_id = int(parts[9]) if len(parts) > 9 else 0
            except ValueError as e:
                raise MessageParsingError(
                    f"Invalid tick_id: {parts[9]} ({e})",
                    message, "quotes"
                )
            
            parsed = {
                'timestamp': timestamp,
                'symbol': symbol,
                'bid_price': bid_price,
                'bid_size': bid_size,
                'ask_price': ask_price,
                'ask_size': ask_size,
                'bid_market_center': bid_market_center,
                'ask_market_center': ask_market_center,
                'tick_id': tick_id
            }
            
            self.stats.successful_parses += 1
            self.stats.quote_messages += 1
            
            return parsed
            
        except MessageParsingError:
            self.stats.failed_parses += 1
            raise
        except Exception as e:
            self.stats.failed_parses += 1
            raise MessageParsingError(
                f"Unexpected error parsing quote message: {e}",
                message, "quotes"
            )
    
    def _parse_timestamp(self, timestamp_str: str, original_message: str, message_type: str) -> datetime:
        """
        Parse IQFeed timestamp with microsecond precision.
        
        Handles multiple timestamp formats:
        - YYYYMMDDHHMMSSSSSSSS (microseconds)
        - YYYYMMDDHHMMSSSS (milliseconds)
        - YYYYMMDDHHMMSS (seconds)
        
        Args:
            timestamp_str: Raw timestamp string
            original_message: Original message for error context
            message_type: Type of message for error context
            
        Returns:
            Parsed datetime with microsecond precision
            
        Raises:
            MessageParsingError: If timestamp parsing fails
        """
        try:
            # Try each timestamp pattern
            for pattern in self.timestamp_patterns:
                match = pattern.match(timestamp_str.strip())
                if match:
                    groups = match.groups()
                    
                    year = int(groups[0])
                    month = int(groups[1])
                    day = int(groups[2])
                    hour = int(groups[3])
                    minute = int(groups[4])
                    second = int(groups[5])
                    
                    # Handle fractional seconds
                    if len(groups) > 6:
                        frac_str = groups[6]
                        if len(frac_str) == 6:  # Microseconds
                            microsecond = int(frac_str)
                        elif len(frac_str) == 3:  # Milliseconds
                            microsecond = int(frac_str) * 1000
                        else:
                            microsecond = 0
                    else:
                        microsecond = 0
                    
                    # Validate date components
                    if not (1 <= month <= 12):
                        raise ValueError(f"Invalid month: {month}")
                    if not (1 <= day <= 31):
                        raise ValueError(f"Invalid day: {day}")
                    if not (0 <= hour <= 23):
                        raise ValueError(f"Invalid hour: {hour}")
                    if not (0 <= minute <= 59):
                        raise ValueError(f"Invalid minute: {minute}")
                    if not (0 <= second <= 59):
                        raise ValueError(f"Invalid second: {second}")
                    if not (0 <= microsecond <= 999999):
                        raise ValueError(f"Invalid microsecond: {microsecond}")
                    
                    return datetime(year, month, day, hour, minute, second, microsecond)
            
            # No pattern matched
            raise ValueError(f"Unrecognized timestamp format: {timestamp_str}")
            
        except ValueError as e:
            raise MessageParsingError(
                f"Invalid timestamp '{timestamp_str}': {e}",
                original_message, message_type
            )
    
    def get_parsing_statistics(self) -> Dict[str, Any]:
        """
        Get current parsing statistics for monitoring.
        
        Returns:
            Dictionary with parsing statistics
        """
        return {
            'total_messages': self.stats.total_messages,
            'successful_parses': self.stats.successful_parses,
            'failed_parses': self.stats.failed_parses,
            'success_rate': self.stats.success_rate,
            'l2_messages': self.stats.l2_messages,
            'trade_messages': self.stats.trade_messages,
            'quote_messages': self.stats.quote_messages
        }
    
    def reset_statistics(self):
        """Reset parsing statistics."""
        self.stats = ParsingStatistics()
        logger.info("Parser statistics reset")
    
    def _parse_l2_update_message(self, parts: list, original_message: str) -> Dict[str, Any]:
        """
        Parse L2 update message (U,symbol,timestamp,side,level,market_maker,price,size,operation).
        
        Args:
            parts: Split message parts
            original_message: Original message for error context
            
        Returns:
            Parsed L2 update data
        """
        if len(parts) < 9:
            raise MessageParsingError(
                f"Insufficient L2 update fields: expected 9, got {len(parts)}",
                original_message, "L2_UPDATE"
            )
        
        symbol = parts[1].strip()
        symbol_error = self._validate_symbol_field_security(symbol, "L2 update message")
        if symbol_error:
            raise MessageParsingError(
                f"Symbol validation failed: {symbol_error}",
                original_message, "L2_UPDATE"
            )
            
        timestamp = self._parse_timestamp(parts[2], original_message, "L2_UPDATE")
        
        try:
            side = int(parts[3])  # 0=Ask, 1=Bid
            level = int(parts[4])
            market_maker = parts[5].strip()
            price = float(parts[6])
            size = int(parts[7])
            operation = int(parts[8])  # 1=Add, 2=Update, 3=Delete
            
        except (ValueError, IndexError) as e:
            raise MessageParsingError(
                f"Invalid L2 update data format: {e}",
                original_message, "L2_UPDATE"
            )
            
        # SECURITY: Comprehensive financial data validation
        price_size_error = self._validate_financial_data_security(price, size, symbol, "L2 update")
        if price_size_error:
            raise MessageParsingError(
                f"L2 update validation failed: {price_size_error}",
                original_message, "L2_UPDATE"
            )
        
        return {
            'timestamp': timestamp,
            'symbol': symbol,
            'side': side,
            'level': level,
            'market_maker': market_maker,
            'price': price,
            'size': size,
            'operation': operation,
            'l2_operation': 'update'
        }
    
    def _parse_l2_market_maker_message(self, parts: list, original_message: str) -> Dict[str, Any]:
        """
        Parse L2 market maker message (M,symbol,timestamp,market_maker,bid_price,bid_size,ask_price,ask_size).
        
        Args:
            parts: Split message parts
            original_message: Original message for error context
            
        Returns:
            Parsed L2 market maker data
        """
        if len(parts) < 8:
            raise MessageParsingError(
                f"Insufficient L2 market maker fields: expected 8, got {len(parts)}",
                original_message, "L2_MM"
            )
        
        symbol = parts[1].strip()
        symbol_error = self._validate_symbol_field_security(symbol, "L2 market maker message")
        if symbol_error:
            raise MessageParsingError(
                f"Symbol validation failed: {symbol_error}",
                original_message, "L2_MM"
            )
            
        timestamp = self._parse_timestamp(parts[2], original_message, "L2_MM")
        
        try:
            market_maker = parts[3].strip()
            bid_price = float(parts[4])
            bid_size = int(parts[5])
            ask_price = float(parts[6])
            ask_size = int(parts[7])
            
        except (ValueError, IndexError) as e:
            raise MessageParsingError(
                f"Invalid L2 market maker data format: {e}",
                original_message, "L2_MM"
            )
            
        # SECURITY: Comprehensive financial data validation for bid/ask
        if bid_price > 0:  # Only validate non-zero prices
            bid_error = self._validate_financial_data_security(bid_price, bid_size, symbol, "L2 MM bid")
            if bid_error:
                raise MessageParsingError(
                    f"L2 MM bid validation failed: {bid_error}",
                    original_message, "L2_MM"
                )
                
        if ask_price > 0:  # Only validate non-zero prices
            ask_error = self._validate_financial_data_security(ask_price, ask_size, symbol, "L2 MM ask")
            if ask_error:
                raise MessageParsingError(
                    f"L2 MM ask validation failed: {ask_error}",
                    original_message, "L2_MM"
                )
        
        return {
            'timestamp': timestamp,
            'symbol': symbol,
            'market_maker': market_maker,
            'bid_price': bid_price,
            'bid_size': bid_size,
            'ask_price': ask_price,
            'ask_size': ask_size,
            'l2_operation': 'market_maker_update'
        }
    
    def _parse_l2_delete_message(self, parts: list, original_message: str) -> Dict[str, Any]:
        """
        Parse L2 delete message (D,symbol,timestamp,side,level).
        
        Args:
            parts: Split message parts
            original_message: Original message for error context
            
        Returns:
            Parsed L2 delete data
        """
        if len(parts) < 5:
            raise MessageParsingError(
                f"Insufficient L2 delete fields: expected 5, got {len(parts)}",
                original_message, "L2_DELETE"
            )
        
        symbol = parts[1].strip()
        symbol_error = self._validate_symbol_field_security(symbol, "L2 delete message")
        if symbol_error:
            raise MessageParsingError(
                f"Symbol validation failed: {symbol_error}",
                original_message, "L2_DELETE"
            )
            
        timestamp = self._parse_timestamp(parts[2], original_message, "L2_DELETE")
        
        try:
            side = int(parts[3])  # 0=Ask, 1=Bid
            level = int(parts[4])
            
        except (ValueError, IndexError) as e:
            raise MessageParsingError(
                f"Invalid L2 delete data: {e}",
                original_message, "L2_DELETE"
            )
        
        return {
            'timestamp': timestamp,
            'symbol': symbol,
            'side': side,
            'level': level,
            'l2_operation': 'delete'
        }