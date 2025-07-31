#!/usr/bin/env python3
"""
Add lag tracking to IQFeed client and Kafka producer.

This script modifies the existing code to capture reception timestamps
and calculate lag metrics for monitoring latency.
"""

import os
import re

def add_lag_tracking_to_iqfeed_client():
    """Add reception timestamp tracking to IQFeed client."""
    
    file_path = 'ingestion/iqfeed_client.py'
    
    # Read the current file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check if already modified
    if 'reception_timestamp' in content:
        print(f"✓ {file_path} already has lag tracking")
        return
    
    # Find the _process_message method and add timestamp capture
    pattern = r'(def _process_message\(self, message: str\):\s*\n\s*""".*?"""\s*\n\s*try:)'
    replacement = r'\1\n            # Capture reception timestamp for lag analysis\n            reception_timestamp = datetime.now(timezone.utc)'
    
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Add timezone import if not present
    if 'from datetime import datetime, timezone' not in content:
        content = content.replace(
            'from datetime import datetime, timedelta',
            'from datetime import datetime, timedelta, timezone'
        )
    
    # Add timestamp to parsed messages
    pattern = r'(if parsed_message:\s*\n\s*# Check sequence integrity)'
    replacement = r'''if parsed_message:
                # Add reception timestamp for lag tracking
                parsed_message['_timestamps'] = {
                    'reception': reception_timestamp.isoformat(),
                    'iqfeed': parsed_message.get('timestamp'),  # Exchange timestamp
                }
                
                # Check sequence integrity'''
    
    content = re.sub(pattern, replacement, content)
    
    # Write the modified file
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Added lag tracking to {file_path}")


def add_lag_tracking_to_kafka_producer():
    """Add lag calculation to Kafka producer."""
    
    file_path = 'ingestion/kafka_producer.py'
    
    # Read the current file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check if already modified
    if 'lag_ms' in content:
        print(f"✓ {file_path} already has lag tracking")
        return
    
    # Add lag calculation function
    lag_calc_function = '''
def _calculate_lag_ms(start_time_str: str, end_time_str: str) -> Optional[float]:
    """Calculate lag in milliseconds between two ISO timestamps."""
    try:
        if not start_time_str or not end_time_str:
            return None
            
        # Parse ISO format timestamps
        if isinstance(start_time_str, str):
            start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        else:
            start = start_time_str
            
        if isinstance(end_time_str, str):
            end = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
        else:
            end = end_time_str
            
        # Calculate difference in milliseconds
        delta = (end - start).total_seconds() * 1000
        return round(delta, 2)
    except Exception:
        return None
'''
    
    # Insert the function before the class definition
    pattern = r'(class IQFeedKafkaProducer:)'
    replacement = lag_calc_function + '\n\n\1'
    content = re.sub(pattern, replacement, content)
    
    # Modify _enrich_message to include lag tracking
    pattern = r"(enriched\['_metadata'\] = \{[^}]+)'schema_version': '1\.0'\s*\}"
    replacement = r"\1'schema_version': '1.0',\n            # Lag tracking metrics\n            'lag_ms': self._get_lag_metrics(message, datetime.now(timezone.utc))\n        }"
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Add the lag metrics calculation method
    lag_metrics_method = '''
    def _get_lag_metrics(self, message: Dict[str, Any], now: datetime) -> Dict[str, Optional[float]]:
        """Calculate lag metrics for the message."""
        lag_metrics = {
            'network': None,
            'processing': None,
            'total': None
        }
        
        timestamps = message.get('_timestamps', {})
        if not timestamps:
            return lag_metrics
            
        # Network lag: IQFeed timestamp to reception
        if 'iqfeed' in timestamps and 'reception' in timestamps:
            lag_metrics['network'] = _calculate_lag_ms(
                timestamps['iqfeed'], 
                timestamps['reception']
            )
        
        # Processing lag: Reception to now (Kafka publish)
        if 'reception' in timestamps:
            lag_metrics['processing'] = _calculate_lag_ms(
                timestamps['reception'],
                now.isoformat()
            )
        
        # Total lag: IQFeed timestamp to Kafka publish
        if 'iqfeed' in timestamps:
            lag_metrics['total'] = _calculate_lag_ms(
                timestamps['iqfeed'],
                now.isoformat()
            )
            
        return lag_metrics
'''
    
    # Insert the method after _enrich_message
    pattern = r'(def _enrich_message.*?return enriched\n)'
    replacement = r'\1' + lag_metrics_method
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Write the modified file
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Added lag tracking to {file_path}")


def create_lag_monitor():
    """Create a lag monitoring script."""
    
    monitor_script = '''#!/usr/bin/env python3
"""
Monitor IQFeed to Kafka lag metrics in real-time.

This script connects to Kafka and monitors lag metrics from the
enriched messages to detect latency issues.
"""

import json
import signal
import sys
from datetime import datetime
from collections import defaultdict
from kafka import KafkaConsumer
import numpy as np

class LagMonitor:
    def __init__(self, bootstrap_servers='localhost:9092'):
        self.consumer = KafkaConsumer(
            'l2_order_book', 'trades', 'quotes',
            bootstrap_servers=bootstrap_servers,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            auto_offset_reset='latest',
            enable_auto_commit=True
        )
        
        self.lag_stats = defaultdict(lambda: {
            'network': [],
            'processing': [],
            'total': []
        })
        
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, sig, frame):
        print("\\nShutting down lag monitor...")
        self.running = False
        sys.exit(0)
    
    def monitor(self):
        """Monitor lag metrics from Kafka messages."""
        print("Monitoring lag metrics... (Press Ctrl+C to stop)")
        print("-" * 80)
        
        message_count = 0
        last_report_time = datetime.now()
        
        for message in self.consumer:
            if not self.running:
                break
                
            try:
                data = message.value
                metadata = data.get('_metadata', {})
                lag_ms = metadata.get('lag_ms', {})
                
                if lag_ms:
                    symbol = data.get('symbol', 'unknown')
                    
                    # Collect lag metrics
                    for lag_type in ['network', 'processing', 'total']:
                        if lag_ms.get(lag_type) is not None:
                            self.lag_stats[symbol][lag_type].append(lag_ms[lag_type])
                            # Keep only last 1000 samples
                            if len(self.lag_stats[symbol][lag_type]) > 1000:
                                self.lag_stats[symbol][lag_type] = self.lag_stats[symbol][lag_type][-1000:]
                
                message_count += 1
                
                # Report every 5 seconds
                if (datetime.now() - last_report_time).total_seconds() >= 5:
                    self._print_report(message_count)
                    last_report_time = datetime.now()
                    
            except Exception as e:
                print(f"Error processing message: {e}")
    
    def _print_report(self, total_messages):
        """Print lag statistics report."""
        print(f"\\n[{datetime.now().strftime('%H:%M:%S')}] Processed {total_messages} messages")
        print("-" * 80)
        print(f"{'Symbol':<10} {'Metric':<12} {'Avg (ms)':<12} {'P50 (ms)':<12} {'P95 (ms)':<12} {'Max (ms)':<12}")
        print("-" * 80)
        
        # Sort symbols by total lag
        sorted_symbols = sorted(
            self.lag_stats.keys(),
            key=lambda s: np.mean(self.lag_stats[s]['total']) if self.lag_stats[s]['total'] else 0,
            reverse=True
        )[:10]  # Top 10 symbols
        
        for symbol in sorted_symbols:
            stats = self.lag_stats[symbol]
            
            for lag_type in ['network', 'processing', 'total']:
                values = stats[lag_type]
                if values:
                    avg = np.mean(values)
                    p50 = np.percentile(values, 50)
                    p95 = np.percentile(values, 95)
                    max_val = np.max(values)
                    
                    # Highlight high latency
                    highlight = ''
                    if lag_type == 'total' and p95 > 100:
                        highlight = ' ⚠️'
                    elif lag_type == 'total' and p95 > 50:
                        highlight = ' ⚡'
                    
                    print(f"{symbol:<10} {lag_type:<12} {avg:>10.1f} {p50:>12.1f} {p95:>12.1f} {max_val:>12.1f}{highlight}")
            
            print("-" * 80)

if __name__ == '__main__':
    monitor = LagMonitor()
    monitor.monitor()
'''
    
    with open('monitor_lag.py', 'w') as f:
        f.write(monitor_script)
    
    os.chmod('monitor_lag.py', 0o755)
    print("✅ Created lag monitoring script: monitor_lag.py")


if __name__ == '__main__':
    print("Adding lag tracking to IQFeed pipeline...")
    print("=" * 60)
    
    # Add lag tracking to both components
    add_lag_tracking_to_iqfeed_client()
    add_lag_tracking_to_kafka_producer()
    create_lag_monitor()
    
    print("=" * 60)
    print("✅ Lag tracking implementation complete!")
    print("\nTo monitor lag in real-time, run:")
    print("  python monitor_lag.py")