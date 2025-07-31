#!/usr/bin/env python3
"""
Django Management Command for Redis-Based Production Monitoring
==============================================================

Continuously updates Redis with fresh monitoring data for real-time
dashboard updates without WebSockets.

Usage:
    python manage.py run_redis_monitor

Features:
- Continuous monitoring data collection
- Redis-based real-time updates
- Alert generation and escalation
- Performance metrics caching
- System health tracking
"""

import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from monitor.alert_manager import get_alert_manager
from monitor.services import HedgeFundProductionMonitor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run Redis-based production monitoring (no WebSockets)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Update interval in seconds (default: 5)'
        )
        parser.add_argument(
            '--cleanup-interval',
            type=int,
            default=3600,
            help='Cleanup interval in seconds (default: 3600 = 1 hour)'
        )
    
    def handle(self, *args, **options):
        """Main monitoring loop."""
        update_interval = options['interval']
        cleanup_interval = options['cleanup_interval']
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Starting Redis-based production monitor (interval: {update_interval}s)'
            )
        )
        
        # Initialize components
        alert_manager = get_alert_manager()
        monitor = HedgeFundProductionMonitor()
        
        last_cleanup = time.time()
        
        try:
            while True:
                start_time = time.time()
                
                try:
                    # Generate and store alerts in Redis
                    alerts = alert_manager.generate_and_store_alerts()
                    
                    # Store system metrics in Redis
                    system_metrics = monitor.get_system_metrics()
                    alert_manager.store_system_metrics(system_metrics)
                    
                    # Process any pending notifications
                    notifications = alert_manager.process_notifications()
                    
                    # Log status
                    current_time = timezone.now()
                    self.stdout.write(
                        f'[{current_time.strftime("%Y-%m-%d %H:%M:%S")}] '
                        f'Updated: {len(alerts)} alerts, '
                        f'{len(notifications)} notifications processed'
                    )
                    
                    # Periodic cleanup
                    if time.time() - last_cleanup > cleanup_interval:
                        alert_manager.cleanup_old_data()
                        last_cleanup = time.time()
                        self.stdout.write(
                            self.style.WARNING('Performed Redis cleanup')
                        )
                
                except Exception as e:
                    logger.error(f"Monitoring loop error: {e}")
                    self.stdout.write(
                        self.style.ERROR(f'Error: {str(e)}')
                    )
                
                # Sleep for remaining interval
                elapsed = time.time() - start_time
                sleep_time = max(0, update_interval - elapsed)
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.SUCCESS('Stopping Redis monitor...')
            )
        except Exception as e:
            logger.error(f"Critical monitoring error: {e}")
            self.stdout.write(
                self.style.ERROR(f'Critical error: {str(e)}')
            )
        finally:
            self.stdout.write(
                self.style.SUCCESS('Redis monitor stopped')
            )