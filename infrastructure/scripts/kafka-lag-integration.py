#!/usr/bin/env python3
"""
Minimal Kafka Lag Integration Helper
Demonstrates how to integrate kafka_lag_monitor.py with production health monitoring
"""

import sys
import json
import subprocess
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from kafka_lag_monitor import KafkaLagMonitor


def get_kafka_lag_summary():
    """
    Get Kafka consumer lag summary in a format suitable for health monitoring.
    
    Returns:
        dict: Lag summary with total lag, consumer groups, and alerts
    """
    try:
        # Initialize monitor with default thresholds
        monitor = KafkaLagMonitor(
            bootstrap_servers="localhost:9092",
            lag_warning_threshold=1000,
            lag_critical_threshold=10000
        )
        
        # Get lag information
        results = monitor.check_all_groups()
        
        # Extract key metrics for health monitoring
        summary = {
            'total_lag': 0,
            'consumer_groups': {},
            'has_warnings': False,
            'has_critical': False,
            'alert_count': len(results.get('alerts', []))
        }
        
        # Calculate total lag across all groups
        for group_id, group_info in results.get('groups', {}).items():
            group_lag = group_info.get('total_lag', 0)
            summary['total_lag'] += group_lag
            summary['consumer_groups'][group_id] = group_lag
        
        # Check alert levels
        for alert in results.get('alerts', []):
            if alert['level'] == 'CRITICAL':
                summary['has_critical'] = True
            elif alert['level'] == 'WARNING':
                summary['has_warnings'] = True
        
        return summary
        
    except Exception as e:
        return {
            'error': str(e),
            'total_lag': -1,
            'consumer_groups': {},
            'has_warnings': True,
            'has_critical': False
        }


def update_production_health_monitor_kafka_check():
    """
    Example of how to update the production health monitor's Kafka check.
    This shows the minimal change needed to use the dedicated lag monitor.
    """
    
    # This would replace the simplified _check_kafka_consumer_lag method
    # in production_health_monitor.py around line 472
    
    example_code = '''
    def _check_kafka_consumer_lag(self) -> int:
        """Check Kafka consumer lag using dedicated monitor."""
        try:
            # Use the dedicated Kafka lag monitor
            from kafka_lag_monitor import KafkaLagMonitor
            
            monitor = KafkaLagMonitor(
                bootstrap_servers=self.config['kafka']['bootstrap_servers'],
                lag_warning_threshold=10000,
                lag_critical_threshold=50000
            )
            
            # Get lag information
            results = monitor.check_all_groups()
            
            # Calculate total lag
            total_lag = 0
            for group_info in results.get('groups', {}).values():
                total_lag += group_info.get('total_lag', 0)
            
            return total_lag
            
        except Exception as e:
            self.logger.error(f"Error checking Kafka lag: {e}")
            return 0
    '''
    
    return example_code


def main():
    """Demonstrate Kafka lag integration."""
    
    print("=== Kafka Lag Integration Demo ===")
    print()
    
    # Get current lag summary
    print("Getting current Kafka lag summary...")
    summary = get_kafka_lag_summary()
    
    if 'error' in summary:
        print(f"Error: {summary['error']}")
    else:
        print(f"Total Lag: {summary['total_lag']:,} messages")
        print(f"Consumer Groups: {len(summary['consumer_groups'])}")
        print(f"Has Warnings: {summary['has_warnings']}")
        print(f"Has Critical: {summary['has_critical']}")
        print(f"Alert Count: {summary['alert_count']}")
        
        if summary['consumer_groups']:
            print("\nPer-Group Lag:")
            for group, lag in summary['consumer_groups'].items():
                status = "🔥" if lag > 10000 else ("⚠️" if lag > 1000 else "✅")
                print(f"  {status} {group}: {lag:,}")
    
    print("\n=== Integration Instructions ===")
    print("1. The kafka_lag_monitor.py is already a complete solution")
    print("2. It can be run standalone or imported as a module")
    print("3. The production_health_monitor.py can use it directly")
    print("4. No additional infrastructure or complexity needed")
    
    print("\n=== Example Usage ===")
    print("Standalone monitoring:")
    print("  python kafka_lag_monitor.py --continuous")
    print("\nOne-time check:")
    print("  python kafka_lag_monitor.py --json")
    print("\nFrom Python code:")
    print("  from kafka_lag_monitor import KafkaLagMonitor")
    print("  monitor = KafkaLagMonitor()")
    print("  results = monitor.check_all_groups()")


if __name__ == "__main__":
    main()