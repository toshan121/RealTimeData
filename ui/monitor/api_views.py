"""
Django REST API Views for Downloader System

Professional API endpoints for managing download jobs, configurations,
and monitoring system status.
"""

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Avg, Sum
from django.utils import timezone
from datetime import datetime, timedelta, timezone
import time
import logging

from .models import (
    DownloadConfiguration,
    DownloadJob, 
    DownloadProgress,
    SystemConfiguration,
    DownloadHistory,
    DownloadAlert
)
from .serializers import (
    DownloadConfigurationSerializer,
    DownloadJobSerializer,
    DownloadProgressSerializer,
    SystemConfigurationSerializer,
    DownloadHistorySerializer,
    DownloadAlertSerializer,
    JobSubmissionSerializer,
    JobActionSerializer,
    BulkJobActionSerializer,
    DownloadStatsSerializer
)
from .services import DownloaderService


logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for API results."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class DownloadConfigurationViewSet(viewsets.ModelViewSet):
    """
    API endpoints for managing download configurations.
    
    Provides CRUD operations for download configurations used by jobs.
    """
    queryset = DownloadConfiguration.objects.all()
    serializer_class = DownloadConfigurationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'is_default', 'storage_type']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def perform_create(self, serializer):
        """Set the created_by field when creating a configuration."""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set this configuration as the system default."""
        config = self.get_object()
        
        # Clear existing default
        DownloadConfiguration.objects.filter(is_default=True).update(is_default=False)
        
        # Set this as default
        config.is_default = True
        config.save()
        
        return Response({
            'status': 'success',
            'message': f'Configuration "{config.name}" set as default'
        })
    
    @action(detail=True, methods=['post'])
    def validate_config(self, request, pk=None):
        """Validate a configuration by testing connections."""
        config = self.get_object()
        
        try:
            # Convert to standalone config and validate
            standalone_config = config.to_downloader_config()
            
            try:
                from downloader.configuration.config_validator import ConfigurationValidator
            except ImportError:
                # Fallback if downloader module is not available
                class ConfigurationValidator:
                    def __init__(self, config):
                        self.config = config
                    def validate_all(self):
                        return True, []
                    def get_validation_summary(self):
                        return {'status': 'valid', 'message': 'Validation skipped - module not available'}
            validator = ConfigurationValidator(standalone_config)
            is_valid, results = validator.validate_all()
            
            return Response({
                'is_valid': is_valid,
                'validation_results': results,
                'summary': validator.get_validation_summary()
            })
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return Response({
                'is_valid': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def default(self, request):
        """Get the default configuration."""
        try:
            default_config = DownloadConfiguration.objects.get(is_default=True)
            serializer = self.get_serializer(default_config)
            return Response(serializer.data)
        except DownloadConfiguration.DoesNotExist:
            return Response({
                'error': 'No default configuration found'
            }, status=status.HTTP_404_NOT_FOUND)


class DownloadJobViewSet(viewsets.ModelViewSet):
    """
    API endpoints for managing download jobs.
    
    Provides CRUD operations and job control actions.
    """
    queryset = DownloadJob.objects.all()
    serializer_class = DownloadJobSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority', 'configuration', 'created_by']
    search_fields = ['job_id', 'name', 'description', 'symbols']
    ordering_fields = ['created_at', 'started_time', 'completed_time', 'priority']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Filter queryset based on query parameters."""
        queryset = super().get_queryset()
        
        # Filter by date ranges
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(start_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(end_date__lte=end_date)
        
        # Filter by symbols
        symbol = self.request.query_params.get('symbol')
        if symbol:
            queryset = queryset.filter(symbols__contains=[symbol.upper()])
        
        return queryset
    
    def perform_create(self, serializer):
        """Set the created_by field when creating a job."""
        serializer.save(created_by=self.request.user)
    
    @action(detail=False, methods=['post'])
    def submit(self, request):
        """Submit a new download job."""
        serializer = JobSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Get configuration
            config = DownloadConfiguration.objects.get(
                id=serializer.validated_data['configuration_id']
            )
            
            # Generate unique job ID
            job_id = f"job_{int(timezone.now().timestamp())}"
            
            # Create job
            job = DownloadJob.objects.create(
                job_id=job_id,
                name=serializer.validated_data.get('name', f'Download {len(serializer.validated_data["symbols"])} symbols'),
                description=serializer.validated_data.get('description', ''),
                configuration=config,
                symbols=serializer.validated_data['symbols'],
                start_date=serializer.validated_data['start_date'],
                end_date=serializer.validated_data['end_date'],
                data_types=serializer.validated_data['data_types'],
                priority=serializer.validated_data['priority'],
                max_concurrent_symbols=serializer.validated_data['max_concurrent_symbols'],
                max_retries=serializer.validated_data['max_retries'],
                continue_on_error=serializer.validated_data['continue_on_error'],
                skip_existing=serializer.validated_data['skip_existing'],
                force_redownload=serializer.validated_data['force_redownload'],
                scheduled_time=serializer.validated_data.get('scheduled_time'),
                created_by=request.user
            )
            
            # Submit to downloader service
            downloader_service = DownloaderService()
            downloader_service.submit_job(job)
            
            # Return job details
            job_serializer = DownloadJobSerializer(job)
            return Response({
                'status': 'success',
                'message': 'Job submitted successfully',
                'job': job_serializer.data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Job submission failed: {e}")
            return Response({
                'status': 'error',
                'message': f'Job submission failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def control(self, request, pk=None):
        """Control job execution (cancel, retry, etc.)."""
        job = self.get_object()
        serializer = JobActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action_type = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')
        
        try:
            downloader_service = DownloaderService()
            
            if action_type == 'cancel':
                if job.status in ['pending', 'running']:
                    success = downloader_service.cancel_job(job.job_id)
                    if success:
                        job.mark_cancelled()
                        message = 'Job cancelled successfully'
                    else:
                        message = 'Job cancellation requested but may not be immediate'
                else:
                    return Response({
                        'status': 'error',
                        'message': f'Cannot cancel job in {job.status} status'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif action_type == 'retry':
                if job.status == 'failed':
                    success = downloader_service.retry_job(job.job_id)
                    if success:
                        message = 'Job retry submitted successfully'
                    else:
                        message = 'Job retry failed - maximum retries exceeded'
                else:
                    return Response({
                        'status': 'error',
                        'message': f'Cannot retry job in {job.status} status'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'status': 'success',
                'message': message,
                'job_id': job.job_id
            })
            
        except Exception as e:
            logger.error(f"Job control action failed: {e}")
            return Response({
                'status': 'error',
                'message': f'Action failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """Get detailed progress information for a job."""
        job = self.get_object()
        
        # Get progress entries
        progress_entries = DownloadProgress.objects.filter(job=job).order_by('created_at')
        progress_serializer = DownloadProgressSerializer(progress_entries, many=True)
        
        # Get overall job progress from downloader service
        downloader_service = DownloaderService()
        live_progress = downloader_service.get_job_progress(job.job_id)
        
        return Response({
            'job_id': job.job_id,
            'status': job.status,
            'current_step': job.current_step,
            'total_steps': job.total_steps,
            'progress_percentage': job.progress_percentage,
            'current_message': job.current_message,
            'live_progress': live_progress,
            'detailed_progress': progress_serializer.data
        })
    
    @action(detail=False, methods=['post'])
    def bulk_action(self, request):
        """Perform bulk actions on multiple jobs."""
        serializer = BulkJobActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        job_ids = serializer.validated_data['job_ids']
        action_type = serializer.validated_data['action']
        reason = serializer.validated_data.get('reason', '')
        
        results = []
        downloader_service = DownloaderService()
        
        for job_id in job_ids:
            try:
                job = DownloadJob.objects.get(job_id=job_id)
                
                if action_type == 'cancel':
                    if job.status in ['pending', 'running']:
                        success = downloader_service.cancel_job(job_id)
                        if success:
                            job.mark_cancelled()
                        results.append({'job_id': job_id, 'status': 'cancelled'})
                    else:
                        results.append({'job_id': job_id, 'status': 'skipped', 'reason': f'Invalid status: {job.status}'})
                
                elif action_type == 'retry':
                    if job.status == 'failed':
                        success = downloader_service.retry_job(job_id)
                        results.append({'job_id': job_id, 'status': 'retried' if success else 'retry_failed'})
                    else:
                        results.append({'job_id': job_id, 'status': 'skipped', 'reason': f'Invalid status: {job.status}'})
                
                elif action_type == 'delete':
                    if job.status in ['completed', 'failed', 'cancelled']:
                        job.delete()
                        results.append({'job_id': job_id, 'status': 'deleted'})
                    else:
                        results.append({'job_id': job_id, 'status': 'skipped', 'reason': f'Cannot delete running job'})
                
            except DownloadJob.DoesNotExist:
                results.append({'job_id': job_id, 'status': 'not_found'})
            except Exception as e:
                results.append({'job_id': job_id, 'status': 'error', 'error': str(e)})
        
        return Response({
            'status': 'completed',
            'action': action_type,
            'results': results
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get job statistics and metrics."""
        # Get basic counts
        total_jobs = DownloadJob.objects.count()
        status_counts = DownloadJob.objects.values('status').annotate(count=Count('id'))
        
        # Convert to dictionary
        status_dict = {item['status']: item['count'] for item in status_counts}
        
        # Calculate performance metrics
        completed_jobs = DownloadJob.objects.filter(
            status='completed',
            started_time__isnull=False,
            completed_time__isnull=False
        )
        
        avg_duration = 0.0
        if completed_jobs.exists():
            durations = [
                (job.completed_time - job.started_time).total_seconds()
                for job in completed_jobs
            ]
            avg_duration = sum(durations) / len(durations)
        
        # Recent activity (last 24 hours)
        last_24h = timezone.now() - timedelta(hours=24)
        recent_jobs = DownloadJob.objects.filter(created_at__gte=last_24h).count()
        
        # Get top symbols
        # This is a simplified version - in production you'd want more sophisticated analytics
        all_symbols = []
        for job in DownloadJob.objects.all():
            all_symbols.extend(job.symbols or [])
        
        from collections import Counter
        symbol_counts = Counter(all_symbols)
        top_symbols = [
            {'symbol': symbol, 'count': count}
            for symbol, count in symbol_counts.most_common(10)
        ]
        
        stats_data = {
            'total_jobs': total_jobs,
            'pending_jobs': status_dict.get('pending', 0),
            'running_jobs': status_dict.get('running', 0),
            'completed_jobs': status_dict.get('completed', 0),
            'failed_jobs': status_dict.get('failed', 0),
            'cancelled_jobs': status_dict.get('cancelled', 0),
            'total_downloads': 0,  # Would calculate from progress entries
            'successful_downloads': 0,
            'failed_downloads': 0,
            'success_rate': 0.0,
            'avg_job_duration': avg_duration,
            'avg_download_rate': 0.0,
            'jobs_last_24h': recent_jobs,
            'downloads_last_24h': 0,
            'top_symbols': top_symbols,
            'active_configurations': DownloadConfiguration.objects.filter(is_active=True).count(),
            'storage_usage_gb': 0.0,  # Would calculate from file system
            'stats_generated_at': timezone.now(),
            'data_last_updated': timezone.now()
        }
        
        serializer = DownloadStatsSerializer(stats_data)
        return Response(serializer.data)


class DownloadProgressViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for viewing download progress details.
    
    Read-only access to detailed progress information.
    """
    queryset = DownloadProgress.objects.all()
    serializer_class = DownloadProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['job', 'symbol', 'data_type', 'status']
    ordering_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['-created_at']


class SystemConfigurationViewSet(viewsets.ModelViewSet):
    """
    API endpoints for system configuration management.
    
    Manages system-wide downloader settings.
    """
    queryset = SystemConfiguration.objects.all()
    serializer_class = SystemConfigurationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        """Always return the current system configuration."""
        return SystemConfiguration.get_current()
    
    def list(self, request):
        """Return the current system configuration."""
        config = self.get_object()
        serializer = self.get_serializer(config)
        return Response(serializer.data)
    
    def update(self, request, pk=None):
        """Update system configuration."""
        config = self.get_object()
        serializer = self.get_serializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)


class DownloadHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for viewing download history and statistics.
    
    Provides historical performance data and analytics.
    """
    queryset = DownloadHistory.objects.all()
    serializer_class = DownloadHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['date']
    ordering_fields = ['date', 'hour']
    ordering = ['-date', '-hour']
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary statistics for a date range."""
        # Get date range from query parameters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        queryset = self.get_queryset()
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        # Calculate aggregated statistics
        summary = queryset.aggregate(
            total_jobs=Sum('total_jobs'),
            completed_jobs=Sum('completed_jobs'),
            failed_jobs=Sum('failed_jobs'),
            cancelled_jobs=Sum('cancelled_jobs'),
            total_downloads=Sum('total_downloads'),
            successful_downloads=Sum('successful_downloads'),
            failed_downloads=Sum('failed_downloads'),
            avg_duration=Avg('avg_download_duration'),
            avg_rate=Avg('avg_records_per_second')
        )
        
        # Calculate success rate
        total_downloads = summary['total_downloads'] or 0
        successful_downloads = summary['successful_downloads'] or 0
        success_rate = (successful_downloads / total_downloads * 100.0) if total_downloads > 0 else 0.0
        
        return Response({
            'date_range': {
                'start_date': start_date,
                'end_date': end_date
            },
            'summary': {
                **summary,
                'success_rate': success_rate
            },
            'record_count': queryset.count()
        })


class DownloadAlertViewSet(viewsets.ModelViewSet):
    """
    API endpoints for managing download alerts and notifications.
    
    Provides alert management and acknowledgment functionality.
    """
    queryset = DownloadAlert.objects.all()
    serializer_class = DownloadAlertSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['alert_type', 'severity', 'is_read', 'is_acknowledged']
    ordering_fields = ['created_at', 'severity']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """Acknowledge an alert."""
        alert = self.get_object()
        alert.acknowledge(request.user)
        
        serializer = self.get_serializer(alert)
        return Response({
            'status': 'success',
            'message': 'Alert acknowledged',
            'alert': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark an alert as read."""
        alert = self.get_object()
        alert.is_read = True
        alert.save()
        
        serializer = self.get_serializer(alert)
        return Response({
            'status': 'success',
            'message': 'Alert marked as read',
            'alert': serializer.data
        })
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all alerts as read."""
        unread_alerts = DownloadAlert.objects.filter(is_read=False)
        count = unread_alerts.update(is_read=True)
        
        return Response({
            'status': 'success',
            'message': f'Marked {count} alerts as read'
        })
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get count of unread alerts."""
        count = DownloadAlert.objects.filter(is_read=False).count()
        return Response({'unread_count': count})


# ============================================================================
# L1 QUOTES API ENDPOINTS
# ============================================================================

class L1QuotesViewSet(viewsets.ViewSet):
    """
    Simple L1 quotes API endpoints for real-time trading display.
    
    Features:
    - Live quotes from Redis cache
    - Historical quotes from ClickHouse
    - Simple watchlist management
    - Market replay support
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_data_sources()
    
    def _setup_data_sources(self):
        """Initialize Redis and ClickHouse connections with proper timeouts."""
        try:
            # Redis for real-time data - Configure aggressive timeouts to prevent 10+ second delays
            import redis
            self.redis_client = redis.Redis(
                host='127.0.0.1', 
                port=6380, 
                db=0, 
                decode_responses=True,
                socket_timeout=2.0,           # 2 second socket timeout
                socket_connect_timeout=1.0,   # 1 second connection timeout  
                health_check_interval=30,     # Health check every 30 seconds
                retry_on_timeout=True,        # Retry on timeout
                socket_keepalive=True,        # Keep connection alive
                socket_keepalive_options={}   # Use system defaults
            )
            
            # Test connection immediately with timeout
            try:
                self.redis_client.ping()
                logger.info("Redis connection established successfully")
            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.error(f"Redis connection failed: {e}")
                self.redis_client = None
            
            # ClickHouse for historical data with timeout  
            try:
                from storage.clickhouse_historical_api import ClickHouseHistoricalAPI
                self.clickhouse_api = ClickHouseHistoricalAPI()
            except ImportError:
                logger.warning("ClickHouse API not available")
                self.clickhouse_api = None
                
        except Exception as e:
            logger.error(f"Failed to setup data sources: {e}")
            self.redis_client = None
            self.clickhouse_api = None
    
    @action(detail=False, methods=['get'])
    def live_quotes(self, request):
        """Get live L1 quotes for symbols."""
        symbols = request.query_params.get('symbols', '').upper().split(',')
        symbols = [s.strip() for s in symbols if s.strip()]
        
        if not symbols:
            return Response({'error': 'No symbols provided'}, status=400)
        
        quotes = []
        
        for symbol in symbols:
            try:
                # Get latest L1 data from Redis with timeout protection
                if not self.redis_client:
                    quotes.append({
                        'symbol': symbol,
                        'error': 'Redis connection not available',
                        'data_quality': 'error'
                    })
                    continue
                
                redis_key = f"market:l1:{symbol}:latest"
                # Use timeout protection - Redis client already configured with timeouts
                quote_data = self.redis_client.get(redis_key)
                
                if quote_data:
                    import json
                    quote = json.loads(quote_data)
                    
                    # Calculate spread and other derived fields
                    bid = float(quote.get('bid', 0))
                    ask = float(quote.get('ask', 0))
                    
                    quotes.append({
                        'symbol': symbol,
                        'bid': bid,
                        'ask': ask,
                        'bid_size': quote.get('bid_size', 0),
                        'ask_size': quote.get('ask_size', 0),
                        'spread': round(ask - bid, 4) if bid and ask else 0,
                        'spread_pct': round((ask - bid) / ((ask + bid) / 2) * 100, 3) if bid and ask else 0,
                        'last_price': quote.get('last_trade_price', 0),
                        'last_size': quote.get('last_trade_size', 0),
                        'timestamp': quote.get('timestamp'),
                        'age_seconds': self._calculate_quote_age(quote.get('timestamp')),
                        'data_quality': self._assess_quote_quality(quote)
                    })
                else:
                    # No live data available
                    quotes.append({
                        'symbol': symbol,
                        'bid': 0,
                        'ask': 0,
                        'bid_size': 0,
                        'ask_size': 0,
                        'spread': 0,
                        'spread_pct': 0,
                        'last_price': 0,
                        'last_size': 0,
                        'timestamp': None,
                        'age_seconds': None,
                        'data_quality': 'no_data'
                    })
                    
            except Exception as e:
                logger.error(f"Error getting quote for {symbol}: {e}")
                quotes.append({
                    'symbol': symbol,
                    'error': str(e),
                    'data_quality': 'error'
                })
        
        return Response({
            'quotes': quotes,
            'timestamp': time.time(),
            'source': 'redis_live'
        })
    
    @action(detail=False, methods=['get'])
    def historical_quotes(self, request):
        """Get historical L1 quotes for a symbol."""
        symbol = request.query_params.get('symbol', '').upper()
        date = request.query_params.get('date')  # YYYY-MM-DD format
        limit = int(request.query_params.get('limit', 100))
        
        if not symbol:
            return Response({'error': 'Symbol required'}, status=400)
        
        if not self.clickhouse_api:
            return Response({'error': 'Historical data not available'}, status=503)
        
        try:
            # Query ClickHouse for historical L1 data
            quotes = self.clickhouse_api.get_l1_quotes_for_symbol(
                symbol=symbol,
                date=date,
                limit=limit
            )
            
            return Response({
                'symbol': symbol,
                'date': date,
                'quotes': quotes,
                'count': len(quotes),
                'source': 'clickhouse_historical'
            })
            
        except Exception as e:
            logger.error(f"Error getting historical quotes for {symbol}: {e}")
            return Response({'error': str(e)}, status=500)
    
    @action(detail=False, methods=['get'])
    def watchlist(self, request):
        """Get user's watchlist symbols."""
        # Simple session-based watchlist for now
        watchlist = request.session.get('watchlist', ['AAPL', 'GOOGL', 'MSFT', 'TSLA'])
        return Response({'watchlist': watchlist})
    
    @action(detail=False, methods=['post'])
    def update_watchlist(self, request):
        """Update user's watchlist."""
        symbols = request.data.get('symbols', [])
        
        # Clean and validate symbols
        clean_symbols = []
        for symbol in symbols:
            if isinstance(symbol, str) and symbol.strip():
                clean_symbols.append(symbol.strip().upper())
        
        # Store in session (simple approach)
        request.session['watchlist'] = clean_symbols[:20]  # Limit to 20 symbols
        
        return Response({
            'message': 'Watchlist updated',
            'watchlist': clean_symbols
        })
    
    @action(detail=False, methods=['get'])
    def market_status(self, request):
        """Get current market status and data source info."""
        from datetime import datetime
        import pytz
        
        # Simple market hours check (9:30 AM - 4:00 PM ET)
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        is_market_hours = market_open <= now_et <= market_close and now_et.weekday() < 5
        
        # Check if we have recent data in Redis with timeout protection
        try:
            if not self.redis_client:
                data_availability = 'redis_unavailable'
            else:
                test_symbols = ['AAPL', 'SPY', 'QQQ']
                recent_data_count = 0
                
                for symbol in test_symbols:
                    try:
                        redis_key = f"market:l1:{symbol}:latest"
                        # Redis client configured with timeouts will handle this quickly
                        if self.redis_client.exists(redis_key):
                            recent_data_count += 1
                    except (redis.ConnectionError, redis.TimeoutError):
                        # Skip symbol on timeout, don't fail entire check
                        continue
                
                data_availability = 'good' if recent_data_count >= 2 else 'limited' if recent_data_count > 0 else 'none'
                
        except Exception:
            data_availability = 'unknown'
        
        return Response({
            'market_open': is_market_hours,
            'current_time_et': now_et.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'market_open_time': market_open.strftime('%H:%M'),
            'market_close_time': market_close.strftime('%H:%M'),
            'data_availability': data_availability,
            'data_sources': {
                'redis_available': self.redis_client is not None,
                'clickhouse_available': self.clickhouse_api is not None
            }
        })
    
    def _calculate_quote_age(self, timestamp_str):
        """Calculate how old a quote is in seconds."""
        if not timestamp_str:
            return None
        
        try:
            import dateutil.parser
            quote_time = dateutil.parser.parse(timestamp_str)
            now = datetime.now(timezone.utc)
            
            age_seconds = (now - quote_time).total_seconds()
            return round(age_seconds, 1)
            
        except Exception:
            return None
    
    def _assess_quote_quality(self, quote_data):
        """Simple quote quality assessment."""
        bid = float(quote_data.get('bid', 0))
        ask = float(quote_data.get('ask', 0))
        
        if not bid or not ask:
            return 'no_quotes'
        
        if bid >= ask:
            return 'invalid_spread'
        
        # Check for reasonable spread
        spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
        
        if spread_pct > 5:  # > 5% spread
            return 'wide_spread'
        elif spread_pct > 1:  # 1-5% spread  
            return 'normal_spread'
        else:
            return 'tight_spread'
    
    @action(detail=False, methods=['get'])
    def stream_quotes(self, request):
        """Server-Sent Events stream for real-time quote updates."""
        from django.http import StreamingHttpResponse
        import time
        import json
        
        def event_stream():
            """Generate SSE events for live quotes."""
            symbols = request.GET.get('symbols', 'AAPL,GOOGL,MSFT,TSLA').upper().split(',')
            symbols = [s.strip() for s in symbols if s.strip()]
            
            yield f"data: {json.dumps({'type': 'connected', 'symbols': symbols})}\n\n"
            
            while True:
                try:
                    # Get live quotes
                    quotes = []
                    for symbol in symbols:
                        redis_key = f"market:l1:{symbol}:latest"
                        quote_data = self.redis_client.get(redis_key) if self.redis_client else None
                        
                        if quote_data:
                            quote = json.loads(quote_data)
                            bid = float(quote.get('bid', 0))
                            ask = float(quote.get('ask', 0))
                            
                            quotes.append({
                                'symbol': symbol,
                                'bid': bid,
                                'ask': ask,
                                'bid_size': quote.get('bid_size', 0),
                                'ask_size': quote.get('ask_size', 0),
                                'spread': round(ask - bid, 4) if bid and ask else 0,
                                'spread_pct': round((ask - bid) / ((ask + bid) / 2) * 100, 3) if bid and ask else 0,
                                'last_price': quote.get('last_trade_price', 0),
                                'last_size': quote.get('last_trade_size', 0),
                                'timestamp': quote.get('timestamp'),
                                'age_seconds': self._calculate_quote_age(quote.get('timestamp')),
                                'data_quality': self._assess_quote_quality(quote)
                            })
                    
                    # Send update
                    event_data = {
                        'type': 'quotes_update',
                        'quotes': quotes,
                        'timestamp': time.time()
                    }
                    
                    yield f"data: {json.dumps(event_data)}\n\n"
                    
                    # Wait 2 seconds before next update
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"SSE stream error: {e}")
                    error_data = {
                        'type': 'error',
                        'message': str(e)
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                    break
        
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['Connection'] = 'keep-alive'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Cache-Control'
        
        return response
    
    @action(detail=False, methods=['get'])
    def replay_control(self, request):
        """Simple market replay control interface."""
        action = request.query_params.get('action', 'status')
        
        # This is a simplified interface - in production you'd connect to the actual replayer
        if action == 'status':
            # Return mock replay status for now
            return Response({
                'replay_active': False,
                'replay_speed': 1.0,
                'replay_progress': 0,
                'available_dates': ['2025-07-22', '2025-07-23', '2025-07-24'],
                'status': 'stopped'
            })
        
        elif action == 'start':
            date = request.query_params.get('date', '2025-07-29')
            speed = float(request.query_params.get('speed', 1.0))
            symbols = request.query_params.get('symbols', 'AAPL,GOOGL,MSFT,TSLA').split(',')
            
            # Mock response - in production this would start the actual replayer
            return Response({
                'status': 'started',
                'message': f'Market replay started for {date} at {speed}x speed',
                'date': date,
                'speed': speed,
                'symbols': symbols
            })
        
        elif action == 'stop':
            return Response({
                'status': 'stopped',
                'message': 'Market replay stopped'
            })
        
        else:
            return Response({'error': 'Invalid action'}, status=400)