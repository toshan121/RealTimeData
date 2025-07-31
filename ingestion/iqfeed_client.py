"""
IQFeed Real-Time Client

Following PROJECT_ROADMAP.md Phase 2.1: Robust connection management with automatic recovery
Following RULES.md: Structured error handling, loud failures, real data only

Manages real-time connections to IQFeed with subscription management and error recovery.
NO MOCKS - Only real IQFeed connections and data.
"""

import socket
import threading
import time
import queue
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum
import os
from dotenv import load_dotenv

from .exceptions import (
    IQFeedConnectionError,
    IQFeedAuthenticationError,
    RateLimitError,
    ProcessingError
)
from .iqfeed_parser import IQFeedMessageParser

# Load environment variables
load_dotenv()

# Configure logging for loud failures
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Connection state enumeration."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ConnectionResult:
    """Result of connection operation."""
    success: bool
    session_id: Optional[str] = None
    error_message: Optional[str] = None
    connection_time: Optional[datetime] = None


@dataclass
class SubscriptionResult:
    """Result of subscription operation."""
    success: bool
    symbol: str
    subscription_type: str  # 'l2', 'trades', 'quotes'
    error_message: Optional[str] = None


@dataclass
class ClientStatus:
    """Current client status."""
    connected: bool
    state: ConnectionState
    uptime_seconds: float
    error: Optional[str] = None
    feed_version: Optional[str] = None
    active_subscriptions: int = 0


@dataclass
class BandwidthStatistics:
    """Bandwidth and throughput statistics."""
    bytes_received_per_second: float
    messages_received_per_second: float
    total_bytes_received: int
    total_messages_received: int
    average_message_size: float
    last_update: datetime


class IQFeedClient:
    """
    Real-time IQFeed client with robust connection management.
    
    Implements automatic reconnection, subscription management, and bandwidth monitoring
    as specified in PROJECT_ROADMAP.md Phase 2.1.
    """
    
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        """
        Initialize IQFeed client.
        
        Args:
            host: IQFeed host (default from .env)
            port: IQFeed port (default from .env)
        """
        self.host = host or os.getenv('IQFEED_HOST', 'localhost')
        self.port = int(port or os.getenv('IQFEED_PORT', '9200'))
        
        # Connection state
        self._socket: Optional[socket.socket] = None
        self._state = ConnectionState.DISCONNECTED
        self._session_id: Optional[str] = None
        self._connect_time: Optional[datetime] = None
        self._last_heartbeat: Optional[datetime] = None
        
        # Message processing
        self._parser = IQFeedMessageParser()
        self._message_queue: queue.Queue = queue.Queue(maxsize=10000)
        
        # High-frequency tick data buffer (larger capacity for high-volume streams)
        self._tick_buffer: queue.Queue = queue.Queue(maxsize=50000)
        self._tick_buffer_overflow_count = 0
        
        self._running = False
        self._receive_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Subscriptions
        self._l2_subscriptions: Set[str] = set()
        self._trade_subscriptions: Set[str] = set()
        self._quote_subscriptions: Set[str] = set()
        self._tick_subscriptions: Set[str] = set()  # High-frequency tick data subscriptions
        self._subscription_lock = threading.Lock()
        
        # Statistics
        self._stats_lock = threading.Lock()
        self._bytes_received = 0
        self._messages_received = 0
        self._stats_start_time = datetime.now()
        self._last_stats_update = datetime.now()
        
        # Rate limiting
        self._last_subscription_time = 0
        self._subscription_count = 0
        self._rate_limit_window = 60  # 1 minute window
        self._max_subscriptions_per_minute = 100
        
        # Sequence tracking
        self._sequence_gaps: List[Dict[str, Any]] = []
        self._last_tick_ids: Dict[str, int] = {}  # symbol -> last_tick_id
        
        # Signal handling for daemon operation
        self._shutdown_requested = False
        self._status_dump_requested = False
        self._config_reload_requested = False
        self._setup_signal_handlers()
        
        logger.info(f"IQFeed client initialized for {self.host}:{self.port} with signal handling")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for daemon operation control."""
        try:
            # Only setup signal handlers if running as main process
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGTERM, self._handle_sigterm)
                signal.signal(signal.SIGINT, self._handle_sigint)
                signal.signal(signal.SIGUSR1, self._handle_sigusr1)
                signal.signal(signal.SIGHUP, self._handle_sighup)
                signal.signal(signal.SIGPIPE, signal.SIG_IGN)  # Ignore broken pipe
                
                logger.debug("Signal handlers installed for IQFeed client")
        except Exception as e:
            logger.warning(f"Could not install signal handlers: {e}")
    
    def _handle_sigterm(self, signum: int, frame):
        """Handle SIGTERM for graceful shutdown."""
        logger.info("IQFeed client received SIGTERM - initiating graceful shutdown")
        self._shutdown_requested = True
        self.shutdown(graceful=True)
    
    def _handle_sigint(self, signum: int, frame):
        """Handle SIGINT (Ctrl+C) for graceful shutdown."""
        logger.info("IQFeed client received SIGINT - initiating graceful shutdown")
        self._shutdown_requested = True
        self.shutdown(graceful=True)
    
    def _handle_sigusr1(self, signum: int, frame):
        """Handle SIGUSR1 for status dump."""
        logger.info("IQFeed client received SIGUSR1 - generating status dump")
        self._status_dump_requested = True
        self._dump_client_status()
    
    def _handle_sighup(self, signum: int, frame):
        """Handle SIGHUP for configuration reload."""
        logger.info("IQFeed client received SIGHUP - reloading configuration")
        self._config_reload_requested = True
        self._reload_configuration()
    
    def _dump_client_status(self):
        """Dump comprehensive client status for operational monitoring."""
        try:
            status = self.get_status()
            connection_info = self.get_connection_info()
            bandwidth_stats = self.get_bandwidth_statistics()
            subscriptions = self.get_active_subscriptions()
            tick_stats = self.get_tick_buffer_stats()
            
            print(f"\n=== IQFEED CLIENT STATUS (SIGUSR1) ===")
            print(f"Timestamp: {datetime.now().isoformat()}")
            print(f"Connected: {status.connected}")
            print(f"State: {status.state.value}")
            print(f"Uptime: {status.uptime_seconds / 3600:.1f} hours")
            print(f"Active Subscriptions: {status.active_subscriptions}")
            print(f"  - L2: {len(subscriptions.get('l2_symbols', []))}")
            print(f"  - Trades: {len(subscriptions.get('trade_symbols', []))}")
            print(f"  - Quotes: {len(subscriptions.get('quote_symbols', []))}")
            print(f"  - Ticks: {len(subscriptions.get('tick_symbols', []))}")
            print(f"Bandwidth: {bandwidth_stats['bytes_received_per_second']:.1f} bytes/sec")
            print(f"Message Rate: {bandwidth_stats['messages_received_per_second']:.1f} msg/sec")
            print(f"Tick Buffer: {tick_stats['buffer_size']}/{tick_stats['buffer_capacity']} ({tick_stats['buffer_utilization']*100:.1f}%)")
            print(f"Overflow Count: {tick_stats['overflow_count']}")
            print(f"Session ID: {connection_info.get('session_id', 'N/A')}")
            print(f"==================================\n")
            
            # Log detailed status to file
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'client_status': status.__dict__,
                'connection_info': connection_info,
                'bandwidth_statistics': bandwidth_stats,
                'subscriptions': subscriptions,
                'tick_buffer_stats': tick_stats
            }
            
            logger.info(f"Status dump completed - detailed data: {status_data}")
            
        except Exception as e:
            logger.error(f"Error generating client status dump: {e}")
    
    def _reload_configuration(self):
        """Reload client configuration from environment variables."""
        try:
            # Reload environment variables
            from dotenv import load_dotenv
            load_dotenv(override=True)
            
            # Update connection parameters
            new_host = os.getenv('IQFEED_HOST', 'localhost')
            new_port = int(os.getenv('IQFEED_PORT', '9200'))
            
            config_changed = (new_host != self.host or new_port != self.port)
            
            if config_changed:
                logger.info(f"Configuration changed: {self.host}:{self.port} -> {new_host}:{new_port}")
                
                # Save current subscriptions
                saved_subscriptions = self.get_active_subscriptions()
                
                # Disconnect and update config
                self.disconnect()
                self.host = new_host
                self.port = new_port
                
                # Reconnect if we were connected
                if self._state != ConnectionState.DISCONNECTED:
                    result = self.connect()
                    if result.success and saved_subscriptions:
                        # Restore subscriptions
                        self._restore_subscriptions_after_reload(saved_subscriptions)
                
                logger.info("Configuration reload completed with reconnection")
            else:
                logger.info("Configuration reload completed - no changes detected")
            
            print(f"\n=== CONFIGURATION RELOAD (SIGHUP) ===")
            print(f"Timestamp: {datetime.now().isoformat()}")
            print(f"Host: {self.host}")
            print(f"Port: {self.port}")
            print(f"Changes Applied: {config_changed}")
            print(f"===================================\n")
            
        except Exception as e:
            logger.error(f"Error during configuration reload: {e}")
    
    def _restore_subscriptions_after_reload(self, saved_subscriptions: Dict[str, List[str]]):
        """Restore subscriptions after configuration reload."""
        try:
            restoration_count = 0
            total_subscriptions = sum(len(symbols) for symbols in saved_subscriptions.values())
            
            # Restore L2 subscriptions
            for symbol in saved_subscriptions.get('l2_symbols', []):
                if self.subscribe_l2_data(symbol).success:
                    restoration_count += 1
            
            # Restore trade subscriptions
            for symbol in saved_subscriptions.get('trade_symbols', []):
                if self.subscribe_trades(symbol).success:
                    restoration_count += 1
            
            # Restore tick subscriptions
            for symbol in saved_subscriptions.get('tick_symbols', []):
                if self.subscribe_tick_data(symbol).success:
                    restoration_count += 1
            
            # Restore quote subscriptions
            for symbol in saved_subscriptions.get('quote_symbols', []):
                if self.subscribe_quotes(symbol).success:
                    restoration_count += 1
            
            logger.info(f"Subscription restoration: {restoration_count}/{total_subscriptions} restored")
            
        except Exception as e:
            logger.error(f"Error restoring subscriptions after reload: {e}")
    
    def _validate_symbol_security(self, symbol: str) -> Optional[str]:
        """
        SECURITY: Comprehensive symbol validation to prevent injection attacks.
        
        Args:
            symbol: Symbol to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        if symbol is None:
            return "Symbol cannot be None"
            
        if not isinstance(symbol, str):
            return f"Symbol must be string, got {type(symbol).__name__}"
            
        # Remove dangerous whitespace and check for empty
        sanitized = symbol.strip()
        if not sanitized:
            return "Symbol cannot be empty or whitespace-only"
            
        # Length validation - prevent buffer overflow attempts
        if len(sanitized) > 10:
            return f"Symbol too long: {len(sanitized)} chars (max 10)"
            
        # Character validation - only allow alphanumeric and safe characters
        import re
        if not re.match(r'^[A-Z0-9._-]+$', sanitized.upper()):
            return f"Symbol contains invalid characters: '{sanitized}'. Only A-Z, 0-9, '.', '_', '-' allowed"
            
        # Prevent control characters and injection attempts
        for char in sanitized:
            if ord(char) < 32 or ord(char) > 126:
                return f"Symbol contains control character: ord({ord(char)})"
                
        # Prevent common injection patterns
        dangerous_patterns = ['..', '//', '\\', '<', '>', '"', "'", ';', '|', '&', '`']
        for pattern in dangerous_patterns:
            if pattern in sanitized:
                return f"Symbol contains dangerous pattern: '{pattern}'"
                
        return None  # Valid symbol
    
    def connect(self) -> ConnectionResult:
        """
        Connect to IQFeed with automatic retry logic.
        
        Returns:
            ConnectionResult with success status and details
            
        Raises:
            IQFeedConnectionError: If connection fails after retries
        """
        logger.info(f"Connecting to IQFeed at {self.host}:{self.port}")
        
        if self._state != ConnectionState.DISCONNECTED:
            logger.warning(f"Already connected or connecting (state: {self._state})")
            return ConnectionResult(success=True, session_id=self._session_id)
        
        self._state = ConnectionState.CONNECTING
        
        try:
            # Create socket connection
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(30.0)
            self._socket.connect((self.host, self.port))
            
            # Wait for server greeting
            greeting = self._socket.recv(1024).decode('utf-8').strip()
            logger.info(f"IQFeed greeting: {greeting}")
            
            if "SERVER CONNECTED" not in greeting:
                raise IQFeedConnectionError(
                    f"Unexpected server greeting: {greeting}",
                    self.host, self.port
                )
            
            # Connection successful
            self._state = ConnectionState.CONNECTED
            self._session_id = f"SESSION_{int(time.time())}"
            self._connect_time = datetime.now()
            self._last_heartbeat = datetime.now()
            
            # Start background threads
            self._running = True
            self._start_background_threads()
            
            logger.info(f"Successfully connected to IQFeed (session: {self._session_id})")
            
            return ConnectionResult(
                success=True,
                session_id=self._session_id,
                connection_time=self._connect_time
            )
            
        except socket.timeout as e:
            self._state = ConnectionState.FAILED
            error_msg = f"Connection timeout to {self.host}:{self.port}"
            logger.error(error_msg)
            raise IQFeedConnectionError(error_msg, self.host, self.port, e)
            
        except socket.error as e:
            self._state = ConnectionState.FAILED
            error_msg = f"Socket error connecting to {self.host}:{self.port}: {e}"
            logger.error(error_msg)
            raise IQFeedConnectionError(error_msg, self.host, self.port, e)
            
        except Exception as e:
            self._state = ConnectionState.FAILED
            error_msg = f"Unexpected error during connection: {e}"
            logger.error(error_msg)
            raise IQFeedConnectionError(error_msg, self.host, self.port, e)
    
    def disconnect(self):
        """Disconnect from IQFeed and cleanup resources."""
        logger.info("Disconnecting from IQFeed")
        
        self._running = False
        self._state = ConnectionState.DISCONNECTED
        
        # Wait for threads to finish
        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=5.0)
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        
        # Close socket
        if self._socket:
            try:
                self._socket.close()
            except Exception as e:
                logger.warning(f"Error closing socket: {e}")
            finally:
                self._socket = None
        
        # Clear subscriptions
        with self._subscription_lock:
            self._l2_subscriptions.clear()
            self._trade_subscriptions.clear()
            self._quote_subscriptions.clear()
            self._tick_subscriptions.clear()
        
        self._session_id = None
        self._connect_time = None
        
        logger.info("Disconnected from IQFeed")
    
    def is_connected(self) -> bool:
        """Check if currently connected to IQFeed and not shutting down."""
        return (self._state == ConnectionState.CONNECTED and 
                self._socket is not None and 
                not self._shutdown_requested)
    
    def get_status(self) -> ClientStatus:
        """
        Get current client status.
        
        Returns:
            ClientStatus with current state information
        """
        uptime = 0.0
        if self._connect_time:
            uptime = (datetime.now() - self._connect_time).total_seconds()
        
        with self._subscription_lock:
            total_subs = (len(self._l2_subscriptions) + 
                         len(self._trade_subscriptions) + 
                         len(self._quote_subscriptions) +
                         len(self._tick_subscriptions))
        
        return ClientStatus(
            connected=self.is_connected(),
            state=self._state,
            uptime_seconds=uptime,
            feed_version="6.2.0.25",  # IQFeed version
            active_subscriptions=total_subs
        )
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get detailed connection information."""
        return {
            'host': self.host,
            'port': self.port,
            'connected': self.is_connected(),
            'session_id': self._session_id,
            'connect_time': self._connect_time.isoformat() if self._connect_time else None,
            'state': self._state.value,
            'last_heartbeat': self._last_heartbeat.isoformat() if self._last_heartbeat else None
        }
    
    def subscribe_l2_data(self, symbol: str) -> SubscriptionResult:
        """
        Subscribe to Level 2 order book data for symbol.
        
        Args:
            symbol: Stock symbol to subscribe to
            
        Returns:
            SubscriptionResult with subscription status
            
        Raises:
            ValueError: If symbol is invalid
            TypeError: If symbol is None or wrong type
        """
        # SECURITY: Critical symbol validation to prevent injection attacks
        if symbol is None:
            raise TypeError("Symbol cannot be None - critical security violation")
            
        if not isinstance(symbol, str):
            raise TypeError(f"Symbol must be string, got {type(symbol).__name__} - critical security violation")
            
        validation_error = self._validate_symbol_security(symbol)
        if validation_error:
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='l2',
                error_message=f"Symbol validation failed: {validation_error}"
            )
            
        if not self.is_connected():
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='l2',
                error_message="Not connected to IQFeed"
            )
        
        # Check rate limits
        rate_limit_result = self._check_rate_limits()
        if not rate_limit_result['allowed']:
            raise RateLimitError(
                f"Subscription rate limit exceeded: {rate_limit_result['current_rate']} subs/min",
                current_rate=rate_limit_result['current_rate'],
                limit_rate=self._max_subscriptions_per_minute,
                retry_after=rate_limit_result['retry_after']
            )
        
        try:
            # Send L2 subscription command (Level 2 depth of market)
            # Format: S,DEPTH_WATCH,{symbol} for Level 2 order book data
            command = f"S,DEPTH_WATCH,{symbol}\r\n"
            self._socket.send(command.encode('utf-8'))
            
            # Also send market maker watch for detailed L2 information
            mm_command = f"S,MMID_WATCH,{symbol}\r\n"
            self._socket.send(mm_command.encode('utf-8'))
            
            # Add to active subscriptions
            with self._subscription_lock:
                self._l2_subscriptions.add(symbol)
            
            # Update rate limiting counters
            self._update_rate_limit_counters()
            
            logger.info(f"Subscribed to L2 depth and market maker data for {symbol}")
            
            return SubscriptionResult(
                success=True,
                symbol=symbol,
                subscription_type='l2'
            )
            
        except Exception as e:
            error_msg = f"Failed to subscribe to L2 data for {symbol}: {e}"
            logger.error(error_msg)
            
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='l2',
                error_message=error_msg
            )
    
    def subscribe_trades(self, symbol: str) -> SubscriptionResult:
        """
        Subscribe to trade data for symbol using basic watch protocol.
        
        Args:
            symbol: Stock symbol to subscribe to
            
        Returns:
            SubscriptionResult with subscription status
            
        Raises:
            TypeError: If symbol is None or wrong type
        """
        # SECURITY: Critical symbol validation  
        if symbol is None:
            raise TypeError("Symbol cannot be None - critical security violation")
            
        if not isinstance(symbol, str):
            raise TypeError(f"Symbol must be string, got {type(symbol).__name__} - critical security violation")
            
        validation_error = self._validate_symbol_security(symbol)
        if validation_error:
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='trades',
                error_message=f"Symbol validation failed: {validation_error}"
            )
            
        if not self.is_connected():
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='trades',
                error_message="Not connected to IQFeed"
            )
        
        try:
            # Send trade subscription command (using watch for simplicity)
            command = f"w,{symbol}\n"
            self._socket.send(command.encode('utf-8'))
            
            # Add to active subscriptions
            with self._subscription_lock:
                self._trade_subscriptions.add(symbol)
            
            self._update_rate_limit_counters()
            
            logger.info(f"Subscribed to trades for {symbol}")
            
            return SubscriptionResult(
                success=True,
                symbol=symbol,
                subscription_type='trades'
            )
            
        except Exception as e:
            error_msg = f"Failed to subscribe to trades for {symbol}: {e}"
            logger.error(error_msg)
            
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='trades',
                error_message=error_msg
            )
    
    def subscribe_tick_data(self, symbol: str, tick_type: str = 'all') -> SubscriptionResult:
        """
        Subscribe to high-frequency tick data (Time & Sales) for symbol.
        
        This uses the proper IQFeed Time & Sales subscription protocol for 
        high-frequency tick data collection with full trade details.
        
        Args:
            symbol: Stock symbol to subscribe to
            tick_type: Type of tick data ('all', 'trades_only', 'quotes_only')
            
        Returns:
            SubscriptionResult with subscription status
            
        Raises:
            TypeError: If symbol is None or wrong type
            ValueError: If tick_type is invalid
        """
        # SECURITY: Critical symbol validation
        if symbol is None:
            raise TypeError("Symbol cannot be None - critical security violation")
            
        if not isinstance(symbol, str):
            raise TypeError(f"Symbol must be string, got {type(symbol).__name__} - critical security violation")
            
        # Validate tick_type
        valid_tick_types = ['all', 'trades_only', 'quotes_only']
        if tick_type not in valid_tick_types:
            raise ValueError(f"Invalid tick_type '{tick_type}'. Must be one of: {valid_tick_types}")
            
        validation_error = self._validate_symbol_security(symbol)
        if validation_error:
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='tick_data',
                error_message=f"Symbol validation failed: {validation_error}"
            )
            
        if not self.is_connected():
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='tick_data',
                error_message="Not connected to IQFeed"
            )
        
        # Check rate limits
        rate_limit_result = self._check_rate_limits()
        if not rate_limit_result['allowed']:
            raise RateLimitError(
                f"Tick subscription rate limit exceeded: {rate_limit_result['current_rate']} subs/min",
                current_rate=rate_limit_result['current_rate'],
                limit_rate=self._max_subscriptions_per_minute,
                retry_after=rate_limit_result['retry_after']
            )
        
        try:
            # Send Time & Sales (tick) subscription command
            # Format depends on tick type:
            if tick_type == 'all':
                # Subscribe to both trades and time & sales updates
                trade_command = f"w,{symbol}\r\n"  # Watch command for trades
                ts_command = f"S,TRADES_WATCH,{symbol}\r\n"  # Time & Sales watch
                self._socket.send(trade_command.encode('utf-8'))
                self._socket.send(ts_command.encode('utf-8'))
                logger.info(f"Subscribed to full tick data (trades + T&S) for {symbol}")
                
            elif tick_type == 'trades_only':
                # Subscribe only to trade executions
                command = f"S,TRADES_WATCH,{symbol}\r\n"
                self._socket.send(command.encode('utf-8'))
                logger.info(f"Subscribed to trades-only tick data for {symbol}")
                
            elif tick_type == 'quotes_only':
                # Subscribe only to quote updates (already handled by subscribe_quotes)
                return self.subscribe_quotes(symbol)
            
            # Add to active tick subscriptions (create new subscription type)
            with self._subscription_lock:
                if not hasattr(self, '_tick_subscriptions'):
                    self._tick_subscriptions = set()
                self._tick_subscriptions.add(symbol)
                # Also add to trade subscriptions for compatibility
                self._trade_subscriptions.add(symbol)
            
            # Update rate limiting counters
            self._update_rate_limit_counters()
            
            return SubscriptionResult(
                success=True,
                symbol=symbol,
                subscription_type='tick_data'
            )
            
        except Exception as e:
            error_msg = f"Failed to subscribe to tick data for {symbol}: {e}"
            logger.error(error_msg)
            
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='tick_data',
                error_message=error_msg
            )
    
    def subscribe_quotes(self, symbol: str) -> SubscriptionResult:
        """
        Subscribe to Level 1 NBBO quote data for symbol.
        
        Args:
            symbol: Stock symbol to subscribe to
            
        Returns:
            SubscriptionResult with subscription status
            
        Raises:
            TypeError: If symbol is None or wrong type
        """
        # SECURITY: Critical symbol validation
        if symbol is None:
            raise TypeError("Symbol cannot be None - critical security violation")
            
        if not isinstance(symbol, str):
            raise TypeError(f"Symbol must be string, got {type(symbol).__name__} - critical security violation")
            
        validation_error = self._validate_symbol_security(symbol)
        if validation_error:
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='quotes',
                error_message=f"Symbol validation failed: {validation_error}"
            )
            
        if not self.is_connected():
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='quotes',
                error_message="Not connected to IQFeed"
            )
        
        # Check rate limits
        rate_limit_result = self._check_rate_limits()
        if not rate_limit_result['allowed']:
            raise RateLimitError(
                f"Subscription rate limit exceeded: {rate_limit_result['current_rate']} subs/min",
                current_rate=rate_limit_result['current_rate'],
                limit_rate=self._max_subscriptions_per_minute,
                retry_after=rate_limit_result['retry_after']
            )
        
        try:
            # Send L1 quote subscription command
            command = f"w,{symbol}\n"
            self._socket.send(command.encode('utf-8'))
            
            # Add to active subscriptions
            with self._subscription_lock:
                self._quote_subscriptions.add(symbol)
            
            # Update rate limiting counters
            self._update_rate_limit_counters()
            
            logger.info(f"Subscribed to L1 quotes for {symbol}")
            
            return SubscriptionResult(
                success=True,
                symbol=symbol,
                subscription_type='quotes'
            )
            
        except Exception as e:
            error_msg = f"Failed to subscribe to L1 quotes for {symbol}: {e}"
            logger.error(error_msg)
            
            return SubscriptionResult(
                success=False,
                symbol=symbol,
                subscription_type='quotes',
                error_message=error_msg
            )
    
    def get_active_subscriptions(self) -> Dict[str, List[str]]:
        """
        Get all active subscriptions.
        
        Returns:
            Dictionary with lists of subscribed symbols by type
        """
        with self._subscription_lock:
            return {
                'l2_symbols': list(self._l2_subscriptions),
                'trade_symbols': list(self._trade_subscriptions),
                'quote_symbols': list(self._quote_subscriptions),
                'tick_symbols': list(self._tick_subscriptions)
            }
    
    def get_next_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Get next message from the general message queue.
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            Parsed message dictionary or None if timeout
        """
        try:
            return self._message_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_next_tick(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """
        Get next tick from the high-frequency tick buffer.
        
        This method is optimized for high-frequency tick data consumption
        with shorter default timeout for rapid processing.
        
        Args:
            timeout: Timeout in seconds (default 0.1 for rapid tick processing)
            
        Returns:
            Parsed tick message dictionary or None if timeout
        """
        try:
            return self._tick_buffer.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_tick_buffer_stats(self) -> Dict[str, Any]:
        """
        Get tick buffer statistics for monitoring high-frequency data flow.
        
        Returns:
            Dictionary with tick buffer statistics
        """
        return {
            'buffer_size': self._tick_buffer.qsize(),
            'buffer_capacity': self._tick_buffer.maxsize,
            'buffer_utilization': self._tick_buffer.qsize() / self._tick_buffer.maxsize,
            'overflow_count': self._tick_buffer_overflow_count,
            'is_nearly_full': self._tick_buffer.qsize() > (self._tick_buffer.maxsize * 0.8)
        }
    
    def drain_tick_buffer(self, max_ticks: int = 1000) -> List[Dict[str, Any]]:
        """
        Drain multiple ticks from buffer for batch processing.
        
        This is optimized for high-throughput tick processing where
        consuming ticks in batches is more efficient.
        
        Args:
            max_ticks: Maximum number of ticks to drain in one call
            
        Returns:
            List of tick messages (up to max_ticks)
        """
        ticks = []
        count = 0
        
        while count < max_ticks:
            try:
                tick = self._tick_buffer.get_nowait()
                ticks.append(tick)
                count += 1
            except queue.Empty:
                break
        
        return ticks
    
    def get_bandwidth_statistics(self) -> Dict[str, Any]:
        """
        Get current bandwidth and throughput statistics.
        
        Returns:
            Dictionary with bandwidth statistics
        """
        with self._stats_lock:
            now = datetime.now()
            elapsed = (now - self._stats_start_time).total_seconds()
            
            if elapsed > 0:
                bytes_per_second = self._bytes_received / elapsed
                messages_per_second = self._messages_received / elapsed
                avg_message_size = self._bytes_received / self._messages_received if self._messages_received > 0 else 0
            else:
                bytes_per_second = 0
                messages_per_second = 0
                avg_message_size = 0
            
            return {
                'bytes_received_per_second': bytes_per_second,
                'messages_received_per_second': messages_per_second,
                'total_bytes_received': self._bytes_received,
                'total_messages_received': self._messages_received,
                'average_message_size': avg_message_size,
                'last_update': now
            }
    
    def check_sequence_integrity(self) -> List[Dict[str, Any]]:
        """
        Check for sequence gaps in received messages.
        
        Returns:
            List of detected sequence gaps
        """
        return self._sequence_gaps.copy()
    
    def reconnect(self) -> ConnectionResult:
        """
        Attempt to reconnect to IQFeed.
        
        Returns:
            ConnectionResult with reconnection status
        """
        logger.info("Attempting to reconnect to IQFeed")
        
        # Save current subscriptions before disconnecting
        saved_l2_subs = set()
        saved_trade_subs = set()
        saved_quote_subs = set()
        saved_tick_subs = set()
        
        with self._subscription_lock:
            saved_l2_subs = self._l2_subscriptions.copy()
            saved_trade_subs = self._trade_subscriptions.copy()
            saved_quote_subs = self._quote_subscriptions.copy()
            saved_tick_subs = self._tick_subscriptions.copy()
        
        # Disconnect first
        self.disconnect()
        
        # Wait before reconnecting
        time.sleep(2)
        
        # Reconnect
        try:
            result = self.connect()
            
            if result.success:
                # Restore subscriptions
                logger.info(f"Restoring {len(saved_l2_subs)} L2, {len(saved_trade_subs)} trade, "
                           f"{len(saved_tick_subs)} tick, and {len(saved_quote_subs)} quote subscriptions")
                
                # Restore L2 subscriptions
                for symbol in saved_l2_subs:
                    try:
                        sub_result = self.subscribe_l2_data(symbol)
                        if not sub_result.success:
                            logger.warning(f"Failed to restore L2 subscription for {symbol}: {sub_result.error_message}")
                    except Exception as e:
                        logger.error(f"Error restoring L2 subscription for {symbol}: {e}")
                
                # Restore trade subscriptions
                for symbol in saved_trade_subs:
                    try:
                        sub_result = self.subscribe_trades(symbol)
                        if not sub_result.success:
                            logger.warning(f"Failed to restore trade subscription for {symbol}: {sub_result.error_message}")
                    except Exception as e:
                        logger.error(f"Error restoring trade subscription for {symbol}: {e}")
                
                # Restore tick subscriptions (high-frequency Time & Sales)
                for symbol in saved_tick_subs:
                    try:
                        sub_result = self.subscribe_tick_data(symbol, tick_type='all')
                        if not sub_result.success:
                            logger.warning(f"Failed to restore tick subscription for {symbol}: {sub_result.error_message}")
                    except Exception as e:
                        logger.error(f"Error restoring tick subscription for {symbol}: {e}")
                
                # Restore quote subscriptions
                for symbol in saved_quote_subs:
                    try:
                        sub_result = self.subscribe_quotes(symbol)
                        if not sub_result.success:
                            logger.warning(f"Failed to restore quote subscription for {symbol}: {sub_result.error_message}")
                    except Exception as e:
                        logger.error(f"Error restoring quote subscription for {symbol}: {e}")
                
                logger.info("Subscription restoration completed")
            
            return result
            
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            return ConnectionResult(
                success=False,
                error_message=f"Reconnection failed: {e}"
            )
    
    def shutdown(self, graceful: bool = True) -> ConnectionResult:
        """
        Shutdown client with optional graceful cleanup.
        
        Args:
            graceful: Whether to perform graceful shutdown
            
        Returns:
            ConnectionResult with shutdown status
        """
        logger.info(f"Shutting down client (graceful={graceful})")
        
        try:
            if graceful:
                # Unsubscribe from all symbols
                with self._subscription_lock:
                    for symbol in list(self._l2_subscriptions):
                        try:
                            self._socket.send(f"S,DEPTH_UNWATCH,{symbol}\r\n".encode('utf-8'))
                            self._socket.send(f"S,MMID_UNWATCH,{symbol}\r\n".encode('utf-8'))
                        except Exception as e:
                            logger.warning(f"Failed to unsubscribe L2 for {symbol} during shutdown: {e}")
                    
                    for symbol in list(self._trade_subscriptions):
                        try:
                            self._socket.send(f"r,{symbol}\n".encode('utf-8'))  # Unwatch trades
                        except Exception as e:
                            logger.warning(f"Failed to unsubscribe trades for {symbol} during shutdown: {e}")
                    
                    for symbol in list(self._tick_subscriptions):
                        try:
                            self._socket.send(f"S,TRADES_UNWATCH,{symbol}\r\n".encode('utf-8'))  # Unwatch Time & Sales
                            self._socket.send(f"r,{symbol}\n".encode('utf-8'))  # Also unwatch basic trades
                        except Exception as e:
                            logger.warning(f"Failed to unsubscribe tick data for {symbol} during shutdown: {e}")
                    
                    for symbol in list(self._quote_subscriptions):
                        try:
                            self._socket.send(f"r,{symbol}\n".encode('utf-8'))  # Unwatch quotes
                        except Exception as e:
                            logger.warning(f"Failed to unsubscribe quotes for {symbol} during shutdown: {e}")
                
                # Brief pause for commands to process
                time.sleep(0.5)
            
            self.disconnect()
            
            return ConnectionResult(success=True)
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            return ConnectionResult(
                success=False,
                error_message=f"Shutdown error: {e}"
            )
    
    def _start_background_threads(self):
        """Start background threads for message receiving and monitoring."""
        self._receive_thread = threading.Thread(target=self._receive_messages, daemon=True)
        self._monitor_thread = threading.Thread(target=self._monitor_connection, daemon=True)
        
        self._receive_thread.start()
        self._monitor_thread.start()
    
    def _receive_messages(self):
        """Background thread to receive and parse messages from IQFeed."""
        logger.info("Message receiver thread started")
        buffer = ""
        
        while self._running and self._socket:
            try:
                data = self._socket.recv(4096).decode('utf-8')
                if not data:
                    logger.warning("No data received from IQFeed")
                    break
                
                buffer += data
                lines = buffer.split('\n')
                buffer = lines[-1]  # Keep incomplete line
                
                for line in lines[:-1]:
                    if line.strip():
                        self._process_message(line.strip())
                
                # Update statistics
                with self._stats_lock:
                    self._bytes_received += len(data)
                    self._last_stats_update = datetime.now()
                
            except socket.timeout:
                continue
            except socket.error as e:
                if self._running:
                    logger.error(f"Socket error in receive thread: {e}")
                break
            except Exception as e:
                logger.error(f"Error in receive thread: {e}")
                if not self._running:
                    break
        
        logger.info("Message receiver thread stopped")
    
    def _process_message(self, message: str):
        """Process a single message from IQFeed."""
        try:
            # Skip timestamp-only messages
            if message.startswith('T,') and len(message.split(',')) <= 2:
                return
            
            # Parse message based on type
            parsed_message = None
            
            if (message.startswith('L2,') or message.startswith('L,') or 
                message.startswith('U,') or message.startswith('M,') or 
                message.startswith('D,')):
                parsed_message = self._parser.parse_l2_message(message)
                if parsed_message:
                    parsed_message['message_type'] = 'l2'
            elif message.startswith('T,'):
                parsed_message = self._parser.parse_trade_message(message)
                if parsed_message:
                    parsed_message['message_type'] = 'trade'
            elif message.startswith('Q,'):
                parsed_message = self._parser.parse_quote_message(message)
                if parsed_message:
                    parsed_message['message_type'] = 'quote'
            elif message.startswith('n,'):
                # News or other data - create basic message
                parts = message.split(',')
                parsed_message = {
                    'message_type': 'news',
                    'symbol': parts[2] if len(parts) > 2 else '',
                    'timestamp': datetime.now(),
                    'raw_message': message
                }
            
            if parsed_message:
                # Check sequence integrity
                self._check_message_sequence(parsed_message)
                
                # Route message to appropriate buffer
                try:
                    # High-frequency tick data goes to dedicated tick buffer
                    if (parsed_message.get('message_type') == 'trade' and
                        parsed_message.get('symbol') in self._tick_subscriptions):
                        
                        try:
                            self._tick_buffer.put_nowait(parsed_message)
                        except queue.Full:
                            self._tick_buffer_overflow_count += 1
                            logger.warning(f"Tick buffer full (overflow #{self._tick_buffer_overflow_count}), dropping tick for {parsed_message.get('symbol')}")
                            
                            # Still try to add to general queue as fallback
                            try:
                                self._message_queue.put_nowait(parsed_message)
                            except queue.Full:
                                pass  # Both buffers full, drop message
                    else:
                        # Regular messages go to general message queue
                        self._message_queue.put_nowait(parsed_message)
                    
                    with self._stats_lock:
                        self._messages_received += 1
                        
                except queue.Full:
                    logger.warning("Message queue full, dropping message")
            
        except Exception as e:
            logger.warning(f"Failed to process message '{message[:50]}...': {e}")
    
    def _check_message_sequence(self, message: Dict[str, Any]):
        """Check message sequence for gaps."""
        if 'tick_id' not in message or 'symbol' not in message:
            return
        
        symbol = message['symbol']
        tick_id = message['tick_id']
        
        if symbol in self._last_tick_ids:
            last_id = self._last_tick_ids[symbol]
            if tick_id != last_id + 1 and tick_id > last_id + 1:
                # Gap detected
                gap_info = {
                    'symbol': symbol,
                    'expected_tick_id': last_id + 1,
                    'received_tick_id': tick_id,
                    'gap_size': tick_id - last_id - 1,
                    'timestamp': datetime.now()
                }
                self._sequence_gaps.append(gap_info)
                
                # Keep only recent gaps (last 100)
                if len(self._sequence_gaps) > 100:
                    self._sequence_gaps = self._sequence_gaps[-100:]
        
        self._last_tick_ids[symbol] = tick_id
    
    def _monitor_connection(self):
        """Background thread to monitor connection health."""
        logger.info("Connection monitor thread started")
        
        while self._running:
            try:
                if self.is_connected():
                    # Send heartbeat/status check
                    self._last_heartbeat = datetime.now()
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
        
        logger.info("Connection monitor thread stopped")
    
    def _check_rate_limits(self) -> Dict[str, Any]:
        """Check if we're within rate limits for subscriptions."""
        now = time.time()
        
        # Clean old subscription timestamps
        if now - self._last_subscription_time > self._rate_limit_window:
            self._subscription_count = 0
            self._last_subscription_time = now
        
        current_rate = self._subscription_count / (self._rate_limit_window / 60)  # per minute
        
        if self._subscription_count >= self._max_subscriptions_per_minute:
            retry_after = self._rate_limit_window - (now - self._last_subscription_time)
            return {
                'allowed': False,
                'current_rate': current_rate,
                'retry_after': max(1, int(retry_after))
            }
        
        return {
            'allowed': True,
            'current_rate': current_rate,
            'retry_after': 0
        }
    
    def _update_rate_limit_counters(self):
        """Update rate limiting counters after successful subscription."""
        now = time.time()
        if now - self._last_subscription_time > self._rate_limit_window:
            self._subscription_count = 1
            self._last_subscription_time = now
        else:
            self._subscription_count += 1
    
    def _restore_subscriptions(self):
        """Restore subscriptions after reconnection."""
        logger.info("Restoring subscriptions after reconnection")
        
        with self._subscription_lock:
            # Restore L2 subscriptions
            for symbol in list(self._l2_subscriptions):
                try:
                    result = self.subscribe_l2_data(symbol)
                    if not result.success:
                        logger.warning(f"Failed to restore L2 subscription for {symbol}: {result.error_message}")
                except Exception as e:
                    logger.error(f"Error restoring L2 subscription for {symbol}: {e}")
            
            # Restore trade subscriptions
            for symbol in list(self._trade_subscriptions):
                try:
                    result = self.subscribe_trades(symbol)
                    if not result.success:
                        logger.warning(f"Failed to restore trades subscription for {symbol}: {result.error_message}")
                except Exception as e:
                    logger.error(f"Error restoring trades subscription for {symbol}: {e}")
            
            # Restore quote subscriptions
            for symbol in list(self._quote_subscriptions):
                try:
                    result = self.subscribe_quotes(symbol)
                    if not result.success:
                        logger.warning(f"Failed to restore quotes subscription for {symbol}: {result.error_message}")
                except Exception as e:
                    logger.error(f"Error restoring quotes subscription for {symbol}: {e}")
        
        logger.info("Subscription restoration completed")
    
    async def get_historical_level2(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Download historical Level 2 order book data.
        
        Args:
            symbol: Trading symbol
            start_date: Start date for historical data
            end_date: End date for historical data
            
        Returns:
            List of L2 order book updates
        """
        try:
            if not self.is_connected():
                raise IQFeedConnectionError("Not connected to IQFeed", self._host, self._port)
            
            logger.info(f"Requesting historical L2 data for {symbol} from {start_date.date()} to {end_date.date()}")
            
            # Format dates for IQFeed HTD command
            start_str = start_date.strftime("%Y%m%d %H%M%S")
            end_str = end_date.strftime("%Y%m%d %H%M%S")
            
            # Send HTD (Historical Time and Sales Depth) command
            command = f"HTD,{symbol},{start_str},{end_str}\r\n"
            
            # Store current message queue size to detect new messages
            initial_queue_size = self._message_queue.qsize()
            
            # Send the command
            self._socket.send(command.encode('utf-8'))
            logger.info(f"Sent HTD command for {symbol}")
            
            # Collect historical L2 data
            l2_data = []
            timeout_start = time.time()
            timeout_seconds = 60  # 60 second timeout
            receiving_data = False
            
            while time.time() - timeout_start < timeout_seconds:
                try:
                    message = self._message_queue.get(timeout=1.0)
                    
                    # Check for end-of-data marker or relevant L2 data
                    if 'symbol' in message and message['symbol'] == symbol:
                        if message.get('message_type') == 'l2':
                            l2_data.append(message)
                            receiving_data = True
                        elif message.get('message_type') == 'end_message':
                            logger.info(f"Received end-of-data marker for {symbol}")
                            break
                    
                    # If we started receiving data but haven't gotten any for 5 seconds, assume done
                    if receiving_data and len(l2_data) > 0:
                        if time.time() - timeout_start > 10 and self._message_queue.empty():
                            logger.info(f"No more L2 data for {symbol} - assuming complete")
                            break
                
                except queue.Empty:
                    if receiving_data and len(l2_data) > 0:
                        # If we were receiving data but queue is empty, we might be done
                        logger.info(f"L2 data collection complete for {symbol} - queue timeout")
                        break
                    continue
            
            logger.info(f"Collected {len(l2_data)} L2 records for {symbol}")
            return l2_data
            
        except Exception as e:
            logger.error(f"Historical L2 download failed for {symbol}: {e}")
            raise ProcessingError(f"Historical L2 download failed", "historical_data", e)
    
    async def get_historical_trades(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Download historical trade data.
        
        Args:
            symbol: Trading symbol
            start_date: Start date for historical data
            end_date: End date for historical data
            
        Returns:
            List of trade records
        """
        try:
            if not self.is_connected():
                raise IQFeedConnectionError("Not connected to IQFeed", self._host, self._port)
            
            logger.info(f"Requesting historical trades for {symbol} from {start_date.date()} to {end_date.date()}")
            
            # Format dates for IQFeed HTT command  
            start_str = start_date.strftime("%Y%m%d %H%M%S")
            end_str = end_date.strftime("%Y%m%d %H%M%S")
            
            # Send HTT (Historical Tick) command
            command = f"HTT,{symbol},{start_str},{end_str}\r\n"
            
            # Send the command
            self._socket.send(command.encode('utf-8'))
            logger.info(f"Sent HTT command for {symbol}")
            
            # Collect historical trade data
            trade_data = []
            timeout_start = time.time()
            timeout_seconds = 60  # 60 second timeout
            receiving_data = False
            
            while time.time() - timeout_start < timeout_seconds:
                try:
                    message = self._message_queue.get(timeout=1.0)
                    
                    # Check for relevant trade data
                    if 'symbol' in message and message['symbol'] == symbol:
                        if message.get('message_type') == 'trade':
                            trade_data.append(message)
                            receiving_data = True
                        elif message.get('message_type') == 'end_message':
                            logger.info(f"Received end-of-data marker for {symbol}")
                            break
                    
                    # If we started receiving data but haven't gotten any for 5 seconds, assume done
                    if receiving_data and len(trade_data) > 0:
                        if time.time() - timeout_start > 10 and self._message_queue.empty():
                            logger.info(f"No more trade data for {symbol} - assuming complete")
                            break
                
                except queue.Empty:
                    if receiving_data and len(trade_data) > 0:
                        # If we were receiving data but queue is empty, we might be done
                        logger.info(f"Trade data collection complete for {symbol} - queue timeout")
                        break
                    continue
            
            logger.info(f"Collected {len(trade_data)} trade records for {symbol}")
            return trade_data
            
        except Exception as e:
            logger.error(f"Historical trades download failed for {symbol}: {e}")
            raise ProcessingError(f"Historical trades download failed", "historical_data", e)