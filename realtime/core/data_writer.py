#!/usr/bin/env python3
"""
Real-time Data Writer
- Writes tick, L1, and L2 data to files
- Maintains compatibility with historical data formats
- Handles high-frequency data streams
- Provides data rotation and compression
"""

import os
import csv
import json
import threading
import time
import gzip
import shutil
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
from dataclasses import asdict
import logging
import queue

logger = logging.getLogger(__name__)

class DataRotator:
    """Handles data file rotation and cleanup"""
    
    def __init__(self, retention_hours: int = 168):  # Default 1 week
        self.retention_hours = retention_hours
    
    def should_rotate(self, file_path: str) -> bool:
        """Check if file should be rotated based on age or size"""
        try:
            if not os.path.exists(file_path):
                return False
            
            # Check file age (rotate daily)
            file_time = datetime.fromtimestamp(os.path.getctime(file_path), tz=timezone.utc)
            current_time = datetime.now(timezone.utc)
            
            # Rotate if file is from a different day
            if file_time.date() != current_time.date():
                return True
            
            # Check file size (rotate if > 100MB)
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > 100:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking file rotation: {e}")
            return False
    
    def rotate_file(self, file_path: str) -> bool:
        """Rotate file by compressing and moving to archive"""
        try:
            if not os.path.exists(file_path):
                return False
            
            # Create archive directory
            archive_dir = os.path.join(os.path.dirname(file_path), 'archive')
            os.makedirs(archive_dir, exist_ok=True)
            
            # Generate archived filename with timestamp
            base_name = os.path.basename(file_path)
            name, ext = os.path.splitext(base_name)
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            archived_name = f"{name}_{timestamp}{ext}.gz"
            archived_path = os.path.join(archive_dir, archived_name)
            
            # Compress and move file
            with open(file_path, 'rb') as f_in:
                with gzip.open(archived_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original file
            os.remove(file_path)
            
            logger.info(f"Rotated file: {file_path} -> {archived_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error rotating file {file_path}: {e}")
            return False
    
    def cleanup_old_files(self, data_dir: str):
        """Clean up old archived files based on retention policy"""
        try:
            archive_dir = os.path.join(data_dir, 'archive')
            if not os.path.exists(archive_dir):
                return
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)
            
            for filename in os.listdir(archive_dir):
                file_path = os.path.join(archive_dir, filename)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path), tz=timezone.utc)
                
                if file_time < cutoff_time:
                    os.remove(file_path)
                    logger.info(f"Cleaned up old file: {file_path}")
                    
        except Exception as e:
            logger.error(f"Error cleaning up old files: {e}")


class RealTimeDataWriter:
    """
    High-performance data writer for real-time trading data
    Features:
    - Asynchronous writing to prevent blocking
    - File format compatibility with historical data
    - Automatic file rotation and cleanup
    - Buffer management for high-frequency data
    - Error recovery and data integrity
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.data_config = config.get('data_collection', {})
        
        # File paths
        self.base_dir = self.data_config.get('base_dir', '/tmp/realtime_data')
        self.tick_dir = os.path.join(self.base_dir, self.data_config.get('tick_dir', 'ticks'))
        self.l1_dir = os.path.join(self.base_dir, self.data_config.get('l1_dir', 'l1'))
        self.l2_dir = os.path.join(self.base_dir, self.data_config.get('l2_dir', 'l2'))
        
        # Create directories
        for directory in [self.base_dir, self.tick_dir, self.l1_dir, self.l2_dir]:
            os.makedirs(directory, exist_ok=True)
        
        # Buffer settings
        self.batch_size = self.data_config.get('batch_size', 1000)
        self.flush_interval = self.data_config.get('flush_interval_seconds', 5)
        
        # Data buffers (per symbol)
        self.tick_buffers = defaultdict(list)
        self.l1_buffers = defaultdict(list)
        self.l2_buffers = defaultdict(list)
        
        # File handles (per symbol per day)
        self.tick_files = {}
        self.l1_files = {}
        self.l2_files = {}
        
        # Writer queues for async processing
        self.write_queue = queue.Queue(maxsize=10000)
        
        # Threading
        self.writer_threads = []
        self.flush_thread = None
        self.running = False
        self.lock = threading.Lock()
        
        # Data rotation
        self.rotator = DataRotator(self.data_config.get('retention_hours', 168))
        
        # Statistics
        self.stats = {
            'ticks_written': 0,
            'l1_written': 0,
            'l2_written': 0,
            'files_rotated': 0,
            'write_errors': 0,
            'buffer_overflows': 0,
            'last_write_time': None
        }
    
    def start(self, num_writer_threads: int = 2):
        """Start data writing service"""
        if self.running:
            return
        
        self.running = True
        
        # Start writer threads
        for i in range(num_writer_threads):
            thread = threading.Thread(target=self._writer_worker, args=(i,), daemon=True)
            thread.start()
            self.writer_threads.append(thread)
        
        # Start flush thread
        self.flush_thread = threading.Thread(target=self._flush_worker, daemon=True)
        self.flush_thread.start()
        
        logger.info(f"✓ Data writer started with {num_writer_threads} writer threads")
    
    def stop(self):
        """Stop data writing service"""
        logger.info("Stopping data writer...")
        
        self.running = False
        
        # Wait for threads to finish
        for thread in self.writer_threads:
            thread.join(timeout=5)
        
        if self.flush_thread:
            self.flush_thread.join(timeout=5)
        
        # Flush remaining buffers
        self._flush_all_buffers()
        
        # Close all file handles
        self._close_all_files()
        
        logger.info("✓ Data writer stopped")
    
    def write_tick_data(self, tick_data):
        """Queue tick data for writing"""
        try:
            write_item = {
                'type': 'tick',
                'symbol': tick_data.symbol,
                'data': tick_data,
                'timestamp': datetime.now(timezone.utc)
            }
            
            if not self.write_queue.full():
                self.write_queue.put_nowait(write_item)
            else:
                self.stats['buffer_overflows'] += 1
                logger.warning("Write queue full - dropping tick data")
                
        except Exception as e:
            logger.error(f"Error queuing tick data: {e}")
            self.stats['write_errors'] += 1
    
    def write_l1_data(self, l1_data):
        """Queue L1 data for writing"""
        try:
            write_item = {
                'type': 'l1',
                'symbol': l1_data.symbol,
                'data': l1_data,
                'timestamp': datetime.now(timezone.utc)
            }
            
            if not self.write_queue.full():
                self.write_queue.put_nowait(write_item)
            else:
                self.stats['buffer_overflows'] += 1
                logger.warning("Write queue full - dropping L1 data")
                
        except Exception as e:
            logger.error(f"Error queuing L1 data: {e}")
            self.stats['write_errors'] += 1
    
    def write_l2_data(self, l2_data):
        """Queue L2 data for writing"""
        try:
            write_item = {
                'type': 'l2',
                'symbol': l2_data.symbol,
                'data': l2_data,
                'timestamp': datetime.now(timezone.utc)
            }
            
            if not self.write_queue.full():
                self.write_queue.put_nowait(write_item)
            else:
                self.stats['buffer_overflows'] += 1
                logger.warning("Write queue full - dropping L2 data")
                
        except Exception as e:
            logger.error(f"Error queuing L2 data: {e}")
            self.stats['write_errors'] += 1
    
    def _writer_worker(self, worker_id: int):
        """Background writer thread"""
        logger.info(f"Writer thread {worker_id} started")
        
        while self.running:
            try:
                # Get write item from queue
                try:
                    write_item = self.write_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process write item
                self._process_write_item(write_item)
                self.write_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in writer thread {worker_id}: {e}")
        
        logger.info(f"Writer thread {worker_id} stopped")
    
    def _process_write_item(self, write_item: Dict):
        """Process individual write item"""
        try:
            data_type = write_item['type']
            symbol = write_item['symbol']
            data = write_item['data']
            
            with self.lock:
                if data_type == 'tick':
                    self.tick_buffers[symbol].append(data)
                    if len(self.tick_buffers[symbol]) >= self.batch_size:
                        self._flush_tick_buffer(symbol)
                        
                elif data_type == 'l1':
                    self.l1_buffers[symbol].append(data)
                    if len(self.l1_buffers[symbol]) >= self.batch_size:
                        self._flush_l1_buffer(symbol)
                        
                elif data_type == 'l2':
                    self.l2_buffers[symbol].append(data)
                    if len(self.l2_buffers[symbol]) >= self.batch_size:
                        self._flush_l2_buffer(symbol)
            
            self.stats['last_write_time'] = datetime.now(timezone.utc)
            
        except Exception as e:
            logger.error(f"Error processing write item: {e}")
            self.stats['write_errors'] += 1
    
    def _flush_worker(self):
        """Background flush thread"""
        logger.info("Flush thread started")
        
        while self.running:
            try:
                time.sleep(self.flush_interval)
                
                if not self.running:
                    break
                
                # Flush all buffers periodically
                with self.lock:
                    self._flush_all_buffers_internal()
                
            except Exception as e:
                logger.error(f"Error in flush thread: {e}")
        
        logger.info("Flush thread stopped")
    
    def _flush_all_buffers_internal(self):
        """Flush all buffers (internal, assumes lock held)"""
        # Flush tick buffers
        for symbol in list(self.tick_buffers.keys()):
            if self.tick_buffers[symbol]:
                self._flush_tick_buffer(symbol)
        
        # Flush L1 buffers
        for symbol in list(self.l1_buffers.keys()):
            if self.l1_buffers[symbol]:
                self._flush_l1_buffer(symbol)
        
        # Flush L2 buffers
        for symbol in list(self.l2_buffers.keys()):
            if self.l2_buffers[symbol]:
                self._flush_l2_buffer(symbol)
    
    def _flush_all_buffers(self):
        """Flush all buffers (external call)"""
        with self.lock:
            self._flush_all_buffers_internal()
    
    def _flush_tick_buffer(self, symbol: str):
        """Flush tick buffer for a symbol"""
        try:
            if not self.tick_buffers[symbol]:
                return
            
            # Get or create file handle
            file_handle = self._get_tick_file_handle(symbol)
            
            # Write buffered data
            for tick_data in self.tick_buffers[symbol]:
                if hasattr(tick_data, '__dict__'):
                    data_dict = asdict(tick_data)
                else:
                    data_dict = tick_data
                
                # Write CSV format (compatible with historical data)
                row = [
                    data_dict.get('timestamp', ''),
                    data_dict.get('price', 0),
                    data_dict.get('size', 0),
                    data_dict.get('conditions', ''),
                    data_dict.get('system_timestamp', ''),
                    data_dict.get('iqfeed_latency_ms', 0),
                    data_dict.get('system_latency_ms', 0)
                ]
                file_handle['csv_writer'].writerow(row)
                
                # Also write JSON format
                file_handle['json_file'].write(json.dumps(data_dict) + '\n')
            
            # Update statistics
            self.stats['ticks_written'] += len(self.tick_buffers[symbol])
            
            # Clear buffer
            self.tick_buffers[symbol].clear()
            
            # Flush files
            file_handle['csv_file'].flush()
            file_handle['json_file'].flush()
            
        except Exception as e:
            logger.error(f"Error flushing tick buffer for {symbol}: {e}")
            self.stats['write_errors'] += 1
    
    def _flush_l1_buffer(self, symbol: str):
        """Flush L1 buffer for a symbol"""
        try:
            if not self.l1_buffers[symbol]:
                return
            
            # Get or create file handle
            file_handle = self._get_l1_file_handle(symbol)
            
            # Write buffered data
            for l1_data in self.l1_buffers[symbol]:
                if hasattr(l1_data, '__dict__'):
                    data_dict = asdict(l1_data)
                else:
                    data_dict = l1_data
                
                # Write CSV format
                row = [
                    data_dict.get('timestamp', ''),
                    data_dict.get('bid', 0),
                    data_dict.get('ask', 0),
                    data_dict.get('bid_size', 0),
                    data_dict.get('ask_size', 0),
                    data_dict.get('last_trade_price', 0),
                    data_dict.get('last_trade_size', 0),
                    data_dict.get('system_timestamp', ''),
                    data_dict.get('iqfeed_latency_ms', 0),
                    data_dict.get('system_latency_ms', 0)
                ]
                file_handle['csv_writer'].writerow(row)
                
                # Also write JSON format
                file_handle['json_file'].write(json.dumps(data_dict) + '\n')
            
            # Update statistics
            self.stats['l1_written'] += len(self.l1_buffers[symbol])
            
            # Clear buffer
            self.l1_buffers[symbol].clear()
            
            # Flush files
            file_handle['csv_file'].flush()
            file_handle['json_file'].flush()
            
        except Exception as e:
            logger.error(f"Error flushing L1 buffer for {symbol}: {e}")
            self.stats['write_errors'] += 1
    
    def _flush_l2_buffer(self, symbol: str):
        """Flush L2 buffer for a symbol"""
        try:
            if not self.l2_buffers[symbol]:
                return
            
            # Get or create file handle
            file_handle = self._get_l2_file_handle(symbol)
            
            # Write buffered data
            for l2_data in self.l2_buffers[symbol]:
                if hasattr(l2_data, '__dict__'):
                    data_dict = asdict(l2_data)
                else:
                    data_dict = l2_data
                
                # Write CSV format
                row = [
                    data_dict.get('timestamp', ''),
                    data_dict.get('side', ''),
                    data_dict.get('level', 0),
                    data_dict.get('price', 0),
                    data_dict.get('size', 0),
                    data_dict.get('market_maker', ''),
                    data_dict.get('system_timestamp', ''),
                    data_dict.get('iqfeed_latency_ms', 0),
                    data_dict.get('system_latency_ms', 0)
                ]
                file_handle['csv_writer'].writerow(row)
                
                # Also write JSON format
                file_handle['json_file'].write(json.dumps(data_dict) + '\n')
            
            # Update statistics
            self.stats['l2_written'] += len(self.l2_buffers[symbol])
            
            # Clear buffer
            self.l2_buffers[symbol].clear()
            
            # Flush files
            file_handle['csv_file'].flush()
            file_handle['json_file'].flush()
            
        except Exception as e:
            logger.error(f"Error flushing L2 buffer for {symbol}: {e}")
            self.stats['write_errors'] += 1
    
    def _get_tick_file_handle(self, symbol: str):
        """Get or create tick file handle for symbol"""
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_key = f"{symbol}_{date_str}"
        
        if file_key not in self.tick_files:
            # Create file paths
            csv_path = os.path.join(self.tick_dir, f"{symbol}_ticks_{date_str}.csv")
            json_path = os.path.join(self.tick_dir, f"{symbol}_ticks_{date_str}.jsonl")
            
            # Check if files need rotation
            if self.rotator.should_rotate(csv_path):
                self.rotator.rotate_file(csv_path)
                self.stats['files_rotated'] += 1
            
            if self.rotator.should_rotate(json_path):
                self.rotator.rotate_file(json_path)
                self.stats['files_rotated'] += 1
            
            # Open files
            csv_file = open(csv_path, 'a', newline='')
            json_file = open(json_path, 'a')
            
            csv_writer = csv.writer(csv_file)
            
            # Write headers if file is new
            if os.path.getsize(csv_path) == 0:
                csv_writer.writerow([
                    'timestamp', 'price', 'size', 'conditions', 
                    'system_timestamp', 'iqfeed_latency_ms', 'system_latency_ms'
                ])
            
            self.tick_files[file_key] = {
                'csv_file': csv_file,
                'json_file': json_file,
                'csv_writer': csv_writer
            }
        
        return self.tick_files[file_key]
    
    def _get_l1_file_handle(self, symbol: str):
        """Get or create L1 file handle for symbol"""
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_key = f"{symbol}_{date_str}"
        
        if file_key not in self.l1_files:
            # Create file paths
            csv_path = os.path.join(self.l1_dir, f"{symbol}_l1_{date_str}.csv")
            json_path = os.path.join(self.l1_dir, f"{symbol}_l1_{date_str}.jsonl")
            
            # Check rotation
            if self.rotator.should_rotate(csv_path):
                self.rotator.rotate_file(csv_path)
                self.stats['files_rotated'] += 1
            
            # Open files
            csv_file = open(csv_path, 'a', newline='')
            json_file = open(json_path, 'a')
            
            csv_writer = csv.writer(csv_file)
            
            # Write headers if file is new
            if os.path.getsize(csv_path) == 0:
                csv_writer.writerow([
                    'timestamp', 'bid', 'ask', 'bid_size', 'ask_size',
                    'last_trade_price', 'last_trade_size', 'system_timestamp',
                    'iqfeed_latency_ms', 'system_latency_ms'
                ])
            
            self.l1_files[file_key] = {
                'csv_file': csv_file,
                'json_file': json_file,
                'csv_writer': csv_writer
            }
        
        return self.l1_files[file_key]
    
    def _get_l2_file_handle(self, symbol: str):
        """Get or create L2 file handle for symbol"""
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_key = f"{symbol}_{date_str}"
        
        if file_key not in self.l2_files:
            # Create file paths
            csv_path = os.path.join(self.l2_dir, f"{symbol}_l2_{date_str}.csv")
            json_path = os.path.join(self.l2_dir, f"{symbol}_l2_{date_str}.jsonl")
            
            # Check rotation
            if self.rotator.should_rotate(csv_path):
                self.rotator.rotate_file(csv_path)
                self.stats['files_rotated'] += 1
            
            # Open files
            csv_file = open(csv_path, 'a', newline='')
            json_file = open(json_path, 'a')
            
            csv_writer = csv.writer(csv_file)
            
            # Write headers if file is new
            if os.path.getsize(csv_path) == 0:
                csv_writer.writerow([
                    'timestamp', 'side', 'level', 'price', 'size', 'market_maker',
                    'system_timestamp', 'iqfeed_latency_ms', 'system_latency_ms'
                ])
            
            self.l2_files[file_key] = {
                'csv_file': csv_file,
                'json_file': json_file,
                'csv_writer': csv_writer
            }
        
        return self.l2_files[file_key]
    
    def _close_all_files(self):
        """Close all open file handles"""
        try:
            # Close tick files
            for file_handle in self.tick_files.values():
                file_handle['csv_file'].close()
                file_handle['json_file'].close()
            self.tick_files.clear()
            
            # Close L1 files
            for file_handle in self.l1_files.values():
                file_handle['csv_file'].close()
                file_handle['json_file'].close()
            self.l1_files.clear()
            
            # Close L2 files
            for file_handle in self.l2_files.values():
                file_handle['csv_file'].close()
                file_handle['json_file'].close()
            self.l2_files.clear()
            
            logger.info("All file handles closed")
            
        except Exception as e:
            logger.error(f"Error closing file handles: {e}")
    
    def get_stats(self) -> Dict:
        """Get current writer statistics"""
        with self.lock:
            return {
                **self.stats.copy(),
                'buffer_sizes': {
                    'tick_buffers': {symbol: len(buffer) for symbol, buffer in self.tick_buffers.items()},
                    'l1_buffers': {symbol: len(buffer) for symbol, buffer in self.l1_buffers.items()},
                    'l2_buffers': {symbol: len(buffer) for symbol, buffer in self.l2_buffers.items()}
                },
                'queue_size': self.write_queue.qsize(),
                'open_files': {
                    'tick_files': len(self.tick_files),
                    'l1_files': len(self.l1_files),
                    'l2_files': len(self.l2_files)
                }
            }
    
    def health_check(self) -> Dict[str, any]:
        """Perform data writer health check"""
        
        health_status = {
            'status': 'healthy',
            'queue_utilization_percent': (self.write_queue.qsize() / self.write_queue.maxsize) * 100,
            'buffer_overflow_count': self.stats['buffer_overflows'],
            'write_error_count': self.stats['write_errors']
        }
        
        # Check queue utilization
        if health_status['queue_utilization_percent'] > 90:
            health_status['status'] = 'critical'
        elif health_status['queue_utilization_percent'] > 70:
            health_status['status'] = 'warning'
        
        # Check for errors
        if self.stats['write_errors'] > 10:
            health_status['status'] = 'critical'
        elif self.stats['write_errors'] > 5:
            health_status['status'] = 'warning'
        
        return health_status