#!/usr/bin/env python3
"""
URL Configuration for Hedge Fund Monitor Django App
Professional REST API endpoints and dashboard routes
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import network_test_views
from . import api_views
from . import downloader_views

app_name = 'monitor'

# Create DRF router for downloader API
router = DefaultRouter()
router.register(r'configurations', api_views.DownloadConfigurationViewSet)
router.register(r'jobs', api_views.DownloadJobViewSet)
router.register(r'progress', api_views.DownloadProgressViewSet)
router.register(r'system-config', api_views.SystemConfigurationViewSet)
router.register(r'history', api_views.DownloadHistoryViewSet)
router.register(r'alerts', api_views.DownloadAlertViewSet)
router.register(r'l1-quotes', api_views.L1QuotesViewSet, basename='l1-quotes')

urlpatterns = [
    # Dashboard Views
    path('', views.dashboard_view, name='dashboard'),
    
    # Downloader Management Interface
    path('downloader/', downloader_views.downloader_dashboard, name='downloader_dashboard'),
    path('downloader/jobs/', downloader_views.job_list_view, name='job_list'),
    path('downloader/jobs/<str:job_id>/', downloader_views.job_detail_view, name='job_detail'),
    path('downloader/configurations/', downloader_views.configuration_list_view, name='configuration_list'),
    path('downloader/submit/', downloader_views.job_submit_view, name='job_submit'),
    
    # Downloader REST API
    path('api/downloader/', include(router.urls)),
    
    # Health and Status API Endpoints
    path('api/health/', views.HealthCheckView.as_view(), name='health'),
    path('api/status/', views.SystemStatusView.as_view(), name='system_status'),
    path('api/debug/', views.DebugInfoView.as_view(), name='debug_info'),
    
    # Metrics API Endpoints
    path('api/metrics/system/', views.SystemMetricsView.as_view(), name='system_metrics'),
    path('api/metrics/dataflow/', views.DataFlowMetricsView.as_view(), name='dataflow_metrics'),
    path('api/metrics/kafka/', views.KafkaMetricsView.as_view(), name='kafka_metrics'),
    path('api/metrics/clickhouse/', views.ClickHouseMetricsView.as_view(), name='clickhouse_metrics'),
    
    # Service Health Endpoints
    path('api/services/health/', views.ServiceHealthView.as_view(), name='service_health'),
    path('api/alerts/', views.AlertsView.as_view(), name='alerts'),
    
    # UI Testing Endpoints (curl-friendly)
    path('api/ui-test/', views.UITestDataView.as_view(), name='ui_test'),
    
    # Trading API Endpoints for Testing
    path('api/iqfeed/', views.IQFeedAPIView.as_view(), name='iqfeed_api'),
    path('api/ib/', views.InteractiveBrokersAPIView.as_view(), name='ib_api'),
    
    # Network Testing and Monitoring APIs
    path('api/network/status/', views.NetworkTestStatusAPIView.as_view(), name='network_test_status'),
    path('api/network/history/', views.NetworkTestHistoryAPIView.as_view(), name='network_test_history'),
    path('api/network/capacity/', views.NetworkCapacityAPIView.as_view(), name='network_capacity'),
    
    # Network Test Controller (UI-triggered tests)
    path('network-tests/', network_test_views.NetworkTestControllerView.as_view(), name='network_test_controller'),
    path('api/network/start/', network_test_views.StartNetworkTestView.as_view(), name='start_network_test'),
    path('api/network/stop/', network_test_views.StopNetworkTestView.as_view(), name='stop_network_test'),
    path('api/network/results/', network_test_views.NetworkTestResultsView.as_view(), name='network_test_results'),
    
    # Streamlit Component APIs (migrated to Django)
    path('api/historical-simulator/', views.HistoricalSimulatorAPIView.as_view(), name='historical_simulator'),
    path('api/l1-tape/', views.L1TapeDisplayAPIView.as_view(), name='l1_tape_display'),
    path('api/candlestick-chart/', views.CandlestickChartAPIView.as_view(), name='candlestick_chart'),
    path('api/data-downloader/', views.DataDownloaderAPIView.as_view(), name='data_downloader'),
    path('api/clickhouse-viewer/', views.ClickHouseViewerAPIView.as_view(), name='clickhouse_viewer'),
    path('api/redis-monitor/', views.RedisMonitorAPIView.as_view(), name='redis_monitor'),
    path('api/kafka-stream/', views.KafkaStreamViewerAPIView.as_view(), name='kafka_stream_viewer'),
    
    # Additional endpoints for different data types
    path('api/iqfeed/historical/', views.IQFeedAPIView.as_view(), name='iqfeed_historical'),
    path('api/iqfeed/realtime/', views.IQFeedAPIView.as_view(), name='iqfeed_realtime'),
    path('api/iqfeed/level2/', views.IQFeedAPIView.as_view(), name='iqfeed_level2'),
    path('api/iqfeed/fundamentals/', views.IQFeedAPIView.as_view(), name='iqfeed_fundamentals'),
    
    path('api/ib/portfolio/', views.InteractiveBrokersAPIView.as_view(), name='ib_portfolio'),
    path('api/ib/orders/', views.InteractiveBrokersAPIView.as_view(), name='ib_orders'),
    path('api/ib/positions/', views.InteractiveBrokersAPIView.as_view(), name='ib_positions'),
    path('api/ib/market-data/', views.InteractiveBrokersAPIView.as_view(), name='ib_market_data'),
    
    # ============================================================================
    # COMPREHENSIVE PRODUCTION MONITORING ENDPOINTS
    # ============================================================================
    
    # Main Production Dashboard
    path('production/', views.ProductionDashboardView.as_view(), name='production_dashboard'),
    
    # Real-time Metrics (Redis-based, no WebSockets)
    path('api/monitor/realtime-metrics/', views.RealTimeMetricsView.as_view(), name='realtime_metrics'),
    path('api/monitor/health-trend/', views.HealthTrendView.as_view(), name='health_trend'),
    
    # Alert Management
    path('alerts/', views.AlertManagementView.as_view(), name='alert_management'),
    path('api/alerts/<str:alert_id>/action/', views.AlertActionView.as_view(), name='alert_action'),
    
    # Component Health Monitoring
    path('api/monitor/components/', views.ComponentHealthView.as_view(), name='component_health_all'),
    path('api/monitor/components/<str:component_type>/', views.ComponentHealthView.as_view(), name='component_health_detail'),
    
    # Performance Analytics
    path('api/monitor/performance/', views.PerformanceAnalyticsView.as_view(), name='performance_analytics'),
    
    # System Maintenance
    path('api/monitor/maintenance/', views.SystemMaintenanceView.as_view(), name='system_maintenance'),
    
    # Trading System Health Assessment
    path('api/monitor/trading-health/', views.TradingSystemHealthView.as_view(), name='trading_health'),
    
    # ============================================================================
    # PROFESSIONAL CANDLESTICK CHART ENDPOINTS
    # ============================================================================
    
    # Chart Dashboard
    path('charts/', views.ChartDashboardView.as_view(), name='chart_dashboard'),
    
    # L1 Quotes Dashboard
    path('l1-quotes/', views.L1QuotesDashboardView.as_view(), name='l1_quotes_dashboard'),
    
    # Chart Data APIs
    path('api/charts/data/', views.ChartDataAPIView.as_view(), name='chart_data'),
    path('api/charts/realtime/', views.ChartRealTimeAPIView.as_view(), name='chart_realtime'),
    path('api/charts/symbols/', views.ChartSymbolsAPIView.as_view(), name='chart_symbols'),
    
    # ============================================================================
    # LEGACY/COMPATIBILITY ENDPOINTS
    # ============================================================================
    # These endpoints are for backward compatibility with the frontend
    path('api/components/', views.ComponentHealthView.as_view(), name='components_legacy'),
    path('api/trading/', views.TradingSystemHealthView.as_view(), name='trading_legacy'),
]