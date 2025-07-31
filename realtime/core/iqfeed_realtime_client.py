#!/usr/bin/env python3
"""
IQFeed Real-time Data Client
- Connects to multiple IQFeed ports (L1, L2, Admin)
- Handles multiple tickers simultaneously  
- Tracks latency and network performance
- Sends data to Kafka and metrics to Redis
"""

import socket
import threading
import time
import json
import logging
import queue
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional, Callable
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import asyncio

# Add project root for auto-downloader import
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Local imports
from realtime.monitoring.latency_monitor import LatencyMonitor
from realtime.monitoring.network_monitor import NetworkMonitor
from realtime.core.kafka_producer import RealTimeKafkaProducer
from realtime.core.redis_metrics import RedisMetrics
from streaming.auto_downloader_v2 import AutoDownloader

# Try to import ClickHouse for auto-download integration
try:
    import clickhouse_connect
    CLICKHOUSE_AVAILABLE = True
except ImportError:
    CLICKHOUSE_AVAILABLE = False
    logger.warning("ClickHouse not available - auto-download data won't be saved to database")

logger = logging.getLogger(__name__)

@dataclass
class RealTimeTickData:
    """Real-time tick data structure"""
    symbol: str
    timestamp: str
    system_timestamp: str
    price: float
    size: int
    exchange: str
    conditions: str
    iqfeed_latency_ms: float
    system_latency_ms: float

@dataclass  
class RealTimeL1Data:
    """Real-time L1 quote data structure"""
    symbol: str
    timestamp: str
    system_timestamp: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    last_trade_price: float
    last_trade_size: int
    iqfeed_latency_ms: float
    system_latency_ms: float

@dataclass
class RealTimeL2Data:
    """Real-time L2 order book data structure"""
    symbol: str
    timestamp: str
    system_timestamp: str
    side: str  # 'bid' or 'ask'
    level: int
    price: float
    size: int
    market_maker: str
    iqfeed_latency_ms: float
    system_latency_ms: float


class IQFeedConnection:
    """Manages a single IQFeed socket connection"""
    
    def __init__(self, host: str, port: int, connection_type: str):
        self.host = host
        self.port = port
        self.connection_type = connection_type
        self.socket = None
        self.connected = False
        self.running = False
        
    def connect(self) -> bool:
        """Establish connection to IQFeed"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)
            self.socket.connect((self.host, self.port))
            
            # Set protocol version
            if self.connection_type != 'admin':
                self.socket.send(b"S,SET PROTOCOL,6.2\r\n")
                response = self.socket.recv(1024).decode('utf-8')
                logger.info(f"{self.connection_type} protocol response: {response.strip()}")
            
            self.connected = True
            logger.info(f"✓ Connected to {self.connection_type} port {self.port}")
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to {self.connection_type} port {self.port}: {e}")
            return False
    
    def disconnect(self):
        """Close connection"""
        self.running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"💥 HARD FAILURE: Could not close socket for {self.connection_type}: {e}")
                raise Exception(f"Socket cleanup failure: {e}")
            self.socket = None
            logger.info(f"Disconnected from {self.connection_type}")


class IQFeedRealTimeClient:
    """
    Multi-port IQFeed real-time data client
    Designed for hedge fund level performance and scaling
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.start_time = None
        
        # Connections
        self.connections = {}
        self.subscribed_symbols: Set[str] = set()
        
        # Data processing
        self.message_queue = queue.Queue(maxsize=10000)
        self.data_handlers: Dict[str, Callable] = {}
        
        # Performance monitoring
        self.latency_monitor = LatencyMonitor(config)
        self.network_monitor = NetworkMonitor(config)
        
        # External components
        self.kafka_producer = RealTimeKafkaProducer(config)
        self.redis_metrics = RedisMetrics(config)
        
        # Auto-download integration
        self.auto_downloader = AutoDownloader()
        self.clickhouse_client = None
        if CLICKHOUSE_AVAILABLE and config.get('clickhouse'):
            try:
                self.clickhouse_client = clickhouse_connect.get_client(
                    host=config['clickhouse']['host'],
                    port=config['clickhouse']['port'],
                    database=config['clickhouse']['database'],
                    username=config['clickhouse']['username'],
                    password=config['clickhouse']['password']
                )
                # TEST THE CONNECTION - NO SILENT FAILURES!
                test_result = self.clickhouse_client.query("SELECT 1").result_rows
                if test_result[0][0] != 1:
                    raise Exception("ClickHouse test query failed")
                logger.info("✓ ClickHouse client initialized and TESTED - connection verified")
            except Exception as e:
                logger.error(f"💥 HARD FAILURE: ClickHouse initialization failed: {e}")
                raise Exception(f"ClickHouse connection REQUIRED for production - Fix this! Error: {e}")
        
        # Threading
        self.executor = ThreadPoolExecutor(max_workers=config.get('scaling', {}).get('max_worker_threads', 8))
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'messages_processed': 0,
            'errors': 0,
            'last_message_time': None,
            'symbols_subscribed': 0,
            'auto_downloads': 0,
            'auto_download_failures': 0,
            'validation_errors': 0
        }
    
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
        if len(sanitized) > 12:  # Allow slightly longer for some instruments
            return f"Symbol too long: {len(sanitized)} chars (max 12)"
            
        # Character validation - only allow alphanumeric and safe characters
        import re
        if not re.match(r'^[A-Z0-9._/-]+$', sanitized.upper()):
            return f"Symbol contains invalid characters: '{sanitized}'. Only A-Z, 0-9, '.', '_', '/', '-' allowed"
            
        # Prevent control characters and injection attempts
        for char in sanitized:
            if ord(char) < 32 or ord(char) > 126:
                return f"Symbol contains control character: ord({ord(char)})"
                
        # Prevent common injection patterns
        dangerous_patterns = ['..', '\\', '<', '>', '"', "'", ';', '|', '&', '`', '$', '(', ')', '{', '}', '[', ']']
        for pattern in dangerous_patterns:
            if pattern in sanitized:
                return f"Symbol contains dangerous pattern: '{pattern}'"
                
        return None  # Valid symbol
    
    def _validate_financial_data_security(self, price: float, size: int, symbol: str, context: str) -> Optional[str]:
        """
        SECURITY: Comprehensive financial data validation.
        
        Args:
            price: Price to validate
            size: Size to validate
            symbol: Symbol for context
            context: Context for error reporting
            
        Returns:
            Error message if invalid, None if valid
        """
        # Price validation
        if not isinstance(price, (int, float)):
            return f"{context} price must be numeric for {symbol}, got {type(price).__name__}"
            
        # SECURITY: Prevent negative prices
        if price < 0:
            return f"{context} price cannot be negative for {symbol}: {price}"
            
        # SECURITY: Prevent unreasonably high prices  
        if price > 100000.0:  # $100K per share is extreme
            return f"{context} price unreasonably high for {symbol}: {price} (max $100K)"
            
        # Size validation
        if not isinstance(size, int):
            return f"{context} size must be integer for {symbol}, got {type(size).__name__}"
            
        # SECURITY: Prevent negative sizes in most contexts
        if size < 0 and context not in ['delete', 'adjustment']:
            return f"{context} size cannot be negative for {symbol}: {size}"
            
        # SECURITY: Prevent unreasonably large sizes
        if size > 1000000000:  # 1B shares is extreme
            return f"{context} size unreasonably large for {symbol}: {size} (max 1B)"
            
        return None  # Valid data
        
    def setup_connections(self):
        """Setup all IQFeed connections"""
        iqfeed_config = self.config['iqfeed']
        host = iqfeed_config['host']
        ports = iqfeed_config['ports']
        
        # Create connections
        connection_types = ['level1', 'level2', 'admin']
        
        for conn_type in connection_types:
            if conn_type in ports:
                connection = IQFeedConnection(host, ports[conn_type], conn_type)
                if connection.connect():
                    self.connections[conn_type] = connection
                else:
                    logger.warning(f"Could not establish {conn_type} connection")
        
        logger.info(f"Established {len(self.connections)} IQFeed connections")
        
    def subscribe_symbols(self, symbols: List[str], data_types: List[str] = ['l1', 'l2']):
        """Subscribe to symbols for specified data types"""
        
        # SECURITY: Validate all symbols before subscribing
        for symbol in symbols:
            validation_error = self._validate_symbol_security(symbol)
            if validation_error:
                logger.error(f"💥 SECURITY FAILURE: Invalid symbol '{symbol}': {validation_error}")
                raise ValueError(f"Symbol validation failed for '{symbol}': {validation_error}")
        
        for symbol in symbols:
            for data_type in data_types:
                
                if data_type == 'l1' and 'level1' in self.connections:
                    # Level 1 subscription
                    command = f"w{symbol}\r\n"
                    try:
                        self.connections['level1'].socket.send(command.encode())
                        logger.debug(f"Subscribed to L1 for {symbol}")
                    except Exception as e:
                        logger.error(f"💥 HARD FAILURE: Failed to subscribe L1 for {symbol}: {e}")
                        raise Exception(f"L1 subscription CRITICAL FAILURE for {symbol}: {e}")
                        
                elif data_type == 'l2' and 'level2' in self.connections:
                    # Level 2 subscription  
                    command = f"w{symbol}\r\n"
                    try:
                        self.connections['level2'].socket.send(command.encode())
                        logger.debug(f"Subscribed to L2 for {symbol}")
                    except Exception as e:
                        logger.error(f"💥 HARD FAILURE: Failed to subscribe L2 for {symbol}: {e}")
                        raise Exception(f"L2 subscription CRITICAL FAILURE for {symbol}: {e}")
        
        self.subscribed_symbols.update(symbols)
        self.stats['symbols_subscribed'] = len(self.subscribed_symbols)
        
        logger.info(f"Subscribed to {len(symbols)} symbols for {data_types} data")
        
    def unsubscribe_symbols(self, symbols: List[str], data_types: List[str] = ['l1', 'l2']):
        """Unsubscribe from symbols"""
        
        for symbol in symbols:
            for data_type in data_types:
                
                if data_type == 'l1' and 'level1' in self.connections:
                    command = f"r{symbol}\r\n"
                    try:
                        self.connections['level1'].socket.send(command.encode())
                        logger.debug(f"Unsubscribed from L1 for {symbol}")
                    except Exception as e:
                        logger.error(f"Failed to unsubscribe L1 for {symbol}: {e}")
                        
                elif data_type == 'l2' and 'level2' in self.connections:
                    command = f"r{symbol}\r\n"
                    try:
                        self.connections['level2'].socket.send(command.encode())
                        logger.debug(f"Unsubscribed from L2 for {symbol}")
                    except Exception as e:
                        logger.error(f"Failed to unsubscribe L2 for {symbol}: {e}")
        
        self.subscribed_symbols -= set(symbols)
        self.stats['symbols_subscribed'] = len(self.subscribed_symbols)
        
    def parse_l1_message(self, message: str) -> Optional[RealTimeL1Data]:
        """Parse Level 1 message from IQFeed"""
        try:
            parts = message.split(',')
            if len(parts) < 10:
                return None
                
            system_time = datetime.now(timezone.utc).isoformat()
            iqfeed_timestamp = parts[1] if len(parts) > 1 else system_time
            
            # Calculate latencies
            iqfeed_latency = self.latency_monitor.calculate_iqfeed_latency(iqfeed_timestamp)
            system_latency = self.latency_monitor.calculate_system_latency(system_time)
            
            return RealTimeL1Data(
                symbol=parts[0],
                timestamp=iqfeed_timestamp,
                system_timestamp=system_time,
                bid=float(parts[2]) if parts[2] else 0.0,
                ask=float(parts[3]) if parts[3] else 0.0,
                bid_size=int(parts[4]) if parts[4] else 0,
                ask_size=int(parts[5]) if parts[5] else 0,
                last_trade_price=float(parts[6]) if parts[6] else 0.0,
                last_trade_size=int(parts[7]) if parts[7] else 0,
                iqfeed_latency_ms=iqfeed_latency,
                system_latency_ms=system_latency
            )
            
        except Exception as e:
            logger.error(f"💥 HARD FAILURE: L1 message parsing failed: {e}")
            logger.error(f"🔥 RAW MESSAGE: {message}")
            raise Exception(f"L1 parsing CRITICAL FAILURE: {e}")
            
    def parse_l2_message(self, message: str) -> Optional[RealTimeL2Data]:
        """Parse Level 2 message from IQFeed"""
        try:
            parts = message.split(',')
            if len(parts) < 8:
                return None
                
            system_time = datetime.now(timezone.utc).isoformat()
            iqfeed_timestamp = parts[1] if len(parts) > 1 else system_time
            
            # Calculate latencies
            iqfeed_latency = self.latency_monitor.calculate_iqfeed_latency(iqfeed_timestamp)
            system_latency = self.latency_monitor.calculate_system_latency(system_time)
            
            return RealTimeL2Data(
                symbol=parts[0],
                timestamp=iqfeed_timestamp,
                system_timestamp=system_time,
                side=parts[2],  # 'B' for bid, 'A' for ask
                level=int(parts[3]) if parts[3] else 0,
                price=float(parts[4]) if parts[4] else 0.0,
                size=int(parts[5]) if parts[5] else 0,
                market_maker=parts[6] if len(parts) > 6 else '',
                iqfeed_latency_ms=iqfeed_latency,
                system_latency_ms=system_latency
            )
            
        except Exception as e:
            logger.error(f"💥 HARD FAILURE: L2 message parsing failed: {e}")
            logger.error(f"🔥 RAW MESSAGE: {message}")
            raise Exception(f"L2 parsing CRITICAL FAILURE: {e}")
    
    def process_message(self, connection_type: str, message: str):
        """Process incoming message from IQFeed"""
        try:
            system_time = datetime.now(timezone.utc)
            self.stats['messages_received'] += 1
            self.stats['last_message_time'] = system_time
            
            # Parse based on connection type
            if connection_type == 'level1':
                data = self.parse_l1_message(message)
                if data:
                    # Send to Kafka
                    self.kafka_producer.send_l1_data(data)
                    
                    # Update Redis metrics
                    self.redis_metrics.update_l1_metrics(data)
                    
            elif connection_type == 'level2':
                data = self.parse_l2_message(message)
                if data:
                    # Send to Kafka
                    self.kafka_producer.send_l2_data(data)
                    
                    # Update Redis metrics
                    self.redis_metrics.update_l2_metrics(data)
            
            self.stats['messages_processed'] += 1
            
        except Exception as e:
            logger.error(f"💥 HARD FAILURE: Message processing failed: {e}")
            logger.error(f"🔥 CONNECTION TYPE: {connection_type}")
            logger.error(f"🔥 RAW MESSAGE: {message}")
            self.stats['errors'] += 1
            raise Exception(f"Message processing CRITICAL FAILURE: {e}")
    
    def listen_connection(self, connection_type: str):
        """Listen for data on a specific connection"""
        connection = self.connections[connection_type]
        buffer = ""
        
        try:
            while self.running and connection.connected:
                connection.socket.settimeout(1.0)
                
                try:
                    chunk = connection.socket.recv(4096).decode('utf-8', errors='ignore')
                    if not chunk:
                        logger.warning(f"{connection_type} connection lost")
                        break
                    
                    buffer += chunk
                    
                    # Process complete messages
                    while '\r\n' in buffer:
                        line, buffer = buffer.split('\r\n', 1)
                        if line.strip():
                            self.process_message(connection_type, line.strip())
                            
                except socket.timeout:
                    continue  # Normal timeout, continue listening
                except Exception as e:
                    logger.error(f"💥 HARD FAILURE: Listening failed on {connection_type}: {e}")
                    raise Exception(f"Connection listening CRITICAL FAILURE on {connection_type}: {e}")
                    
        except Exception as e:
            logger.error(f"💥 CATASTROPHIC FAILURE: Fatal error in {connection_type} listener: {e}")
            raise Exception(f"Connection listener CATASTROPHIC FAILURE on {connection_type}: {e}")
        finally:
            connection.disconnect()
    
    def start(self, symbols: List[str], data_types: List[str] = ['l1', 'l2']):
        """Start real-time data collection"""
        logger.info(f"🚀 Starting IQFeed real-time client for {len(symbols)} symbols")
        
        self.running = True
        self.start_time = datetime.now(timezone.utc)
        
        # Setup connections
        self.setup_connections()
        
        if not self.connections:
            logger.error("No IQFeed connections available")
            return False
        
        # Subscribe to symbols
        self.subscribe_symbols(symbols, data_types)
        
        # Start listeners for each connection
        listeners = []
        for conn_type in self.connections:
            listener = threading.Thread(
                target=self.listen_connection,
                args=(conn_type,),
                name=f"{conn_type}_listener"
            )
            listener.daemon = True
            listener.start()
            listeners.append(listener)
            
        logger.info(f"✓ Started {len(listeners)} connection listeners")
        
        # Start monitoring threads
        self.latency_monitor.start()
        self.network_monitor.start()
        
        return True
    
    def download_historical_data(self, symbol: str, date: str, save_to_clickhouse: bool = True) -> bool:
        """
        Download historical data for missing symbol/date using auto-downloader
        Integrates with existing IQFeed auto-download functionality
        """
        logger.info(f"🔄 Auto-downloading historical data for {symbol} on {date}")
        
        try:
            # Check if data already exists
            tick_exists, l1_exists = self.auto_downloader.check_data_exists(symbol, date)
            
            if tick_exists and l1_exists:
                logger.info(f"✓ Historical data already exists for {symbol} on {date}")
                self.stats['auto_downloads'] += 1  # Count as successful operation
                return True
            
            # Use auto-downloader to download missing data
            success = self.auto_downloader.download_if_missing(symbol, date)
            
            if success:
                self.stats['auto_downloads'] += 1
                logger.info(f"✓ Successfully auto-downloaded {symbol} {date}")
                
                # Save to ClickHouse if requested and available
                if save_to_clickhouse and self.clickhouse_client:
                    self._save_auto_downloaded_data_to_clickhouse(symbol, date)
                
                return True
            else:
                self.stats['auto_download_failures'] += 1
                logger.warning(f"✗ Failed to auto-download {symbol} {date}")
                return False
                
        except Exception as e:
            logger.error(f"Error in auto-download for {symbol} {date}: {e}")
            self.stats['auto_download_failures'] += 1
            return False
    
    def _save_auto_downloaded_data_to_clickhouse(self, symbol: str, date: str):
        """Save auto-downloaded data to ClickHouse for integration with real-time pipeline"""
        try:
            # Process tick data
            tick_csv = f"{self.auto_downloader.tick_csv_dir}/{symbol}/{symbol}_ticks_{date}.csv"
            if os.path.exists(tick_csv) and os.path.getsize(tick_csv) > 100:
                self._insert_tick_csv_to_clickhouse(tick_csv, symbol, date)
            
            # Process L1 data
            l1_csv = f"{self.auto_downloader.l1_csv_dir}/{symbol}/{symbol}_l1_{date}.csv"
            if os.path.exists(l1_csv) and os.path.getsize(l1_csv) > 100:
                self._insert_l1_csv_to_clickhouse(l1_csv, symbol, date)
                
            logger.info(f"✓ Saved auto-downloaded {symbol} {date} to ClickHouse")
            
        except Exception as e:
            logger.error(f"Failed to save auto-downloaded data to ClickHouse: {e}")
    
    def _insert_tick_csv_to_clickhouse(self, csv_file: str, symbol: str, date: str):
        """Insert tick data from CSV file into ClickHouse"""
        import csv
        
        try:
            # Create separate ClickHouse client to avoid concurrency issues
            client = clickhouse_connect.get_client(
                host=self.config['clickhouse']['host'],
                port=self.config['clickhouse']['port'],
                database=self.config['clickhouse']['database'],
                username=self.config['clickhouse']['username'],
                password=self.config['clickhouse']['password']
            )
            
            rows = []
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        rows.append({
                            'symbol': symbol,
                            'timestamp': row['timestamp'],
                            'price': float(row['price']),
                            'size': int(row['size']),
                            'conditions': row.get('conditions', ''),
                            'ingestion_time': datetime.now(),
                            'source': 'auto_download'
                        })
                    except (ValueError, KeyError):
                        continue  # Skip malformed rows
            
            if rows:
                client.insert('market_ticks', rows)
                logger.info(f"✓ Inserted {len(rows)} auto-downloaded tick records for {symbol} {date}")
            
            client.close()
            
        except Exception as e:
            logger.error(f"Failed to insert tick data to ClickHouse: {e}")
    
    def _insert_l1_csv_to_clickhouse(self, csv_file: str, symbol: str, date: str):
        """Insert L1 data from CSV file into ClickHouse"""
        import csv
        
        try:
            # Create separate ClickHouse client to avoid concurrency issues
            client = clickhouse_connect.get_client(
                host=self.config['clickhouse']['host'],
                port=self.config['clickhouse']['port'],
                database=self.config['clickhouse']['database'],
                username=self.config['clickhouse']['username'],
                password=self.config['clickhouse']['password']
            )
            
            rows = []
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        rows.append({
                            'symbol': symbol,
                            'timestamp': row['timestamp'],
                            'bid': float(row['bid']),
                            'ask': float(row['ask']),
                            'bid_size': int(row['bid_size']),
                            'ask_size': int(row['ask_size']),
                            'ingestion_time': datetime.now(),
                            'source': 'auto_download'
                        })
                    except (ValueError, KeyError):
                        continue  # Skip malformed rows
            
            if rows:
                client.insert('market_l1', rows)
                logger.info(f"✓ Inserted {len(rows)} auto-downloaded L1 records for {symbol} {date}")
            
            client.close()
            
        except Exception as e:
            logger.error(f"Failed to insert L1 data to ClickHouse: {e}")
    
    def batch_download_historical_data(self, symbol_date_pairs: List[tuple], max_workers: int = 3) -> Dict[str, bool]:
        """
        Download multiple symbol/date pairs with rate limiting for IQFeed
        Returns dict of results: {symbol_date: success_bool}
        """
        logger.info(f"🔄 Batch auto-downloading {len(symbol_date_pairs)} symbol/date pairs")
        
        results = {}
        
        # Rate limiting to avoid overwhelming IQFeed trial limits
        for i, (symbol, date) in enumerate(symbol_date_pairs):
            if i > 0 and i % max_workers == 0:
                time.sleep(2)  # 2 second pause every few downloads
            
            success = self.download_historical_data(symbol, date)
            results[f"{symbol}_{date}"] = success
            
            # Small delay between downloads
            time.sleep(0.5)
        
        successful = sum(1 for success in results.values() if success)
        logger.info(f"✓ Batch download complete: {successful}/{len(symbol_date_pairs)} successful")
        
        return results
    
    def ensure_historical_data_available(self, symbols: List[str], date: str) -> bool:
        """
        Ensure historical data is available for all symbols on a specific date
        Used for replay functionality integration
        """
        logger.info(f"🔍 Ensuring historical data availability for {len(symbols)} symbols on {date}")
        
        missing_pairs = []
        
        # Check which symbols need data
        for symbol in symbols:
            tick_exists, l1_exists = self.auto_downloader.check_data_exists(symbol, date)
            if not (tick_exists and l1_exists):
                missing_pairs.append((symbol, date))
        
        if not missing_pairs:
            logger.info(f"✓ All historical data already available for {date}")
            return True
        
        logger.info(f"📥 Need to download {len(missing_pairs)} missing datasets for {date}")
        
        # Download missing data
        results = self.batch_download_historical_data(missing_pairs)
        
        # Check results
        successful_downloads = sum(1 for success in results.values() if success)
        total_needed = len(missing_pairs)
        
        if successful_downloads == total_needed:
            logger.info(f"✅ All missing historical data successfully downloaded for {date}")
            return True
        else:
            logger.warning(f"⚠️ Only {successful_downloads}/{total_needed} historical datasets downloaded for {date}")
            return False
        
    def stop(self):
        """Stop real-time data collection"""
        logger.info("🛑 Stopping IQFeed real-time client")
        
        self.running = False
        
        # Stop monitoring
        self.latency_monitor.stop()
        self.network_monitor.stop()
        
        # Unsubscribe from all symbols
        if self.subscribed_symbols:
            self.unsubscribe_symbols(list(self.subscribed_symbols))
        
        # Close connections
        for connection in self.connections.values():
            connection.disconnect()
        
        # Stop Kafka producer
        self.kafka_producer.close()
        
        # Close ClickHouse client
        if self.clickhouse_client:
            try:
                self.clickhouse_client.close()
                logger.info("✓ ClickHouse client closed")
            except Exception as e:
                logger.error(f"Error closing ClickHouse client: {e}")
        
        # Shutdown executor
        self.executor.shutdown(wait=True)
        
        logger.info("✓ IQFeed real-time client stopped")
        
    def get_statistics(self) -> Dict:
        """Get current statistics"""
        uptime = None
        if self.start_time:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            
        return {
            **self.stats,
            'uptime_seconds': uptime,
            'connections': {name: conn.connected for name, conn in self.connections.items()},
            'latency_stats': self.latency_monitor.get_stats(),
            'network_stats': self.network_monitor.get_stats()
        }