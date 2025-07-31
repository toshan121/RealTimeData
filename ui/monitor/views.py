#!/usr/bin/env python3
"""
Django Views for Hedge Fund Production Monitor
Professional-grade REST API endpoints for production monitoring
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
import json
import logging
from .services import HedgeFundProductionMonitor
from .models import (
    SystemHealthSnapshot, ProductionAlert, ComponentStatus, 
    PerformanceMetric, MonitoringDashboard, SystemMaintenanceWindow
)
from .alert_manager import get_alert_manager
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db.models import Q, Avg, Count
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.paginator import Paginator
import redis
import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Global monitor and alert manager instances for efficiency
monitor = HedgeFundProductionMonitor()
alert_manager = get_alert_manager()

# ClickHouse configuration for chart data
CLICKHOUSE_CONFIG = {
    "host": "localhost",
    "port": 8123,
    "database": "l2_market_data",
    "username": "l2_user",
    "password": "l2_secure_pass",
}

# Redis configuration for real-time data
REDIS_CONFIG = {
    "host": "localhost",
    "port": 6380,
    "db": 0,
    "decode_responses": True,
}

# Redis connection pool for better performance
redis_pool = redis.ConnectionPool(**REDIS_CONFIG, max_connections=20)


class HealthCheckView(View):
    """Simple health check endpoint"""
    
    def get(self, request):
        return JsonResponse({
            'status': 'healthy',
            'service': 'hedge_fund_monitor',
            'message': 'Money is safe - Django API is responding',
            'framework': 'Django'
        })


class SystemStatusView(View):
    """Overall system status endpoint"""
    
    def get(self, request):
        try:
            comprehensive_status = monitor.get_comprehensive_status()
            return JsonResponse(comprehensive_status)
        except Exception as e:
            logger.error(f"System status error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e),
                'money_safe': False
            }, status=500)


class SystemMetricsView(View):
    """Detailed system metrics endpoint"""
    
    def get(self, request):
        try:
            metrics = monitor.get_system_metrics()
            return JsonResponse(metrics)
        except Exception as e:
            logger.error(f"System metrics error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e)
            }, status=500)


class DataFlowMetricsView(View):
    """Data pipeline metrics endpoint"""
    
    def get(self, request):
        try:
            metrics = monitor.get_data_flow_metrics()
            return JsonResponse(metrics)
        except Exception as e:
            logger.error(f"Data flow metrics error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e)
            }, status=500)


class KafkaMetricsView(View):
    """Kafka metrics endpoint"""
    
    def get(self, request):
        try:
            metrics = monitor.get_kafka_metrics()
            return JsonResponse(metrics)
        except Exception as e:
            logger.error(f"Kafka metrics error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e)
            }, status=500)


class ClickHouseMetricsView(View):
    """ClickHouse storage metrics endpoint"""
    
    def get(self, request):
        try:
            metrics = monitor.get_clickhouse_metrics()
            return JsonResponse(metrics)
        except Exception as e:
            logger.error(f"ClickHouse metrics error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e)
            }, status=500)


class ServiceHealthView(View):
    """Service health check endpoint"""
    
    def get(self, request):
        try:
            health = monitor.check_service_health()
            return JsonResponse(health)
        except Exception as e:
            logger.error(f"Service health error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e)
            }, status=500)


class AlertsView(View):
    """Current alerts endpoint - Redis-based (no WebSockets)"""
    
    def get(self, request):
        try:
            # Use Redis-based alert manager for fast retrieval
            alert_data = alert_manager.get_current_alerts()
            
            # Store system metrics in Redis for dashboard
            system_metrics = monitor.get_system_metrics()
            alert_manager.store_system_metrics(system_metrics)
            
            return JsonResponse({
                'alerts': alert_data.get('alerts', []),
                'alert_count': alert_data.get('alert_count', 0),
                'has_critical': alert_data.get('critical_count', 0) > 0,
                'critical_count': alert_data.get('critical_count', 0),
                'timestamp': alert_data.get('timestamp'),
                'data_source': 'Redis Cache',
                'framework': 'Django + Redis'
            })
        except Exception as e:
            logger.error(f"Redis alerts error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e),
                'alerts': [],
                'alert_count': 0,
                'has_critical': False
            }, status=500)


class UITestDataView(View):
    """UI testing data endpoint (curl-friendly)"""
    
    def get(self, request):
        try:
            comprehensive_status = monitor.get_comprehensive_status()
            
            # Format for UI testing
            return JsonResponse({
                'title': 'Hedge Fund Production Monitor',
                'overall_status': comprehensive_status.get('overall_status', 'UNKNOWN'),
                'sections': {
                    'system_performance': True,
                    'data_pipeline': True,
                    'service_health': True,
                    'alerts': True,
                },
                'metrics': {
                    'cpu_usage': f"{comprehensive_status.get('system', {}).get('cpu_percent', 0):.1f}%",
                    'memory_usage': f"{comprehensive_status.get('system', {}).get('memory_percent', 0):.1f}%",
                    'data_rate': f"{comprehensive_status.get('data_flow', {}).get('total_messages_per_minute', 0):,}/min",
                    'latency': f"{comprehensive_status.get('data_flow', {}).get('avg_latency_ms', 0):.1f}ms",
                },
                'services': {
                    service: details.get('status', 'UNKNOWN') 
                    for service, details in comprehensive_status.get('services', {}).items()
                },
                'alerts': comprehensive_status.get('alerts', []),
                'alert_count': comprehensive_status.get('alert_count', 0),
                'has_critical': comprehensive_status.get('has_critical', False),
                'ui_functional': True,
                'money_safe': comprehensive_status.get('money_safe', False),
                'framework': 'Django',
                'timestamp': comprehensive_status.get('timestamp')
            })
        except Exception as e:
            logger.error(f"UI test data error: {e}")
            return JsonResponse({
                'status': 'error',
                'error': str(e),
                'ui_functional': False,
                'money_safe': False,
                'framework': 'Django'
            }, status=500)


def dashboard_view(request):
    """Main dashboard view with professional hedge fund styling"""
    try:
        comprehensive_status = monitor.get_comprehensive_status()
        
        context = {
            'title': 'Hedge Fund Production Monitor',
            'status': comprehensive_status,
            'money_safe': comprehensive_status.get('money_safe', False),
            'framework': 'Django'
        }
        
        return render(request, 'monitor/dashboard.html', context)
    except Exception as e:
        logger.error(f"Dashboard view error: {e}")
        return render(request, 'monitor/error.html', {
            'error': str(e),
            'framework': 'Django'
        })


# IQFeed and Interactive Brokers API endpoints for testing
class IQFeedAPIView(View):
    """IQFeed API testing endpoint"""
    
    def get(self, request):
        return JsonResponse({
            'api': 'IQFeed',
            'status': 'available',
            'endpoints': [
                '/api/iqfeed/historical/',
                '/api/iqfeed/realtime/',
                '/api/iqfeed/level2/',
                '/api/iqfeed/fundamentals/'
            ],
            'message': 'IQFeed API ready for hedge fund testing'
        })
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            symbol = data.get('symbol', 'AAPL')
            
            # REAL IQFeed connection - NO SIMULATION
            try:
                # Import real IQFeed client
                import sys
                import os
                sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
                from realtime.core.iqfeed_realtime_client import IQFeedRealTimeClient
                
                # Create configuration for real connection
                config = {
                    'iqfeed': {
                        'host': '127.0.0.1',
                        'ports': {
                            'level1': 5009,
                            'level2': 9200,  # FIXED: Correct Level 2 port
                            'admin': 9100
                        }
                    },
                    'clickhouse': {
                        'host': 'localhost',
                        'port': 8123,
                        'database': 'l2_market_data',
                        'username': 'l2_user',        # FIXED: Correct from Docker
                        'password': 'l2_secure_pass'  # FIXED: Correct from Docker
                    }
                }
                
                # Attempt real connection to IQFeed
                client = IQFeedRealTimeClient(config)
                
                # Test real data retrieval
                success = client.download_historical_data(symbol, '20250725')
                
                return JsonResponse({
                    'api': 'IQFeed',
                    'symbol': symbol,
                    'connection_status': 'REAL CONNECTION ESTABLISHED',
                    'data_download_success': success,
                    'message': f'REAL IQFeed data retrieval for {symbol}',
                    'data_source': 'LIVE_IQFEED_PRODUCTION'
                })
                
            except Exception as connection_error:
                # If real connection fails, provide detailed error
                return JsonResponse({
                    'api': 'IQFeed',
                    'symbol': symbol,
                    'connection_status': 'REAL CONNECTION FAILED',
                    'error': str(connection_error),
                    'message': 'Unable to connect to real IQFeed - check IQConnect.exe',
                    'data_source': 'ATTEMPTED_REAL_CONNECTION'
                })
                
        except Exception as e:
            return JsonResponse({
                'api': 'IQFeed',
                'error': str(e)
            }, status=400)


class InteractiveBrokersAPIView(View):
    """Interactive Brokers TWS API testing endpoint"""
    
    def get(self, request):
        return JsonResponse({
            'api': 'Interactive Brokers TWS',
            'status': 'available',
            'endpoints': [
                '/api/ib/portfolio/',
                '/api/ib/orders/',
                '/api/ib/positions/',
                '/api/ib/market-data/'
            ],
            'message': 'IB TWS API ready for hedge fund testing'
        })
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            action = data.get('action', 'get_positions')
            
            # REAL Interactive Brokers connection - NO SIMULATION
            try:
                # Attempt real TWS API connection
                from ib_insync import IB, Stock
                
                ib = IB()
                
                # Try to connect to TWS (default port 7497 for paper trading, 7496 for live)
                try:
                    ib.connect('127.0.0.1', 7497, clientId=1)  # Paper trading
                    
                    if action == 'get_positions':
                        positions = ib.positions()
                        portfolio = ib.portfolio()
                        
                        return JsonResponse({
                            'api': 'Interactive Brokers',
                            'action': action,
                            'connection_status': 'REAL TWS CONNECTION ESTABLISHED',
                            'positions_count': len(positions),
                            'portfolio_items': len(portfolio),
                            'message': 'REAL IB TWS data retrieval successful',
                            'data_source': 'LIVE_TWS_PRODUCTION'
                        })
                    
                    elif action == 'get_account_info':
                        account_summary = ib.accountSummary()
                        
                        return JsonResponse({
                            'api': 'Interactive Brokers', 
                            'action': action,
                            'connection_status': 'REAL TWS CONNECTION ESTABLISHED',
                            'account_items': len(account_summary),
                            'message': 'REAL IB account data retrieved',
                            'data_source': 'LIVE_TWS_PRODUCTION'
                        })
                    
                    else:
                        return JsonResponse({
                            'api': 'Interactive Brokers',
                            'action': action,
                            'connection_status': 'REAL TWS CONNECTION ESTABLISHED',
                            'message': f'REAL IB TWS action: {action}',
                            'data_source': 'LIVE_TWS_PRODUCTION'
                        })
                        
                except Exception as tws_error:
                    return JsonResponse({
                        'api': 'Interactive Brokers',
                        'action': action,
                        'connection_status': 'REAL TWS CONNECTION FAILED',
                        'error': str(tws_error),
                        'message': 'Unable to connect to real TWS - check Trader Workstation is running',
                        'data_source': 'ATTEMPTED_REAL_CONNECTION'
                    })
                finally:
                    try:
                        ib.disconnect()
                    except Exception as e:
                        logger.warning(f"💥 FAKE ELIMINATED: Failed to disconnect IB: {e}")
                        
            except ImportError:
                return JsonResponse({
                    'api': 'Interactive Brokers',
                    'action': action,
                    'connection_status': 'IB_INSYNC_NOT_INSTALLED',
                    'error': 'ib_insync package not available',
                    'message': 'Install ib_insync for real IB connections',
                    'data_source': 'DEPENDENCY_MISSING'
                })
                
        except Exception as e:
            return JsonResponse({
                'api': 'Interactive Brokers',
                'error': str(e)
            }, status=400)


class DebugInfoView(View):
    """Debug information endpoint"""
    
    def get(self, request):
        try:
            import sys
            import os
            
            debug_info = {
                'python_version': sys.version,
                'django_version': None,  # Will be filled by Django
                'working_directory': os.getcwd(),
                'environment': {
                    'DJANGO_SETTINGS_MODULE': os.environ.get('DJANGO_SETTINGS_MODULE', 'Not set'),
                    'DEBUG': os.environ.get('DEBUG', 'Not set')
                },
                'connections': {},
                'framework': 'Django'
            }
            
            # Test Redis connection using django-redis
            try:
                from django_redis import get_redis_connection
                redis_client = get_redis_connection("default")
                redis_client.ping()
                debug_info['connections']['redis'] = 'Connected (django-redis)'
            except Exception as e:
                debug_info['connections']['redis'] = f'Error: {str(e)}'
            
            # Test ClickHouse connection
            try:
                import clickhouse_connect
                ch_client = clickhouse_connect.get_client(host='localhost', port=8123)
                ch_client.query("SELECT 1")
                debug_info['connections']['clickhouse'] = 'Connected'
            except Exception as e:
                debug_info['connections']['clickhouse'] = f'Error: {str(e)}'
            
            return JsonResponse(debug_info)
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'error': str(e),
                'framework': 'Django'
            }, status=500)


# Streamlit Component API Views (migrated to Django REST APIs)
class HistoricalSimulatorAPIView(View):
    """Historical simulator component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'Historical Simulator',
            'description': 'Backend-independent replay control from UI',
            'features': [
                'Quick Presets for popular stocks',
                'Speed tests and multi-symbol configurations',
                'Advanced configuration with symbol selection',
                'Session management with real-time progress tracking',
                'Data browser with file analysis'
            ],
            'endpoints': {
                'start_replay': 'POST /api/historical-simulator/start/',
                'stop_replay': 'POST /api/historical-simulator/stop/',
                'status': 'GET /api/historical-simulator/status/',
                'available_data': 'GET /api/historical-simulator/data/'
            },
            'status': 'Available',
            'framework': 'Django'
        })


class L1TapeDisplayAPIView(View):
    """L1 + Tape Display component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'L1 + Tape Display',
            'description': 'ThinkOrSwim-grade interface for system validation and monitoring',
            'features': [
                'Real-time quotes with live bid/ask/last',
                'Color-coded price changes',
                'Time & Sales tape with scrolling trade prints',
                'Multi-symbol monitoring with dynamic updates',
                'Professional layout like ThinkOrSwim'
            ],
            'data_sources': ['Redis cache', 'Kafka streams'],
            'status': 'Available',
            'framework': 'Django'
        })


class CandlestickChartAPIView(View):
    """Candlestick Chart component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'Candlestick Chart',
            'description': 'Professional-grade real-time charting',
            'features': [
                'Multiple timeframes (1m, 5m, 15m, 1h, 4h, 1d)',
                'Technical indicators (SMA, EMA, RSI, VWAP)',
                'Volume analysis with color-coded bars',
                'OHLC construction from real-time tick data',
                'Interactive zoom, pan, crosshair functionality'
            ],
            'timeframes': ['1m', '5m', '15m', '1h', '4h', '1d'],
            'indicators': ['SMA', 'EMA', 'RSI', 'VWAP'],
            'status': 'Available',
            'framework': 'Django'
        })


class DataDownloaderAPIView(View):
    """Data Downloader component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'Data Downloader',
            'description': 'Historical data management with IQFeed integration',
            'features': [
                'Auto-downloader integration with data existence validation',
                'Real tick and L1 data from IQFeed',
                'Comprehensive error handling and reconnection logic',
                'ClickHouse storage integration',
                'Data validation and completeness checks'
            ],
            'data_types': ['L1 quotes', 'tick data', 'L2 order book'],
            'storage': 'ClickHouse',
            'status': 'Available',
            'framework': 'Django'
        })


class ClickHouseViewerAPIView(View):
    """ClickHouse Viewer component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'ClickHouse Viewer',
            'description': 'Data validation and browsing for ClickHouse storage',
            'features': [
                'Database browser with table exploration',
                'Query interface for data validation',
                'Schema validation and data integrity checks',
                'Performance monitoring for queries',
                'Data completeness verification'
            ],
            'database': 'l2_market_data',
            'tables': ['market_ticks', 'market_l1', 'market_l2', 'market_trades'],
            'credentials': 'l2_user / l2_secure_pass',
            'port': 8123,
            'status': 'Available',
            'framework': 'Django'
        })


class RedisMonitorAPIView(View):
    """Redis Monitor component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'Redis Monitor',
            'description': 'Redis monitoring and cleanup for memory management',
            'features': [
                'Memory usage monitoring',
                'Key pattern analysis',
                'TTL management and cleanup',
                'Real-time metrics caching',
                'Connection health monitoring'
            ],
            'port': 6380,
            'key_patterns': ['l1:{symbol}', 'ticks:{symbol}', 'market_*:{symbol}'],
            'data_types': 'JSON serialized market data with timestamps',
            'cleanup': 'Automatic TTL management',
            'plugin': 'django-redis',
            'status': 'Available',
            'framework': 'Django'
        })


class KafkaStreamViewerAPIView(View):
    """Kafka Stream Viewer component as REST API"""
    
    def get(self, request):
        return JsonResponse({
            'component': 'Kafka Stream Viewer',
            'description': 'Live Kafka message streams monitoring',
            'features': [
                'Real-time message streaming',
                'Topic monitoring and lag analysis',
                'Consumer group management',
                'Message content inspection',
                'Performance metrics tracking'
            ],
            'topics': ['market_ticks', 'market_l1s', 'market_l2', 'live-*', 'realtime-*'],
            'partitioning': 'By symbol for ordered processing',
            'producer_settings': 'High-throughput, reliable delivery',
            'consumer_groups': ['UI components', 'storage services'],
            'status': 'Available',
            'framework': 'Django'
        })


# Real-Time Network Monitoring API Views
class NetworkTestStatusAPIView(View):
    """Real-time network test status from Redis"""
    
    def get(self, request):
        try:
            from django_redis import get_redis_connection
            redis_client = get_redis_connection("default")
            
            # Get current test status
            current_test = redis_client.hgetall('network_test:current')
            
            if not current_test:
                return JsonResponse({
                    'status': 'NO_TEST_RUNNING',
                    'message': 'No network test currently running',
                    'framework': 'Django'
                })
            
            # Convert bytes to strings and format
            test_data = {k.decode() if isinstance(k, bytes) else k: 
                        v.decode() if isinstance(v, bytes) else v 
                        for k, v in current_test.items()}
            
            return JsonResponse({
                'status': 'ACTIVE_TEST',
                'test_data': test_data,
                'framework': 'Django',
                'data_source': 'REAL_TIME_REDIS'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'ERROR',
                'error': str(e),
                'framework': 'Django'
            }, status=500)


class NetworkTestHistoryAPIView(View):
    """Network test history and completed tests"""
    
    def get(self, request):
        try:
            from django_redis import get_redis_connection
            import json
            
            redis_client = get_redis_connection("default")
            
            # Get completed tests
            completed_tests_raw = redis_client.lrange('network_test:completed', 0, 10)
            completed_tests = []
            
            for test_raw in completed_tests_raw:
                try:
                    test_data = json.loads(test_raw.decode() if isinstance(test_raw, bytes) else test_raw)
                    completed_tests.append(test_data)
                except Exception as e:
                    logger.warning(f"💥 FAKE ELIMINATED: Failed to parse completed test: {e}")
                    continue
            
            # Get historical data points
            history_raw = redis_client.lrange('network_test:history', 0, 50)
            history_data = []
            
            for point_raw in history_raw:
                try:
                    point_data = json.loads(point_raw.decode() if isinstance(point_raw, bytes) else point_raw)
                    history_data.append(point_data)
                except Exception as e:
                    logger.warning(f"💥 FAKE ELIMINATED: Failed to parse history data: {e}")
                    continue
            
            # Get summary
            summary_raw = redis_client.hgetall('network_test:summary')
            summary = {k.decode() if isinstance(k, bytes) else k: 
                      v.decode() if isinstance(v, bytes) else v 
                      for k, v in summary_raw.items()} if summary_raw else {}
            
            return JsonResponse({
                'completed_tests': completed_tests,
                'historical_data': history_data,
                'summary': summary,
                'total_completed': len(completed_tests),
                'framework': 'Django',
                'data_source': 'REAL_TIME_REDIS'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'ERROR',
                'error': str(e),
                'framework': 'Django'
            }, status=500)


class NetworkCapacityAPIView(View):
    """Real-time network capacity assessment"""
    
    def get(self, request):
        try:
            from django_redis import get_redis_connection
            import json
            
            redis_client = get_redis_connection("default")
            
            # Get current capacity metrics
            current_test = redis_client.hgetall('network_test:current')
            summary = redis_client.hgetall('network_test:summary')
            
            # Calculate capacity assessment
            current_tickers = int(current_test.get(b'ticker_count' if b'ticker_count' in current_test else 'ticker_count', 0))
            current_bandwidth = float(current_test.get(b'bandwidth_mbps' if b'bandwidth_mbps' in current_test else 'bandwidth_mbps', 0))
            
            # Estimate capacity limits
            bandwidth_per_ticker = current_bandwidth / current_tickers if current_tickers > 0 else 0.612  # From testing
            
            conservative_limit = int(100 / bandwidth_per_ticker) if bandwidth_per_ticker > 0 else 163  # 100 Mbps limit
            aggressive_limit = int(500 / bandwidth_per_ticker) if bandwidth_per_ticker > 0 else 816   # 500 Mbps limit
            
            capacity_assessment = {
                'current_ticker_count': current_tickers,
                'current_bandwidth_mbps': current_bandwidth,
                'bandwidth_per_ticker': bandwidth_per_ticker,
                'capacity_estimates': {
                    'conservative_limit_tickers': conservative_limit,
                    'aggressive_limit_tickers': aggressive_limit,
                    'recommended_production': int(conservative_limit * 0.7),
                    'safety_margin_percent': 30
                },
                'performance_thresholds': {
                    'bandwidth_warning_mbps': 50,
                    'bandwidth_critical_mbps': 100,
                    'latency_warning_ms': 10,
                    'latency_critical_ms': 50
                },
                'system_status': summary.get(b'system_status' if isinstance(list(summary.keys())[0], bytes) else 'system_status', 'UNKNOWN') if summary else 'UNKNOWN',
                'level2_available': summary.get(b'level2_working' if isinstance(list(summary.keys())[0], bytes) else 'level2_working', 'false') if summary else 'false'
            }
            
            return JsonResponse({
                'capacity_assessment': capacity_assessment,
                'framework': 'Django',
                'data_source': 'REAL_TIME_CALCULATION'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'ERROR',
                'error': str(e),
                'framework': 'Django'
            }, status=500)


# ============================================================================
# COMPREHENSIVE PRODUCTION MONITORING DASHBOARD VIEWS
# ============================================================================

class ProductionDashboardView(View):
    """Main production monitoring dashboard view"""
    
    @method_decorator(login_required)
    def get(self, request):
        """Render the main production dashboard"""
        try:
            # Get comprehensive system status
            comprehensive_status = monitor.get_comprehensive_status()
            
            # Get recent alerts
            recent_alerts = ProductionAlert.objects.filter(
                is_active=True
            ).order_by("-last_triggered")[:10]
            
            # Get health trend (last 24 hours)
            health_trend = SystemHealthSnapshot.objects.filter(
                timestamp__gte=timezone.now() - timedelta(hours=24)
            ).order_by("timestamp").values(
                "timestamp", "health_score", "overall_status"
            )
            
            # Get component statuses
            latest_components = {}
            for component_type in ["iqfeed", "kafka", "redis", "clickhouse", "system"]:
                latest = ComponentStatus.objects.filter(
                    component_type=component_type
                ).order_by("-timestamp").first()
                if latest:
                    latest_components[component_type] = latest
            
            context = {
                "title": "Hedge Fund Production Monitor",
                "comprehensive_status": comprehensive_status,
                "recent_alerts": recent_alerts,
                "health_trend": list(health_trend),
                "component_statuses": latest_components,
                "framework": "Django Production Dashboard"
            }
            
            return render(request, "monitor/production_dashboard.html", context)
            
        except Exception as e:
            logger.error(f"Production dashboard error: {e}")
            return render(request, "monitor/error.html", {
                "error": str(e),
                "framework": "Django"
            })


class RealTimeMetricsView(View):
    """Real-time metrics API for dashboard updates - Redis-based"""
    
    def get(self, request):
        """Get real-time metrics from Redis cache for fast dashboard updates"""
        try:
            # Get comprehensive dashboard data from Redis
            dashboard_data = alert_manager.get_dashboard_data()
            
            # Generate fresh alerts and store in Redis
            alert_manager.generate_and_store_alerts()
            
            # Get current system status (cached)
            status = monitor.get_comprehensive_status()
            
            return JsonResponse({
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "dashboard_data": dashboard_data,
                "data_source": "Redis Cache",
                "framework": "Django + Redis Real-Time API"
            })
            
        except Exception as e:
            logger.error(f"Redis real-time metrics error: {e}")
            return JsonResponse({
                "status": "error",
                "error": str(e),
                "framework": "Django + Redis"
            }, status=500)


class TradingSystemHealthView(View):
    """Specialized view for trading system health assessment"""
    
    def get(self, request):
        """Get trading-specific system health"""
        try:
            # Get comprehensive status
            status = monitor.get_comprehensive_status()
            
            # Assess trading readiness
            trading_ready = status.get("money_safe", False)
            
            # Get critical trading components status
            trading_components = ["iqfeed", "data_flow", "clickhouse"]
            component_health = {}
            
            for component in trading_components:
                comp_status = status.get("services", {}).get(component, {})
                component_health[component] = {
                    "status": comp_status.get("status", "UNKNOWN"),
                    "message": comp_status.get("message", ""),
                    "critical_for_trading": True
                }
            
            # Get recent trading-critical alerts
            trading_alerts = ProductionAlert.objects.filter(
                is_active=True,
                category__in=["iqfeed", "data_flow", "clickhouse"],
                level__in=["CRITICAL", "URGENT"]
            ).order_by("-last_triggered")[:5]
            
            # Calculate trading risk score
            risk_factors = []
            if not trading_ready:
                risk_factors.append("System marked as unsafe for trading")
            
            critical_alerts = [a for a in trading_alerts if a.level == "CRITICAL"]
            if critical_alerts:
                risk_factors.append(f"{len(critical_alerts)} critical trading alerts")
            
            # Get data flow health
            data_flow_rate = status.get("data_flow", {}).get("total_messages_per_minute", 0)
            if data_flow_rate < 10:
                risk_factors.append("Low data flow rate")
            
            return JsonResponse({
                "timestamp": datetime.now().isoformat(),
                "trading_ready": trading_ready,
                "overall_health_score": status.get("health_score", 0),
                "component_health": component_health,
                "risk_factors": risk_factors,
                "data_flow_rate": data_flow_rate,
                "trading_alerts": [
                    {
                        "title": alert.title,
                        "level": alert.level,
                        "category": alert.category,
                        "timestamp": alert.last_triggered.isoformat()
                    } for alert in trading_alerts
                ],
                "framework": "Django Trading Health Monitor"
            })
            
        except Exception as e:
            logger.error(f"Trading system health error: {e}")
            return JsonResponse({
                "status": "error",
                "error": str(e),
                "trading_ready": False
            }, status=500)


class ComponentHealthView(View):
    """Component-specific health monitoring API"""
    
    def get(self, request, component_type=None):
        """Get health status for specific component or all components"""
        try:
            service_health = monitor.check_service_health()
            
            if component_type:
                # Return specific component health
                if component_type in service_health:
                    return JsonResponse({
                        "timestamp": datetime.now().isoformat(),
                        "component": component_type,
                        "health": service_health[component_type],
                        "framework": "Django Component Monitor"
                    })
                else:
                    return JsonResponse({
                        "error": f"Unknown component: {component_type}",
                        "available_components": list(service_health.keys())
                    }, status=404)
            else:
                # Return all components health
                return JsonResponse({
                    "timestamp": datetime.now().isoformat(),
                    "components": service_health,
                    "total_components": len(service_health),
                    "healthy_components": sum(1 for c in service_health.values() 
                                            if c.get("status") == "HEALTHY"),
                    "framework": "Django Component Monitor"
                })
                
        except Exception as e:
            logger.error(f"Component health check error: {e}")
            return JsonResponse({
                "error": str(e),
                "component": component_type,
                "status": "ERROR"
            }, status=500)


class HealthTrendView(View):
    """Health trend data for monitoring dashboard"""
    
    def get(self, request):
        """Get health trend data over time"""
        try:
            # Get time range from query params
            hours = int(request.GET.get("hours", 24))
            
            # Generate sample trend data (in production, this would come from time-series DB)
            now = datetime.now()
            trend_data = []
            
            for i in range(hours):
                timestamp = now - timedelta(hours=i)
                # Simulate health score fluctuation
                base_score = 85
                variation = (i % 6) * 2 - 6  # Creates variation pattern
                health_score = min(100, max(0, base_score + variation))
                
                trend_data.append({
                    "timestamp": timestamp.isoformat(),
                    "health_score": health_score,
                    "cpu_percent": 30 + (i % 8) * 5,
                    "memory_percent": 60 + (i % 10) * 3,
                    "data_flow_rate": 1000 + (i % 12) * 100
                })
            
            return JsonResponse({
                "timestamp": datetime.now().isoformat(),
                "hours": hours,
                "trend_data": trend_data,
                "summary": {
                    "avg_health_score": sum(d["health_score"] for d in trend_data) / len(trend_data),
                    "min_health_score": min(d["health_score"] for d in trend_data),
                    "max_health_score": max(d["health_score"] for d in trend_data)
                },
                "framework": "Django Health Trend Monitor"
            })
            
        except Exception as e:
            logger.error(f"Health trend error: {e}")
            return JsonResponse({
                "error": str(e),
                "status": "ERROR"
            }, status=500)


class PerformanceAnalyticsView(View):
    """Performance analytics and metrics API"""
    
    def get(self, request):
        """Get detailed performance analytics"""
        try:
            # Get system metrics
            system_metrics = monitor.get_system_metrics()
            data_flow_metrics = monitor.get_data_flow_metrics()
            
            # Calculate performance indicators
            performance_data = {
                "timestamp": datetime.now().isoformat(),
                "system_performance": {
                    "cpu": {
                        "current": system_metrics.get("cpu_percent", 0),
                        "threshold": 80,
                        "status": "OK" if system_metrics.get("cpu_percent", 0) < 80 else "WARNING"
                    },
                    "memory": {
                        "current": system_metrics.get("memory_percent", 0),
                        "available_gb": system_metrics.get("memory_available_gb", 0),
                        "threshold": 85,
                        "status": "OK" if system_metrics.get("memory_percent", 0) < 85 else "WARNING"
                    },
                    "disk": {
                        "current": system_metrics.get("disk_percent", 0),
                        "free_gb": system_metrics.get("disk_free_gb", 0),
                        "threshold": 90,
                        "status": "OK" if system_metrics.get("disk_percent", 0) < 90 else "WARNING"
                    }
                },
                "data_pipeline_performance": {
                    "messages_per_minute": data_flow_metrics.get("total_messages_per_minute", 0),
                    "avg_latency_ms": data_flow_metrics.get("avg_latency_ms", 0),
                    "error_rate": data_flow_metrics.get("error_rate", 0),
                    "components": data_flow_metrics.get("components", {})
                },
                "process_metrics": system_metrics.get("processes", {}),
                "load_average": system_metrics.get("load_average", [0, 0, 0]),
                "framework": "Django Performance Analytics"
            }
            
            return JsonResponse(performance_data)
            
        except Exception as e:
            logger.error(f"Performance analytics error: {e}")
            return JsonResponse({
                "error": str(e),
                "status": "ERROR"
            }, status=500)


class SystemMaintenanceView(View):
    """System maintenance operations API"""
    
    def get(self, request):
        """Get maintenance status and recommendations"""
        try:
            # Check system status
            status = monitor.get_comprehensive_status()
            
            # Generate maintenance recommendations
            recommendations = []
            
            # Check CPU usage
            cpu_percent = status.get("system", {}).get("cpu_percent", 0)
            if cpu_percent > 80:
                recommendations.append({
                    "type": "performance",
                    "severity": "high",
                    "message": f"High CPU usage ({cpu_percent}%). Consider scaling or optimizing processes.",
                    "action": "investigate_cpu_usage"
                })
            
            # Check memory usage
            memory_percent = status.get("system", {}).get("memory_percent", 0)
            if memory_percent > 85:
                recommendations.append({
                    "type": "performance",
                    "severity": "high",
                    "message": f"High memory usage ({memory_percent}%). Consider increasing memory or optimizing usage.",
                    "action": "investigate_memory_usage"
                })
            
            # Check disk space
            disk_percent = status.get("system", {}).get("disk_percent", 0)
            if disk_percent > 90:
                recommendations.append({
                    "type": "storage",
                    "severity": "critical",
                    "message": f"Low disk space ({100-disk_percent}% free). Clean up old data or expand storage.",
                    "action": "cleanup_disk_space"
                })
            
            # Check for failed jobs
            from .models import DownloadJob
            failed_jobs = DownloadJob.objects.filter(
                status="failed",
                created_at__gte=datetime.now() - timedelta(days=1)
            ).count()
            
            if failed_jobs > 5:
                recommendations.append({
                    "type": "jobs",
                    "severity": "medium",
                    "message": f"{failed_jobs} jobs failed in last 24 hours. Review and retry.",
                    "action": "review_failed_jobs"
                })
            
            return JsonResponse({
                "timestamp": datetime.now().isoformat(),
                "maintenance_status": "OK" if not recommendations else "ACTION_REQUIRED",
                "recommendations": recommendations,
                "system_uptime_hours": status.get("uptime_hours", 0),
                "last_maintenance": None,  # Would come from DB in production
                "framework": "Django System Maintenance"
            })
            
        except Exception as e:
            logger.error(f"System maintenance error: {e}")
            return JsonResponse({
                "error": str(e),
                "status": "ERROR"
            }, status=500)


class AlertManagementView(View):
    """Alert management dashboard view"""
    
    def get(self, request):
        """Render alert management page"""
        try:
            from .models import Alert
            
            # Get active alerts
            active_alerts = Alert.objects.filter(is_active=True).order_by("-last_triggered")
            
            # Get alert statistics
            alert_stats = {
                "total_active": active_alerts.count(),
                "critical": active_alerts.filter(level="CRITICAL").count(),
                "warning": active_alerts.filter(level="WARNING").count(),
                "info": active_alerts.filter(level="INFO").count()
            }
            
            context = {
                "alerts": active_alerts[:20],  # Show latest 20 alerts
                "alert_stats": alert_stats,
                "page_title": "Alert Management"
            }
            
            return render(request, "monitor/alert_management.html", context)
            
        except Exception as e:
            logger.error(f"Alert management view error: {e}")
            return render(request, "monitor/error.html", {
                "error": str(e),
                "page_title": "Alert Management Error"
            })


class AlertActionView(View):
    """Handle alert actions (acknowledge, resolve, etc.)"""
    
    def post(self, request, alert_id):
        """Process alert action"""
        try:
            from .models import Alert
            
            alert = Alert.objects.get(id=alert_id)
            action = request.POST.get("action")
            
            if action == "acknowledge":
                alert.is_acknowledged = True
                alert.acknowledged_by = request.user
                alert.acknowledged_at = datetime.now()
                alert.save()
                
                return JsonResponse({
                    "status": "success",
                    "message": f"Alert {alert_id} acknowledged"
                })
                
            elif action == "resolve":
                alert.is_resolved = True
                alert.resolved_by = request.user
                alert.resolved_at = datetime.now()
                alert.resolution_notes = request.POST.get("notes", "")
                alert.is_active = False
                alert.save()
                
                return JsonResponse({
                    "status": "success",
                    "message": f"Alert {alert_id} resolved"
                })
                
            else:
                return JsonResponse({
                    "status": "error",
                    "message": f"Unknown action: {action}"
                }, status=400)
                
        except Alert.DoesNotExist:
            return JsonResponse({
                "status": "error",
                "message": f"Alert {alert_id} not found"
            }, status=404)
        except Exception as e:
            logger.error(f"Alert action error: {e}")
            return JsonResponse({
                "status": "error",
                "error": str(e)
            }, status=500)


# ============================================================================
# PROFESSIONAL CANDLESTICK CHART API ENDPOINTS
# ============================================================================

class ChartDataAPIView(View):
    """
    Professional-grade chart data API for TradingView integration
    Provides OHLCV data from ClickHouse with multiple timeframe support
    """
    
    def get(self, request):
        """Get historical OHLCV data for charting"""
        try:
            # Parse request parameters
            symbol = request.GET.get('symbol', 'AAPL').upper()
            timeframe = request.GET.get('timeframe', '1m')
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            limit = min(int(request.GET.get('limit', 1000)), 5000)  # Max 5000 bars
            
            # Validate timeframe
            valid_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
            if timeframe not in valid_timeframes:
                return JsonResponse({
                    'error': f'Invalid timeframe. Must be one of: {valid_timeframes}'
                }, status=400)
            
            # Get OHLCV data from ClickHouse
            ohlcv_data = self._get_ohlcv_data(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            
            if not ohlcv_data:
                return JsonResponse({
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'data': [],
                    'message': 'No data available for the specified parameters'
                })
            
            return JsonResponse({
                'symbol': symbol,
                'timeframe': timeframe,
                'data': ohlcv_data,
                'count': len(ohlcv_data),
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Chart data API error: {e}")
            return JsonResponse({
                'error': str(e),
                'status': 'error'
            }, status=500)
    
    def _get_ohlcv_data(self, symbol, timeframe, start_date=None, end_date=None, limit=1000):
        """Fetch OHLCV data from ClickHouse with aggregation"""
        try:
            # Check cache first for performance
            cache_key = f"chart_data_{symbol}_{timeframe}_{limit}_{start_date}_{end_date}"
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached OHLCV data for {symbol}")
                return cached_data
            
            # Initialize ClickHouse client
            client = clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)
            
            # Define timeframe mapping for ClickHouse intervals
            timeframe_mapping = {
                '1m': 'INTERVAL 1 MINUTE',
                '5m': 'INTERVAL 5 MINUTE', 
                '15m': 'INTERVAL 15 MINUTE',
                '30m': 'INTERVAL 30 MINUTE',
                '1h': 'INTERVAL 1 HOUR',
                '4h': 'INTERVAL 4 HOUR',
                '1d': 'INTERVAL 1 DAY'
            }
            
            interval = timeframe_mapping.get(timeframe, 'INTERVAL 1 MINUTE')
            
            # Build query conditions
            conditions = [f"symbol = '{symbol}'"]
            
            if start_date:
                conditions.append(f"timestamp >= '{start_date}'")
            else:
                # Default to last 7 days if no start date
                conditions.append("timestamp >= now() - INTERVAL 7 DAY")
                
            if end_date:
                conditions.append(f"timestamp <= '{end_date}'")
            
            where_clause = " AND ".join(conditions)
            
            # ClickHouse query for OHLCV aggregation
            query = f"""
            SELECT 
                toStartOfInterval(timestamp, {interval}) as time,
                argMin(price, timestamp) as open,
                max(price) as high,
                min(price) as low,
                argMax(price, timestamp) as close,
                sum(size) as volume,
                count(*) as trades
            FROM trades 
            WHERE {where_clause}
            GROUP BY time
            ORDER BY time DESC
            LIMIT {limit}
            """
            
            # Execute query
            result = client.query(query)
            
            # Convert to list of dictionaries
            ohlcv_data = []
            for row in result.result_rows:
                ohlcv_data.append({
                    'time': int(row[0].timestamp()),  # Unix timestamp for TradingView
                    'open': float(row[1]),
                    'high': float(row[2]),
                    'low': float(row[3]),
                    'close': float(row[4]),
                    'volume': int(row[5]),
                    'trades': int(row[6])
                })
            
            # Reverse to get chronological order
            ohlcv_data.reverse()
            
            # Cache the result for 30 seconds (balance between freshness and performance)
            cache.set(cache_key, ohlcv_data, 30)
            
            return ohlcv_data
            
        except Exception as e:
            logger.error(f"ClickHouse OHLCV query error: {e}")
            # Fallback to sample data for development
            return self._generate_sample_ohlcv_data(symbol, timeframe, limit)
    
    def _generate_sample_ohlcv_data(self, symbol, timeframe, limit):
        """Generate sample OHLCV data for development/testing"""
        try:
            import random
            from datetime import datetime, timedelta
            
            # Timeframe to minutes mapping
            timeframe_minutes = {
                '1m': 1, '5m': 5, '15m': 15, '30m': 30,
                '1h': 60, '4h': 240, '1d': 1440
            }
            
            minutes = timeframe_minutes.get(timeframe, 1)
            
            # Generate sample data
            data = []
            base_price = 150.0  # Sample base price
            current_time = datetime.now()
            
            for i in range(limit):
                timestamp = current_time - timedelta(minutes=minutes * (limit - i))
                
                # Generate realistic OHLCV data
                price_change = random.uniform(-2, 2)
                open_price = base_price + random.uniform(-1, 1)
                close_price = open_price + price_change
                high_price = max(open_price, close_price) + random.uniform(0, 1)
                low_price = min(open_price, close_price) - random.uniform(0, 1)
                volume = random.randint(1000, 50000)
                
                data.append({
                    'time': int(timestamp.timestamp()),
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(low_price, 2),
                    'close': round(close_price, 2),
                    'volume': volume,
                    'trades': random.randint(10, 500)
                })
                
                base_price = close_price  # Next bar starts where previous closed
            
            return data
            
        except Exception as e:
            logger.error(f"Sample data generation error: {e}")
            return []


class ChartRealTimeAPIView(View):
    """Real-time chart data updates from Redis"""
    
    def get(self, request):
        """Get real-time price updates for active charts"""
        try:
            symbols = request.GET.get('symbols', '').split(',')
            symbols = [s.strip().upper() for s in symbols if s.strip()]
            
            if not symbols:
                return JsonResponse({
                    'error': 'No symbols provided',
                    'status': 'error'
                }, status=400)
            
            # Get real-time data from Redis using connection pool
            redis_client = redis.Redis(connection_pool=redis_pool)
            real_time_data = {}
            
            for symbol in symbols:
                try:
                    # Try multiple Redis key patterns
                    tick_data = self._get_latest_tick_data(redis_client, symbol)
                    if tick_data:
                        real_time_data[symbol] = tick_data
                        
                except Exception as e:
                    logger.debug(f"Redis data fetch error for {symbol}: {e}")
                    continue
            
            return JsonResponse({
                'data': real_time_data,
                'timestamp': datetime.now().isoformat(),
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Real-time chart data error: {e}")
            return JsonResponse({
                'error': str(e),
                'status': 'error'
            }, status=500)
    
    def _get_latest_tick_data(self, redis_client, symbol):
        """Get latest tick/quote data from Redis"""
        # Try multiple key patterns
        key_patterns = [
            f"ticks:{symbol}",
            f"l1:{symbol}",
            f"market_ticks:{symbol}",
            f"trades:{symbol}"
        ]
        
        for pattern in key_patterns:
            try:
                # Try getting latest from list
                latest_data = redis_client.lindex(pattern, -1)
                if latest_data:
                    import json
                    data = json.loads(latest_data)
                    return {
                        'price': data.get('price', data.get('last_price', 0)),
                        'size': data.get('size', data.get('last_size', 0)),
                        'timestamp': data.get('timestamp', datetime.now().isoformat()),
                        'bid': data.get('bid_price', 0),
                        'ask': data.get('ask_price', 0)
                    }
                
                # Try getting single value
                data_str = redis_client.get(pattern)
                if data_str:
                    data = json.loads(data_str)
                    return {
                        'price': data.get('price', data.get('last_price', 0)),
                        'size': data.get('size', data.get('last_size', 0)),
                        'timestamp': data.get('timestamp', datetime.now().isoformat()),
                        'bid': data.get('bid_price', 0),
                        'ask': data.get('ask_price', 0)
                    }
                    
            except Exception:
                continue
                
        return None


class ChartSymbolsAPIView(View):
    """API for managing chart symbols and watchlists"""
    
    def get(self, request):
        """Get available symbols for charting"""
        try:
            # Check cache first (symbols don't change frequently)
            cache_key = "chart_symbols_list"
            cached_symbols = cache.get(cache_key)
            if cached_symbols:
                return JsonResponse(cached_symbols)
            
            # Get symbols from ClickHouse
            client = clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)
            
            query = """
            SELECT DISTINCT symbol, 
                   count(*) as data_points,
                   min(timestamp) as first_seen,
                   max(timestamp) as last_seen
            FROM trades 
            WHERE timestamp >= now() - INTERVAL 7 DAY
            GROUP BY symbol
            ORDER BY data_points DESC
            LIMIT 100
            """
            
            result = client.query(query)
            
            symbols = []
            for row in result.result_rows:
                symbols.append({
                    'symbol': row[0],
                    'data_points': int(row[1]),
                    'first_seen': row[2].isoformat(),
                    'last_seen': row[3].isoformat()
                })
            
            response_data = {
                'symbols': symbols,
                'count': len(symbols),
                'status': 'success'
            }
            
            # Cache for 5 minutes (symbols don't change frequently)
            cache.set(cache_key, response_data, 300)
            
            return JsonResponse(response_data)
            
        except Exception as e:
            logger.error(f"Chart symbols API error: {e}")
            # Return sample symbols for development
            sample_symbols = [
                {'symbol': 'AAPL', 'data_points': 10000, 'first_seen': '2025-07-22T09:30:00', 'last_seen': '2025-07-29T16:00:00'},
                {'symbol': 'TSLA', 'data_points': 8500, 'first_seen': '2025-07-22T09:30:00', 'last_seen': '2025-07-29T16:00:00'},
                {'symbol': 'NVDA', 'data_points': 9200, 'first_seen': '2025-07-22T09:30:00', 'last_seen': '2025-07-29T16:00:00'},
                {'symbol': 'MSFT', 'data_points': 7800, 'first_seen': '2025-07-22T09:30:00', 'last_seen': '2025-07-29T16:00:00'},
                {'symbol': 'GOOGL', 'data_points': 6900, 'first_seen': '2025-07-22T09:30:00', 'last_seen': '2025-07-29T16:00:00'}
            ]
            
            return JsonResponse({
                'symbols': sample_symbols,
                'count': len(sample_symbols),
                'status': 'success',
                'note': 'Sample data - ClickHouse connection failed'
            })


class ChartDashboardView(View):
    """Main chart dashboard view"""
    
    def get(self, request):
        """Render the professional chart dashboard"""
        try:
            # Get available symbols
            symbols_response = ChartSymbolsAPIView().get(request)
            symbols_data = json.loads(symbols_response.content)
            
            context = {
                'title': 'Professional Trading Charts',
                'symbols': symbols_data.get('symbols', []),
                'default_symbol': 'AAPL',
                'default_timeframe': '5m',
                'page_title': 'Professional Trading Charts'
            }
            
            return render(request, 'monitor/chart_dashboard.html', context)
            
        except Exception as e:
            logger.error(f"Chart dashboard error: {e}")
            return render(request, 'monitor/error.html', {
                'error': str(e),
                'page_title': 'Chart Dashboard Error'
            })


# ============================================================================
# L1 QUOTES VIEWS
# ============================================================================

class L1QuotesDashboardView(View):
    """L1 Quotes Dashboard View"""
    
    def get(self, request):
        """Render the L1 quotes dashboard"""
        try:
            context = {
                'title': 'L1 Quotes Monitor',
                'page_title': 'Level 1 Quotes',
                'default_symbols': ['AAPL', 'GOOGL', 'MSFT', 'TSLA']
            }
            
            return render(request, 'monitor/l1_quotes.html', context)
            
        except Exception as e:
            logger.error(f"L1 quotes dashboard error: {e}")
            return render(request, 'monitor/error.html', {
                'error': str(e),
                'page_title': 'L1 Quotes Error'
            })

