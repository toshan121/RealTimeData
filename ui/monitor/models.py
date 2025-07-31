"""
Django Models for Hedge Fund Monitor

Models for download jobs, progress tracking, and configuration management.
Integrates with the standalone downloader system.
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import json
from typing import Dict, Any, List


class DownloadConfiguration(models.Model):
    """
    Model for storing download configurations.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    
    # Data source settings
    iqfeed_host = models.CharField(max_length=100, default='127.0.0.1')
    iqfeed_level1_port = models.IntegerField(default=5009)
    iqfeed_level2_port = models.IntegerField(default=5010)
    iqfeed_admin_port = models.IntegerField(default=9300)
    
    # Rate limiting
    requests_per_second = models.IntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    concurrent_connections = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    
    # Storage settings
    storage_type = models.CharField(
        max_length=20,
        choices=[
            ('file', 'File Storage'),
            ('clickhouse', 'ClickHouse'),
            ('both', 'File + ClickHouse')
        ],
        default='both'
    )
    base_data_dir = models.CharField(max_length=500, default='data')
    file_format = models.CharField(
        max_length=20,
        choices=[('csv', 'CSV'), ('parquet', 'Parquet'), ('json', 'JSON')],
        default='csv'
    )
    
    # ClickHouse settings
    clickhouse_host = models.CharField(max_length=100, default='localhost')
    clickhouse_port = models.IntegerField(default=9000)
    clickhouse_database = models.CharField(max_length=100, default='market_data')
    
    # Performance settings
    buffer_size = models.IntegerField(default=8192)
    batch_size = models.IntegerField(default=1000)
    memory_limit_mb = models.IntegerField(default=512)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'download_configurations'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Config: {self.name}"
    
    def to_downloader_config(self):
        """Convert to standalone downloader configuration."""
        try:
            from downloader.configuration.download_config import (
                DownloadConfiguration as StandaloneConfig,
                DataSourceConfig,
                StorageConfig,
                StorageType
            )
        except ImportError:
            # Create stub classes if downloader module is not available
            class StandaloneConfig:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)
            
            class DataSourceConfig:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)
            
            class StorageConfig:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)
            
            class StorageType:
                FILE = 'file'
                CLOUD = 'cloud'
        
        # Convert storage type
        storage_type_map = {
            'file': StorageType.FILE,
            'clickhouse': StorageType.CLICKHOUSE,
            'both': StorageType.BOTH
        }
        
        data_source = DataSourceConfig(
            iqfeed_host=self.iqfeed_host,
            iqfeed_level1_port=self.iqfeed_level1_port,
            iqfeed_level2_port=self.iqfeed_level2_port,
            iqfeed_admin_port=self.iqfeed_admin_port,
            requests_per_second=self.requests_per_second,
            concurrent_connections=self.concurrent_connections
        )
        
        storage = StorageConfig(
            storage_type=storage_type_map[self.storage_type],
            base_data_dir=self.base_data_dir,
            file_format=self.file_format,
            clickhouse_host=self.clickhouse_host,
            clickhouse_port=self.clickhouse_port,
            clickhouse_database=self.clickhouse_database
        )
        
        return StandaloneConfig(
            data_source=data_source,
            storage=storage,
            buffer_size=self.buffer_size,
            batch_size=self.batch_size,
            memory_limit_mb=self.memory_limit_mb
        )


class DownloadJob(models.Model):
    """
    Model for download jobs.
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ]
    
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Normal'),
        (3, 'High'),
        (4, 'Urgent')
    ]
    
    # Job identification
    job_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    
    # Job configuration
    configuration = models.ForeignKey(
        DownloadConfiguration,
        on_delete=models.CASCADE,
        related_name='jobs'
    )
    
    # Symbols and dates
    symbols = models.JSONField(help_text="List of stock symbols")
    start_date = models.DateField()
    end_date = models.DateField()
    data_types = models.JSONField(
        help_text="List of data types: tick, level1, level2",
        default=list
    )
    
    # Job settings
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=2)
    max_concurrent_symbols = models.IntegerField(default=2)
    max_retries = models.IntegerField(default=3)
    continue_on_error = models.BooleanField(default=True)
    skip_existing = models.BooleanField(default=True)
    force_redownload = models.BooleanField(default=False)
    
    # Status and timing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    scheduled_time = models.DateTimeField(null=True, blank=True)
    started_time = models.DateTimeField(null=True, blank=True)
    completed_time = models.DateTimeField(null=True, blank=True)
    
    # Progress and results
    current_step = models.IntegerField(default=0)
    total_steps = models.IntegerField(default=0)
    progress_percentage = models.FloatField(default=0.0)
    current_message = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    # Results (JSON stored)
    result_data = models.JSONField(null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'download_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['job_id']),
            models.Index(fields=['created_by', 'status'])
        ]
    
    def __str__(self):
        return f"Job: {self.job_id} ({self.status})"
    
    @property
    def duration(self):
        """Calculate job duration."""
        if self.started_time:
            end_time = self.completed_time or timezone.now()
            return end_time - self.started_time
        return None
    
    @property
    def symbol_count(self):
        """Get number of symbols in this job."""
        return len(self.symbols) if self.symbols else 0
    
    @property
    def date_count(self):
        """Get number of dates in this job."""
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0
    
    @property
    def total_downloads(self):
        """Calculate total number of downloads this job represents."""
        return self.symbol_count * self.date_count * len(self.data_types or [])
    
    def update_progress(self, step: int, message: str = "", percentage: float = None):
        """Update job progress."""
        self.current_step = step
        self.current_message = message
        
        if percentage is not None:
            self.progress_percentage = percentage
        elif self.total_steps > 0:
            self.progress_percentage = (step / self.total_steps) * 100.0
        
        self.updated_at = timezone.now()
        self.save(update_fields=['current_step', 'current_message', 'progress_percentage', 'updated_at'])
    
    def mark_started(self):
        """Mark job as started."""
        self.status = 'running'
        self.started_time = timezone.now()
        self.save(update_fields=['status', 'started_time'])
    
    def mark_completed(self, result_data: Dict[str, Any] = None):
        """Mark job as completed."""
        self.status = 'completed'
        self.completed_time = timezone.now()
        self.progress_percentage = 100.0
        
        if result_data:
            self.result_data = result_data
        
        self.save(update_fields=['status', 'completed_time', 'progress_percentage', 'result_data'])
    
    def mark_failed(self, error_message: str):
        """Mark job as failed."""
        self.status = 'failed'
        self.completed_time = timezone.now()
        self.error_message = error_message
        self.save(update_fields=['status', 'completed_time', 'error_message'])
    
    def mark_cancelled(self):
        """Mark job as cancelled."""
        self.status = 'cancelled'
        self.completed_time = timezone.now()
        self.save(update_fields=['status', 'completed_time'])
    
    def to_job_config(self):
        """Convert to standalone job configuration."""
        try:
            from downloader.configuration.download_config import DownloadJobConfig, DataType
        except ImportError:
            # Create stub classes if downloader module is not available
            class DownloadJobConfig:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)
            
            class DataType:
                TICK = 'tick'
                MINUTE = 'minute'
                INTERVAL = 'interval'
                DAILY = 'daily'
        
        # Convert data types
        data_types = []
        for dt in (self.data_types or []):
            if dt == 'tick':
                data_types.append(DataType.TICK)
            elif dt == 'level1':
                data_types.append(DataType.LEVEL1)
            elif dt == 'level2':
                data_types.append(DataType.LEVEL2)
        
        return DownloadJobConfig(
            job_id=self.job_id,
            job_name=self.name,
            symbols=self.symbols or [],
            start_date=self.start_date.strftime('%Y-%m-%d'),
            end_date=self.end_date.strftime('%Y-%m-%d'),
            data_types=data_types,
            max_concurrent_symbols=self.max_concurrent_symbols,
            max_retries_per_symbol=self.max_retries,
            continue_on_error=self.continue_on_error,
            skip_existing=self.skip_existing,
            force_redownload=self.force_redownload
        )


class DownloadProgress(models.Model):
    """
    Model for tracking detailed download progress.
    """
    job = models.ForeignKey(DownloadJob, on_delete=models.CASCADE, related_name='progress_entries')
    
    # Progress details
    symbol = models.CharField(max_length=20, blank=True)
    date = models.DateField(null=True, blank=True)
    data_type = models.CharField(max_length=20, blank=True)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('downloading', 'Downloading'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    
    # Metrics
    records_downloaded = models.IntegerField(default=0)
    file_size_bytes = models.BigIntegerField(default=0)
    download_duration_seconds = models.FloatField(default=0.0)
    
    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Error handling
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    # File information
    output_file_path = models.CharField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'download_progress'
        unique_together = ['job', 'symbol', 'date', 'data_type']
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['job', 'status']),
            models.Index(fields=['symbol', 'date'])
        ]
    
    def __str__(self):
        return f"Progress: {self.job.job_id} - {self.symbol} {self.date} {self.data_type}"


class SystemConfiguration(models.Model):
    """
    Model for system-wide downloader configuration.
    """
    # System settings
    max_concurrent_jobs = models.IntegerField(default=3)
    job_retention_days = models.IntegerField(default=30)
    auto_cleanup_enabled = models.BooleanField(default=True)
    
    # Default limits
    default_rate_limit = models.IntegerField(default=10)
    max_symbols_per_job = models.IntegerField(default=100)
    max_date_range_days = models.IntegerField(default=30)
    
    # Monitoring settings
    progress_update_interval = models.IntegerField(default=5)
    health_check_interval = models.IntegerField(default=30)
    enable_email_notifications = models.BooleanField(default=False)
    notification_email = models.EmailField(blank=True)
    
    # Log settings
    log_level = models.CharField(
        max_length=20,
        choices=[
            ('DEBUG', 'Debug'),
            ('INFO', 'Info'),
            ('WARNING', 'Warning'),
            ('ERROR', 'Error'),
            ('CRITICAL', 'Critical')
        ],
        default='INFO'
    )
    log_retention_days = models.IntegerField(default=7)
    
    # Metadata
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'system_configuration'
    
    def __str__(self):
        return f"System Config (updated {self.updated_at})"
    
    @classmethod
    def get_current(cls):
        """Get current system configuration."""
        config, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'updated_by_id': 1  # Assumes superuser with ID 1 exists
            }
        )
        return config


class DownloadHistory(models.Model):
    """
    Model for maintaining download history and statistics.
    """
    # Time period
    date = models.DateField()
    hour = models.IntegerField(null=True, blank=True)  # For hourly stats
    
    # Metrics
    total_jobs = models.IntegerField(default=0)
    completed_jobs = models.IntegerField(default=0)
    failed_jobs = models.IntegerField(default=0)
    cancelled_jobs = models.IntegerField(default=0)
    
    total_downloads = models.IntegerField(default=0)
    successful_downloads = models.IntegerField(default=0)
    failed_downloads = models.IntegerField(default=0)
    
    total_records_downloaded = models.BigIntegerField(default=0)
    total_bytes_downloaded = models.BigIntegerField(default=0)
    
    # Performance metrics
    avg_download_duration = models.FloatField(default=0.0)
    avg_records_per_second = models.FloatField(default=0.0)
    
    # Most active symbols
    top_symbols = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'download_history'
        unique_together = ['date', 'hour']
        ordering = ['-date', '-hour']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['date', 'hour'])
        ]
    
    def __str__(self):
        if self.hour is not None:
            return f"History: {self.date} {self.hour}:00"
        return f"History: {self.date}"


class DownloadAlert(models.Model):
    """
    Model for download alerts and notifications.
    """
    
    ALERT_TYPES = [
        ('job_failed', 'Job Failed'),
        ('job_completed', 'Job Completed'),
        ('high_failure_rate', 'High Failure Rate'),
        ('system_error', 'System Error'),
        ('quota_exceeded', 'Quota Exceeded')
    ]
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical')
    ]
    
    # Alert details
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Related objects
    job = models.ForeignKey(DownloadJob, on_delete=models.CASCADE, null=True, blank=True)
    
    # Status
    is_read = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='acknowledged_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'download_alerts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_type', 'created_at']),
            models.Index(fields=['severity', 'is_read']),
            models.Index(fields=['job'])
        ]
    
    def __str__(self):
        return f"Alert: {self.title} ({self.severity})"
    
    def acknowledge(self, user: User):
        """Acknowledge this alert."""
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save(update_fields=['is_acknowledged', 'acknowledged_by', 'acknowledged_at'])


class SystemHealthSnapshot(models.Model):
    """
    Model for storing system health snapshots for trending and analysis.
    """
    
    # Timestamp
    timestamp = models.DateTimeField()
    
    # Overall metrics
    health_score = models.FloatField(help_text="Overall health score 0-100")
    overall_status = models.CharField(
        max_length=20,
        choices=[
            ('HEALTHY', 'Healthy'),
            ('WARNING', 'Warning'),
            ('CRITICAL', 'Critical'),
            ('ERROR', 'Error')
        ]
    )
    money_safe = models.BooleanField(default=False)
    
    # System resource metrics
    cpu_percent = models.FloatField()
    memory_percent = models.FloatField()
    disk_percent = models.FloatField()
    network_latency_ms = models.FloatField(default=0)
    
    # Data flow metrics
    data_flow_rate = models.FloatField(default=0, help_text="Messages per minute")
    avg_latency_ms = models.FloatField(default=0)
    error_rate = models.FloatField(default=0)
    
    # Service health status (JSON)
    service_health = models.JSONField(default=dict)
    
    # Alert counts
    alert_count = models.IntegerField(default=0)
    critical_alert_count = models.IntegerField(default=0)
    
    # Raw metrics data (JSON)
    raw_metrics = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'system_health_snapshots'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['overall_status', 'timestamp']),
            models.Index(fields=['health_score'])
        ]
    
    def __str__(self):
        return f"Health Snapshot: {self.timestamp} - {self.overall_status} ({self.health_score:.1f})"


class ProductionAlert(models.Model):
    """
    Model for production system alerts with escalation capabilities.
    """
    
    ALERT_LEVELS = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
        ('URGENT', 'Urgent')
    ]
    
    ALERT_CATEGORIES = [
        ('system', 'System Resources'),
        ('iqfeed', 'IQFeed Connection'),
        ('kafka', 'Kafka Pipeline'),
        ('redis', 'Redis Cache'),
        ('clickhouse', 'ClickHouse Storage'),
        ('data_flow', 'Data Flow'),
        ('downloader', 'Data Downloader'),
        ('monitoring', 'Monitoring System')
    ]
    
    # Alert identification
    alert_id = models.CharField(max_length=100, unique=True)
    level = models.CharField(max_length=20, choices=ALERT_LEVELS)
    category = models.CharField(max_length=20, choices=ALERT_CATEGORIES)
    
    # Alert content
    title = models.CharField(max_length=200)
    message = models.TextField()
    component = models.CharField(max_length=50, blank=True)
    
    # Alert data
    alert_data = models.JSONField(default=dict, help_text="Additional alert data")
    threshold_value = models.FloatField(null=True, blank=True)
    current_value = models.FloatField(null=True, blank=True)
    
    # Status and timing
    is_active = models.BooleanField(default=True)
    first_triggered = models.DateTimeField()
    last_triggered = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Escalation
    escalation_level = models.IntegerField(default=0)
    last_escalated = models.DateTimeField(null=True, blank=True)
    escalation_count = models.IntegerField(default=0)
    
    # Acknowledgment
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_production_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledgment_note = models.TextField(blank=True)
    
    # Resolution
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_production_alerts'
    )
    resolution_note = models.TextField(blank=True)
    
    # Notification tracking
    notification_sent = models.BooleanField(default=False)
    notification_channels = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'production_alerts'
        ordering = ['-last_triggered']
        indexes = [
            models.Index(fields=['is_active', 'level']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['first_triggered']),
            models.Index(fields=['is_resolved', 'level'])
        ]
    
    def __str__(self):
        return f"Alert: {self.title} [{self.level}]"
    
    def acknowledge(self, user: User, note: str = ""):
        """Acknowledge this alert."""
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.acknowledgment_note = note
        self.save(update_fields=[
            'is_acknowledged', 'acknowledged_by', 
            'acknowledged_at', 'acknowledgment_note', 'updated_at'
        ])
    
    def resolve(self, user: User, note: str = ""):
        """Resolve this alert."""
        self.is_resolved = True
        self.is_active = False
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save(update_fields=[
            'is_resolved', 'is_active', 'resolved_by',
            'resolved_at', 'resolution_note', 'updated_at'
        ])
    
    def escalate(self):
        """Escalate this alert."""
        self.escalation_level += 1
        self.escalation_count += 1
        self.last_escalated = timezone.now()
        self.save(update_fields=[
            'escalation_level', 'escalation_count', 
            'last_escalated', 'updated_at'
        ])
    
    @property
    def duration(self):
        """Get alert duration."""
        end_time = self.resolved_at or timezone.now()
        return end_time - self.first_triggered
    
    @property
    def is_critical_trading(self):
        """Check if this is a critical trading alert."""
        trading_critical_categories = ['iqfeed', 'data_flow', 'clickhouse']
        return (self.level in ['CRITICAL', 'URGENT'] and 
                self.category in trading_critical_categories)


class ComponentStatus(models.Model):
    """
    Model for tracking individual component status over time.
    """
    
    COMPONENT_TYPES = [
        ('iqfeed', 'IQFeed'),
        ('kafka', 'Kafka'),
        ('redis', 'Redis'),
        ('clickhouse', 'ClickHouse'),
        ('downloader', 'Data Downloader'),
        ('data_pipeline', 'Data Pipeline'),
        ('system', 'System Resources')
    ]
    
    STATUS_CHOICES = [
        ('HEALTHY', 'Healthy'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
        ('ERROR', 'Error'),
        ('UNKNOWN', 'Unknown')
    ]
    
    # Component identification
    component_type = models.CharField(max_length=20, choices=COMPONENT_TYPES)
    component_name = models.CharField(max_length=100)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    status_message = models.TextField()
    
    # Metrics (JSON)
    metrics = models.JSONField(default=dict)
    
    # Performance data
    latency_ms = models.FloatField(null=True, blank=True)
    throughput = models.FloatField(null=True, blank=True)
    error_count = models.IntegerField(default=0)
    uptime_seconds = models.IntegerField(null=True, blank=True)
    
    # Timestamp
    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'component_status'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['component_type', 'timestamp']),
            models.Index(fields=['status', 'timestamp']),
            models.Index(fields=['component_name', 'timestamp'])
        ]
    
    def __str__(self):
        return f"{self.component_name}: {self.status} at {self.timestamp}"


class PerformanceMetric(models.Model):
    """
    Model for storing performance metrics for trending and analysis.
    """
    
    METRIC_TYPES = [
        ('cpu_usage', 'CPU Usage %'),
        ('memory_usage', 'Memory Usage %'),
        ('disk_usage', 'Disk Usage %'),
        ('network_latency', 'Network Latency ms'),
        ('data_flow_rate', 'Data Flow Rate'),
        ('kafka_latency', 'Kafka Latency ms'),
        ('redis_latency', 'Redis Latency ms'),
        ('clickhouse_latency', 'ClickHouse Latency ms'),
        ('error_rate', 'Error Rate %'),
        ('throughput', 'Throughput')
    ]
    
    # Metric identification
    metric_type = models.CharField(max_length=30, choices=METRIC_TYPES)
    component = models.CharField(max_length=50, blank=True)
    
    # Metric value
    value = models.FloatField()
    unit = models.CharField(max_length=20, blank=True)
    
    # Additional context
    tags = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    
    # Timestamp
    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'performance_metrics'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['metric_type', 'timestamp']),
            models.Index(fields=['component', 'metric_type', 'timestamp']),
            models.Index(fields=['timestamp'])
        ]
    
    def __str__(self):
        return f"{self.metric_type}: {self.value} {self.unit} at {self.timestamp}"


class AlertEscalationRule(models.Model):
    """
    Model for defining alert escalation rules.
    """
    
    # Rule identification
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    # Conditions
    alert_level = models.CharField(max_length=20, choices=ProductionAlert.ALERT_LEVELS)
    alert_category = models.CharField(
        max_length=20, 
        choices=ProductionAlert.ALERT_CATEGORIES,
        blank=True
    )
    component_pattern = models.CharField(max_length=100, blank=True)
    
    # Escalation timing
    initial_delay_minutes = models.IntegerField(default=5)
    escalation_interval_minutes = models.IntegerField(default=15)
    max_escalations = models.IntegerField(default=3)
    
    # Notification settings
    notification_channels = models.JSONField(default=list)
    escalation_recipients = models.ManyToManyField(
        User,
        related_name='escalation_rules',
        blank=True
    )
    
    # Additional conditions (JSON)
    conditions = models.JSONField(default=dict)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'alert_escalation_rules'
        ordering = ['name']
    
    def __str__(self):
        return f"Escalation Rule: {self.name}"
    
    def matches_alert(self, alert: ProductionAlert) -> bool:
        """Check if this rule matches the given alert."""
        # Check level
        if self.alert_level != alert.level:
            return False
        
        # Check category
        if self.alert_category and self.alert_category != alert.category:
            return False
        
        # Check component pattern
        if self.component_pattern:
            import re
            if not re.search(self.component_pattern, alert.component or ''):
                return False
        
        return True


class MonitoringDashboard(models.Model):
    """
    Model for storing custom dashboard configurations.
    """
    
    # Dashboard identification
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True)
    
    # Configuration
    layout = models.JSONField(default=dict, help_text="Dashboard layout configuration")
    widgets = models.JSONField(default=list, help_text="Widget configurations")
    refresh_interval = models.IntegerField(default=30, help_text="Refresh interval in seconds")
    
    # Access control
    is_public = models.BooleanField(default=False)
    allowed_users = models.ManyToManyField(User, related_name='allowed_dashboards', blank=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'monitoring_dashboards'
        ordering = ['name']
    
    def __str__(self):
        return f"Dashboard: {self.name}"


class SystemMaintenanceWindow(models.Model):
    """
    Model for tracking system maintenance windows.
    """
    
    # Maintenance details
    title = models.CharField(max_length=200)
    description = models.TextField()
    
    # Timing
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Affected components
    affected_components = models.JSONField(default=list)
    
    # Status
    is_active = models.BooleanField(default=True)
    suppress_alerts = models.BooleanField(default=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'system_maintenance_windows'
        ordering = ['-start_time']
    
    def __str__(self):
        return f"Maintenance: {self.title} ({self.start_time})"
    
    @property
    def is_current(self):
        """Check if maintenance window is currently active."""
        now = timezone.now()
        return self.is_active and self.start_time <= now <= self.end_time
