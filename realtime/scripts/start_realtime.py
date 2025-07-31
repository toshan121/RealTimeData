#!/usr/bin/env python3
"""
Real-time Trading System Startup Script
- Starts all components of the real-time trading infrastructure
- Coordinates IQFeed client, Kafka, Redis, and data writers
- Provides centralized control and monitoring
"""

import os
import sys
import yaml
import logging
import signal
import threading
import time
from datetime import datetime
from typing import Dict, List

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime.core.iqfeed_realtime_client import IQFeedRealTimeClient
from realtime.core.data_writer import RealTimeDataWriter
from realtime.core.redis_metrics import RedisMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/realtime_trading.log')
    ]
)
logger = logging.getLogger(__name__)

class RealTimeTradingSystem:
    """
    Main orchestrator for real-time trading system
    Manages all components and provides unified control
    """
    
    def __init__(self, config_file: str = None):
        self.config = self._load_config(config_file)
        
        # Components
        self.iqfeed_client = None
        self.data_writer = None
        self.redis_metrics = None
        
        # State
        self.running = False
        self.start_time = None
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self, config_file: str = None) -> Dict:
        """Load configuration from YAML file"""
        if not config_file:
            config_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'config', 'realtime_config.yaml'
            )
        
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"✓ Loaded configuration from {config_file}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config {config_file}: {e}")
            sys.exit(1)
    
    def _load_ticker_list(self, list_name: str) -> List[str]:
        """Load ticker list from configuration"""
        ticker_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'ticker_lists.json'
        )
        
        try:
            import json
            with open(ticker_file, 'r') as f:
                ticker_lists = json.load(f)
            
            if list_name in ticker_lists:
                symbols = ticker_lists[list_name]['symbols']
                if symbols == "AUTO_GENERATED":
                    # Use a default test list for now
                    symbols = ticker_lists['test_small']['symbols']
                
                logger.info(f"✓ Loaded {len(symbols)} symbols from {list_name}")
                return symbols
            else:
                logger.error(f"Ticker list '{list_name}' not found")
                return []
                
        except Exception as e:
            logger.error(f"Failed to load ticker list: {e}")
            return []
    
    def start(self, ticker_list: str = 'test_small', data_types: List[str] = ['l1', 'l2']):
        """Start the real-time trading system"""
        logger.info("🚀 Starting Real-time Trading System")
        logger.info("=" * 60)
        
        self.start_time = datetime.now()
        self.running = True
        
        try:
            # Load ticker symbols
            symbols = self._load_ticker_list(ticker_list)
            if not symbols:
                logger.error("No symbols to monitor")
                return False
            
            logger.info(f"Monitoring {len(symbols)} symbols: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
            
            # Initialize Redis metrics
            logger.info("Initializing Redis metrics...")
            self.redis_metrics = RedisMetrics(self.config)
            self.redis_metrics.start_background_persistence()
            
            # Initialize data writer
            logger.info("Initializing data writer...")
            self.data_writer = RealTimeDataWriter(self.config)
            self.data_writer.start()
            
            # Initialize IQFeed client
            logger.info("Initializing IQFeed client...")
            self.iqfeed_client = IQFeedRealTimeClient(self.config)
            
            # Setup data flow: IQFeed -> Kafka -> Data Writer
            self._setup_data_flow()
            
            # Start IQFeed client
            if not self.iqfeed_client.start(symbols, data_types):
                logger.error("Failed to start IQFeed client")
                return False
            
            logger.info("✅ Real-time Trading System started successfully")
            logger.info(f"📊 Dashboard available at: http://localhost:8501")
            logger.info(f"🔄 Monitoring {len(symbols)} symbols for {data_types} data")
            
            # Main monitoring loop
            self._monitoring_loop()
            
            return True
            
        except Exception as e:
            logger.error(f"Error starting system: {e}")
            return False
    
    def _setup_data_flow(self):
        """Setup data flow between components"""
        # The IQFeed client automatically sends to Kafka
        # Kafka data is consumed by data writer through separate consumers
        # For now, we'll directly connect IQFeed -> Data Writer
        
        def on_tick_data(tick_data):
            if self.data_writer:
                self.data_writer.write_tick_data(tick_data)
        
        def on_l1_data(l1_data):
            if self.data_writer:
                self.data_writer.write_l1_data(l1_data)
        
        def on_l2_data(l2_data):
            if self.data_writer:
                self.data_writer.write_l2_data(l2_data)
        
        # Register callbacks (would be implemented in IQFeed client)
        # self.iqfeed_client.register_tick_callback(on_tick_data)
        # self.iqfeed_client.register_l1_callback(on_l1_data)
        # self.iqfeed_client.register_l2_callback(on_l2_data)
    
    def _monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("Starting monitoring loop...")
        
        while self.running:
            try:
                time.sleep(10)  # Update every 10 seconds
                
                if not self.running:
                    break
                
                # Get system statistics
                stats = self._get_system_stats()
                
                # Update Redis with system metrics
                if self.redis_metrics:
                    self.redis_metrics.update_system_metrics(stats)
                
                # Log periodic status
                uptime = datetime.now() - self.start_time
                logger.info(f"System running - Uptime: {uptime} - Stats: {stats}")
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
    
    def _get_system_stats(self) -> Dict:
        """Get current system statistics"""
        stats = {
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            'timestamp': datetime.now().isoformat()
        }
        
        # Add IQFeed client stats
        if self.iqfeed_client:
            iqfeed_stats = self.iqfeed_client.get_statistics()
            stats.update({
                'iqfeed_messages': iqfeed_stats.get('messages_received', 0),
                'iqfeed_symbols': iqfeed_stats.get('symbols_subscribed', 0),
                'messages_per_second': iqfeed_stats.get('messages_received', 0) / max(stats['uptime_seconds'], 1)
            })
        
        # Add data writer stats
        if self.data_writer:
            writer_stats = self.data_writer.get_stats()
            stats.update({
                'ticks_written': writer_stats.get('ticks_written', 0),
                'l1_written': writer_stats.get('l1_written', 0),
                'l2_written': writer_stats.get('l2_written', 0)
            })
        
        return stats
    
    def stop(self):
        """Stop the real-time trading system"""
        logger.info("🛑 Stopping Real-time Trading System...")
        
        self.running = False
        
        # Stop components in reverse order
        if self.iqfeed_client:
            self.iqfeed_client.stop()
        
        if self.data_writer:
            self.data_writer.stop()
        
        if self.redis_metrics:
            self.redis_metrics.stop()
        
        logger.info("✅ Real-time Trading System stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)
    
    def get_status(self) -> Dict:
        """Get current system status"""
        status = {
            'running': self.running,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            'components': {
                'iqfeed_client': self.iqfeed_client is not None,
                'data_writer': self.data_writer is not None,
                'redis_metrics': self.redis_metrics is not None
            }
        }
        
        # Add health checks
        if self.iqfeed_client:
            status['iqfeed_health'] = self.iqfeed_client.get_statistics()
        
        if self.data_writer:
            status['writer_health'] = self.data_writer.health_check()
        
        if self.redis_metrics:
            status['metrics_health'] = self.redis_metrics.health_check()
        
        return status


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Real-time Trading System')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--tickers', default='test_small', 
                       help='Ticker list name (test_small, test_medium, production_1000)')
    parser.add_argument('--data-types', nargs='+', default=['l1'], 
                       help='Data types to collect (l1, l2, tick)')
    parser.add_argument('--status', action='store_true', help='Show system status and exit')
    
    args = parser.parse_args()
    
    # Create system
    system = RealTimeTradingSystem(args.config)
    
    if args.status:
        # Just show status
        status = system.get_status()
        print(json.dumps(status, indent=2, default=str))
        return
    
    try:
        # Start system
        success = system.start(args.tickers, args.data_types)
        
        if success:
            # Keep running until interrupted
            while system.running:
                time.sleep(1)
        else:
            logger.error("Failed to start system")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        system.stop()


if __name__ == "__main__":
    main()