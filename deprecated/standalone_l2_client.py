#!/usr/bin/env python3
"""
Standalone IQFeed L2 Data Collection Client

Test script to validate L2 data collection functionality independently.
Demonstrates:
1. IQFeed L2 connection and subscription
2. Real-time L2 message parsing 
3. Order book reconstruction from L2 updates
4. Data export and validation

Following RULES.md: No mocks, real data only, loud failures
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingestion.iqfeed_client import IQFeedClient
from processing.order_book import OrderBookSnapshot, OrderBookManager
from ingestion.exceptions import IQFeedConnectionError, RateLimitError

# Configure logging for standalone operation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"l2_client_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger(__name__)


class StandaloneL2Client:
    """
    Standalone Level 2 data collection client for testing and validation.
    
    Provides complete L2 data collection pipeline from IQFeed connection
    through order book reconstruction and data export.
    """
    
    def __init__(self, symbols: List[str]):
        """
        Initialize standalone L2 client.
        
        Args:
            symbols: List of symbols to collect L2 data for
        """
        self.symbols = symbols
        self.client = IQFeedClient()
        self.order_book_manager = OrderBookManager()
        
        # Collection statistics
        self.start_time = datetime.now()
        self.messages_received = 0
        self.messages_processed = 0
        self.l2_messages = 0
        self.errors = 0
        
        # Data storage
        self.collected_messages: List[Dict[str, Any]] = []
        self.order_book_snapshots: Dict[str, List[Dict[str, Any]]] = {}
        
        logger.info(f"StandaloneL2Client initialized for symbols: {symbols}")
    
    def connect_and_subscribe(self) -> bool:
        """
        Connect to IQFeed and subscribe to L2 data for all symbols.
        
        Returns:
            True if connection and subscriptions successful
        """
        try:
            # Connect to IQFeed
            logger.info("Connecting to IQFeed...")
            result = self.client.connect()
            
            if not result.success:
                logger.error(f"IQFeed connection failed: {result.error_message}")
                return False
            
            logger.info(f"Connected to IQFeed: {result.session_id}")
            
            # Subscribe to L2 data for each symbol
            successful_subscriptions = 0
            for symbol in self.symbols:
                try:
                    logger.info(f"Subscribing to L2 data for {symbol}...")
                    sub_result = self.client.subscribe_l2_data(symbol)
                    
                    if sub_result.success:
                        successful_subscriptions += 1
                        logger.info(f"Successfully subscribed to L2 data for {symbol}")
                    else:
                        logger.error(f"Failed to subscribe to L2 data for {symbol}: {sub_result.error_message}")
                    
                    # Brief pause between subscriptions to respect rate limits
                    time.sleep(0.1)
                    
                except RateLimitError as e:
                    logger.warning(f"Rate limited on {symbol}, waiting {e.retry_after} seconds...")
                    time.sleep(e.retry_after)
                    
                    # Retry subscription
                    retry_result = self.client.subscribe_l2_data(symbol)
                    if retry_result.success:
                        successful_subscriptions += 1
                        logger.info(f"Successfully subscribed to L2 data for {symbol} (retry)")
                    else:
                        logger.error(f"Failed to subscribe to L2 data for {symbol} after retry")
                
                except Exception as e:
                    logger.error(f"Unexpected error subscribing to {symbol}: {e}")
                    self.errors += 1
            
            logger.info(f"Successfully subscribed to {successful_subscriptions}/{len(self.symbols)} symbols")
            return successful_subscriptions > 0
            
        except IQFeedConnectionError as e:
            logger.error(f"IQFeed connection error: {e}")
            logger.error(f"Recovery hint: {e.recovery_hint}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            return False
    
    def collect_data(self, duration_seconds: int = 60) -> bool:
        """
        Collect L2 data for specified duration.
        
        Args:
            duration_seconds: How long to collect data
            
        Returns:
            True if data collection completed successfully
        """
        logger.info(f"Starting L2 data collection for {duration_seconds} seconds...")
        
        start_time = time.time()
        last_stats_time = start_time
        
        try:
            while time.time() - start_time < duration_seconds:
                # Get next message with short timeout
                message = self.client.get_next_message(timeout=1.0)
                
                if message:
                    self.messages_received += 1
                    
                    # Process L2 messages
                    if message.get('message_type') == 'l2':
                        self.l2_messages += 1
                        self._process_l2_message(message)
                    
                    # Store all messages for analysis
                    self.collected_messages.append(message)
                    
                    # Periodic statistics
                    current_time = time.time()
                    if current_time - last_stats_time >= 10.0:  # Every 10 seconds
                        self._log_statistics()
                        last_stats_time = current_time
                
                # Check connection health
                if not self.client.is_connected():
                    logger.warning("IQFeed connection lost, attempting reconnection...")
                    reconnect_result = self.client.reconnect()
                    if not reconnect_result.success:
                        logger.error("Failed to reconnect to IQFeed")
                        return False
            
            logger.info(f"Data collection completed after {duration_seconds} seconds")
            return True
            
        except KeyboardInterrupt:
            logger.info("Data collection interrupted by user")
            return True
        except Exception as e:
            logger.error(f"Error during data collection: {e}")
            self.errors += 1
            return False
    
    def _process_l2_message(self, message: Dict[str, Any]):
        """Process individual L2 message and update order books."""
        try:
            # Apply L2 update to order book manager
            success = self.order_book_manager.apply_l2_update(message)
            
            if success:
                self.messages_processed += 1
                
                # Periodically capture order book snapshots
                symbol = message.get('symbol')
                if symbol and self.messages_processed % 100 == 0:  # Every 100 messages
                    order_book = self.order_book_manager.get_order_book(symbol)
                    if order_book:
                        snapshot = order_book.to_dict()
                        
                        if symbol not in self.order_book_snapshots:
                            self.order_book_snapshots[symbol] = []
                        
                        self.order_book_snapshots[symbol].append(snapshot)
            
        except Exception as e:
            logger.warning(f"Failed to process L2 message: {e}")
            self.errors += 1
    
    def _log_statistics(self):
        """Log current collection statistics."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        msg_rate = self.messages_received / elapsed if elapsed > 0 else 0
        l2_rate = self.l2_messages / elapsed if elapsed > 0 else 0
        
        logger.info(f"Stats: {self.messages_received} msgs ({msg_rate:.1f}/sec), "
                   f"{self.l2_messages} L2 msgs ({l2_rate:.1f}/sec), "
                   f"{self.messages_processed} processed, {self.errors} errors")
        
        # Order book statistics
        manager_stats = self.order_book_manager.get_statistics()
        logger.info(f"Order books: {manager_stats['total_symbols']} symbols, "
                   f"{manager_stats['total_updates']} updates")
    
    def validate_order_books(self) -> Dict[str, Any]:
        """
        Validate all reconstructed order books for integrity.
        
        Returns:
            Validation report with issues found
        """
        logger.info("Validating order book integrity...")
        
        validation_report = {
            'symbols_validated': 0,
            'total_issues': 0,
            'issues_by_symbol': {},
            'validation_timestamp': datetime.now().isoformat()
        }
        
        for symbol in self.order_book_manager.get_all_symbols():
            order_book = self.order_book_manager.get_order_book(symbol)
            if order_book:
                issues = order_book.validate_integrity()
                validation_report['symbols_validated'] += 1
                validation_report['total_issues'] += len(issues)
                
                if issues:
                    validation_report['issues_by_symbol'][symbol] = issues
                    logger.warning(f"Order book issues for {symbol}: {issues}")
                else:
                    logger.debug(f"Order book for {symbol} validated successfully")
        
        if validation_report['total_issues'] == 0:
            logger.info("All order books validated successfully - no integrity issues found")
        else:
            logger.warning(f"Found {validation_report['total_issues']} integrity issues "
                          f"across {len(validation_report['issues_by_symbol'])} symbols")
        
        return validation_report
    
    def export_data(self, output_dir: str = "./l2_data_export") -> bool:
        """
        Export collected data and order book snapshots.
        
        Args:
            output_dir: Directory to export data to
            
        Returns:
            True if export successful
        """
        try:
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Export collection statistics
            stats = {
                'collection_start': self.start_time.isoformat(),
                'collection_end': datetime.now().isoformat(),
                'duration_seconds': (datetime.now() - self.start_time).total_seconds(),
                'symbols': self.symbols,
                'messages_received': self.messages_received,
                'l2_messages': self.l2_messages,
                'messages_processed': self.messages_processed,
                'errors': self.errors,
                'order_book_manager_stats': self.order_book_manager.get_statistics()
            }
            
            stats_file = os.path.join(output_dir, f"l2_collection_stats_{timestamp}.json")
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)
            logger.info(f"Collection statistics exported to {stats_file}")
            
            # Export raw messages
            if self.collected_messages:
                messages_file = os.path.join(output_dir, f"l2_raw_messages_{timestamp}.jsonl")
                with open(messages_file, 'w') as f:
                    for message in self.collected_messages:
                        # Convert datetime objects to strings for JSON serialization
                        if 'timestamp' in message and isinstance(message['timestamp'], datetime):
                            message['timestamp'] = message['timestamp'].isoformat()
                        f.write(json.dumps(message) + '\n')
                logger.info(f"Raw messages ({len(self.collected_messages)}) exported to {messages_file}")
            
            # Export order book snapshots
            for symbol, snapshots in self.order_book_snapshots.items():
                snapshots_file = os.path.join(output_dir, f"{symbol}_order_book_snapshots_{timestamp}.jsonl")
                with open(snapshots_file, 'w') as f:
                    for snapshot in snapshots:
                        f.write(json.dumps(snapshot) + '\n')
                logger.info(f"Order book snapshots for {symbol} ({len(snapshots)}) exported to {snapshots_file}")
            
            # Export final order book states
            final_books = {}
            for symbol in self.order_book_manager.get_all_symbols():
                order_book = self.order_book_manager.get_order_book(symbol)
                if order_book:
                    final_books[symbol] = order_book.to_dict()
            
            if final_books:
                final_books_file = os.path.join(output_dir, f"final_order_books_{timestamp}.json")
                with open(final_books_file, 'w') as f:
                    json.dump(final_books, f, indent=2)
                logger.info(f"Final order book states exported to {final_books_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to export data: {e}")
            return False
    
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive collection and validation report.
        
        Returns:
            Complete report dictionary
        """
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        report = {
            'collection_summary': {
                'start_time': self.start_time.isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_seconds': elapsed,
                'symbols_requested': self.symbols,
                'symbols_with_data': self.order_book_manager.get_all_symbols()
            },
            'message_statistics': {
                'total_messages': self.messages_received,
                'l2_messages': self.l2_messages,
                'messages_processed': self.messages_processed,
                'processing_success_rate': self.messages_processed / max(self.l2_messages, 1),
                'errors': self.errors,
                'message_rate_per_second': self.messages_received / max(elapsed, 1),
                'l2_message_rate_per_second': self.l2_messages / max(elapsed, 1)
            },
            'order_book_statistics': self.order_book_manager.get_statistics(),
            'validation_report': self.validate_order_books(),
            'bandwidth_statistics': self.client.get_bandwidth_statistics() if self.client.is_connected() else None,
            'connection_status': self.client.get_status().connected if self.client else False
        }
        
        return report
    
    def disconnect(self):
        """Disconnect from IQFeed and cleanup resources."""
        if self.client and self.client.is_connected():
            logger.info("Disconnecting from IQFeed...")
            self.client.disconnect()
            logger.info("Disconnected from IQFeed")


def main():
    """Main entry point for standalone L2 client."""
    parser = argparse.ArgumentParser(description="Standalone IQFeed L2 Data Collection Client")
    parser.add_argument('--symbols', nargs='+', default=['AAPL', 'MSFT', 'GOOGL'], 
                       help='Symbols to collect L2 data for')
    parser.add_argument('--duration', type=int, default=60, 
                       help='Data collection duration in seconds')
    parser.add_argument('--output-dir', default='./l2_data_export',
                       help='Output directory for exported data')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("IQFeed L2 Data Collection Client - Standalone Mode")
    logger.info("=" * 60)
    logger.info(f"Symbols: {args.symbols}")
    logger.info(f"Duration: {args.duration} seconds")
    logger.info(f"Output directory: {args.output_dir}")
    
    # Initialize client
    client = StandaloneL2Client(args.symbols)
    
    try:
        # Connect and subscribe
        if not client.connect_and_subscribe():
            logger.error("Failed to connect and subscribe - exiting")
            return 1
        
        # Collect data
        logger.info(f"Starting data collection for {args.duration} seconds...")
        if not client.collect_data(args.duration):
            logger.warning("Data collection completed with errors")
        
        # Generate final report
        logger.info("Generating collection report...")
        report = client.generate_report()
        
        # Export data
        logger.info("Exporting collected data...")
        if client.export_data(args.output_dir):
            logger.info("Data export completed successfully")
        else:
            logger.error("Data export failed")
        
        # Display summary
        logger.info("=" * 60)
        logger.info("COLLECTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Duration: {report['collection_summary']['duration_seconds']:.1f} seconds")
        logger.info(f"Messages received: {report['message_statistics']['total_messages']}")
        logger.info(f"L2 messages: {report['message_statistics']['l2_messages']}")
        logger.info(f"Messages processed: {report['message_statistics']['messages_processed']}")
        logger.info(f"Processing success rate: {report['message_statistics']['processing_success_rate']:.2%}")
        logger.info(f"Errors: {report['message_statistics']['errors']}")
        logger.info(f"Order books created: {report['order_book_statistics']['total_symbols']}")
        logger.info(f"Total order book updates: {report['order_book_statistics']['total_updates']}")
        
        validation = report['validation_report']
        logger.info(f"Validation: {validation['symbols_validated']} symbols validated, "
                   f"{validation['total_issues']} integrity issues found")
        
        if validation['total_issues'] == 0:
            logger.info("✅ All order books validated successfully!")
            return 0
        else:
            logger.warning("⚠️  Order book integrity issues found - check detailed logs")
            return 1
            
    except KeyboardInterrupt:
        logger.info("Collection interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    sys.exit(main())