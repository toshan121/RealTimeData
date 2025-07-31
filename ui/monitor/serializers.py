"""
Django REST Framework Serializers for Downloader API

Serializers for converting between Django models and JSON representations
for the downloader API endpoints.
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    DownloadConfiguration, 
    DownloadJob, 
    DownloadProgress,
    SystemConfiguration,
    DownloadHistory,
    DownloadAlert
)


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User objects."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class DownloadConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for DownloadConfiguration objects."""
    
    created_by = UserSerializer(read_only=True)
    job_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DownloadConfiguration
        fields = [
            'id', 'name', 'description', 'iqfeed_host', 'iqfeed_level1_port',
            'iqfeed_level2_port', 'iqfeed_admin_port', 'requests_per_second',
            'concurrent_connections', 'storage_type', 'base_data_dir', 
            'file_format', 'clickhouse_host', 'clickhouse_port',
            'clickhouse_database', 'buffer_size', 'batch_size', 
            'memory_limit_mb', 'is_active', 'is_default', 'created_by',
            'created_at', 'updated_at', 'job_count'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'job_count']
    
    def get_job_count(self, obj):
        """Get number of jobs using this configuration."""
        return obj.jobs.count()
    
    def validate_name(self, value):
        """Validate configuration name is unique."""
        if self.instance and self.instance.name == value:
            return value
        
        if DownloadConfiguration.objects.filter(name=value).exists():
            raise serializers.ValidationError("Configuration name must be unique.")
        
        return value
    
    def validate(self, data):
        """Validate configuration data."""
        # Ensure only one default configuration
        if data.get('is_default', False):
            if self.instance and self.instance.is_default:
                # Current instance is already default, allow it
                pass
            else:
                # Check if another default exists
                existing_default = DownloadConfiguration.objects.filter(is_default=True)
                if self.instance:
                    existing_default = existing_default.exclude(id=self.instance.id)
                
                if existing_default.exists():
                    raise serializers.ValidationError({
                        'is_default': 'Only one configuration can be set as default.'
                    })
        
        return data


class DownloadJobSerializer(serializers.ModelSerializer):
    """Serializer for DownloadJob objects."""
    
    created_by = UserSerializer(read_only=True)
    configuration_name = serializers.CharField(source='configuration.name', read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    symbol_count = serializers.ReadOnlyField()
    date_count = serializers.ReadOnlyField()
    total_downloads = serializers.ReadOnlyField()
    
    class Meta:
        model = DownloadJob
        fields = [
            'id', 'job_id', 'name', 'description', 'configuration', 
            'configuration_name', 'symbols', 'start_date', 'end_date',
            'data_types', 'priority', 'max_concurrent_symbols', 'max_retries',
            'continue_on_error', 'skip_existing', 'force_redownload',
            'status', 'scheduled_time', 'started_time', 'completed_time',
            'current_step', 'total_steps', 'progress_percentage',
            'current_message', 'error_message', 'retry_count',
            'result_data', 'created_by', 'created_at', 'updated_at',
            'duration_seconds', 'symbol_count', 'date_count', 'total_downloads'
        ]
        read_only_fields = [
            'id', 'created_by', 'created_at', 'updated_at', 'status',
            'started_time', 'completed_time', 'current_step', 'total_steps',
            'progress_percentage', 'current_message', 'error_message',
            'retry_count', 'result_data', 'duration_seconds', 'symbol_count',
            'date_count', 'total_downloads', 'configuration_name'
        ]
    
    def get_duration_seconds(self, obj):
        """Get job duration in seconds."""
        if obj.duration:
            return obj.duration.total_seconds()
        return None
    
    def validate_job_id(self, value):
        """Validate job ID is unique."""
        if self.instance and self.instance.job_id == value:
            return value
        
        if DownloadJob.objects.filter(job_id=value).exists():
            raise serializers.ValidationError("Job ID must be unique.")
        
        return value
    
    def validate_symbols(self, value):
        """Validate symbols list."""
        if not value or len(value) == 0:
            raise serializers.ValidationError("At least one symbol is required.")
        
        # Check for duplicates
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate symbols are not allowed.")
        
        # Validate symbol format (basic check)
        for symbol in value:
            if not isinstance(symbol, str) or not symbol.strip():
                raise serializers.ValidationError("All symbols must be non-empty strings.")
            
            if len(symbol) > 20:
                raise serializers.ValidationError("Symbol names cannot exceed 20 characters.")
        
        return value
    
    def validate_data_types(self, value):
        """Validate data types list."""
        valid_types = ['tick', 'level1', 'level2']
        
        if not value or len(value) == 0:
            raise serializers.ValidationError("At least one data type is required.")
        
        for data_type in value:
            if data_type not in valid_types:
                raise serializers.ValidationError(
                    f"Invalid data type: {data_type}. Valid types: {valid_types}"
                )
        
        return value
    
    def validate(self, data):
        """Validate job data."""
        # Validate date range
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if start_date and end_date:
            if start_date > end_date:
                raise serializers.ValidationError({
                    'start_date': 'Start date cannot be after end date.'
                })
            
            # Check date range isn't too large
            date_diff = (end_date - start_date).days
            if date_diff > 365:
                raise serializers.ValidationError({
                    'date_range': 'Date range cannot exceed 365 days.'
                })
        
        return data


class DownloadProgressSerializer(serializers.ModelSerializer):
    """Serializer for DownloadProgress objects."""
    
    job_id = serializers.CharField(source='job.job_id', read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = DownloadProgress
        fields = [
            'id', 'job', 'job_id', 'symbol', 'date', 'data_type', 'status',
            'records_downloaded', 'file_size_bytes', 'download_duration_seconds',
            'started_at', 'completed_at', 'error_message', 'retry_count',
            'output_file_path', 'created_at', 'updated_at', 'duration_seconds'
        ]
        read_only_fields = [
            'id', 'job_id', 'created_at', 'updated_at', 'duration_seconds'
        ]
    
    def get_duration_seconds(self, obj):
        """Calculate duration in seconds."""
        if obj.started_at and obj.completed_at:
            return (obj.completed_at - obj.started_at).total_seconds()
        return None


class SystemConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for SystemConfiguration objects."""
    
    updated_by = UserSerializer(read_only=True)
    
    class Meta:
        model = SystemConfiguration
        fields = [
            'id', 'max_concurrent_jobs', 'job_retention_days', 'auto_cleanup_enabled',
            'default_rate_limit', 'max_symbols_per_job', 'max_date_range_days',
            'progress_update_interval', 'health_check_interval',
            'enable_email_notifications', 'notification_email',
            'log_level', 'log_retention_days', 'updated_by', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_by', 'updated_at']


class DownloadHistorySerializer(serializers.ModelSerializer):
    """Serializer for DownloadHistory objects."""
    
    success_rate = serializers.SerializerMethodField()
    time_period = serializers.SerializerMethodField()
    
    class Meta:
        model = DownloadHistory
        fields = [
            'id', 'date', 'hour', 'total_jobs', 'completed_jobs', 'failed_jobs',
            'cancelled_jobs', 'total_downloads', 'successful_downloads',
            'failed_downloads', 'total_records_downloaded', 'total_bytes_downloaded',
            'avg_download_duration', 'avg_records_per_second', 'top_symbols',
            'created_at', 'success_rate', 'time_period'
        ]
        read_only_fields = ['id', 'created_at', 'success_rate', 'time_period']
    
    def get_success_rate(self, obj):
        """Calculate success rate percentage."""
        if obj.total_downloads > 0:
            return (obj.successful_downloads / obj.total_downloads) * 100.0
        return 0.0
    
    def get_time_period(self, obj):
        """Get formatted time period."""
        if obj.hour is not None:
            return f"{obj.date} {obj.hour:02d}:00"
        return str(obj.date)


class DownloadAlertSerializer(serializers.ModelSerializer):
    """Serializer for DownloadAlert objects."""
    
    job_id = serializers.CharField(source='job.job_id', read_only=True, allow_null=True)
    acknowledged_by_username = serializers.CharField(
        source='acknowledged_by.username', 
        read_only=True, 
        allow_null=True
    )
    
    class Meta:
        model = DownloadAlert
        fields = [
            'id', 'alert_type', 'severity', 'title', 'message', 'job',
            'job_id', 'is_read', 'is_acknowledged', 'acknowledged_by',
            'acknowledged_by_username', 'acknowledged_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'job_id', 'acknowledged_by', 'acknowledged_by_username',
            'acknowledged_at', 'created_at'
        ]


class JobSubmissionSerializer(serializers.Serializer):
    """Serializer for job submission requests."""
    
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    configuration_id = serializers.IntegerField()
    symbols = serializers.ListField(
        child=serializers.CharField(max_length=20),
        min_length=1,
        max_length=100
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    data_types = serializers.ListField(
        child=serializers.ChoiceField(choices=['tick', 'level1', 'level2']),
        min_length=1
    )
    priority = serializers.ChoiceField(choices=[1, 2, 3, 4], default=2)
    max_concurrent_symbols = serializers.IntegerField(min_value=1, max_value=10, default=2)
    max_retries = serializers.IntegerField(min_value=0, max_value=10, default=3)
    continue_on_error = serializers.BooleanField(default=True)
    skip_existing = serializers.BooleanField(default=True)
    force_redownload = serializers.BooleanField(default=False)
    scheduled_time = serializers.DateTimeField(required=False, allow_null=True)
    
    def validate_configuration_id(self, value):
        """Validate configuration exists and is active."""
        try:
            config = DownloadConfiguration.objects.get(id=value)
            if not config.is_active:
                raise serializers.ValidationError("Configuration is not active.")
            return value
        except DownloadConfiguration.DoesNotExist:
            raise serializers.ValidationError("Configuration does not exist.")
    
    def validate_symbols(self, value):
        """Validate symbols list."""
        # Remove duplicates while preserving order
        seen = set()
        unique_symbols = []
        for symbol in value:
            symbol = symbol.upper().strip()
            if symbol not in seen:
                seen.add(symbol)
                unique_symbols.append(symbol)
        
        return unique_symbols
    
    def validate(self, data):
        """Validate job submission data."""
        # Validate date range
        start_date = data['start_date']
        end_date = data['end_date']
        
        if start_date > end_date:
            raise serializers.ValidationError({
                'start_date': 'Start date cannot be after end date.'
            })
        
        # Check date range limits
        date_diff = (end_date - start_date).days
        if date_diff > 90:
            raise serializers.ValidationError({
                'date_range': 'Date range cannot exceed 90 days.'
            })
        
        # Check symbol count limits
        if len(data['symbols']) > 50:
            raise serializers.ValidationError({
                'symbols': 'Cannot submit more than 50 symbols at once.'
            })
        
        return data


class JobActionSerializer(serializers.Serializer):
    """Serializer for job action requests (cancel, retry, etc.)."""
    
    action = serializers.ChoiceField(choices=['cancel', 'retry', 'pause', 'resume'])
    reason = serializers.CharField(required=False, allow_blank=True)
    
    def validate_action(self, value):
        """Validate action is supported."""
        # For now, only cancel and retry are implemented
        if value not in ['cancel', 'retry']:
            raise serializers.ValidationError("Only 'cancel' and 'retry' actions are currently supported.")
        
        return value


class BulkJobActionSerializer(serializers.Serializer):
    """Serializer for bulk job actions."""
    
    job_ids = serializers.ListField(
        child=serializers.CharField(max_length=100),
        min_length=1,
        max_length=50
    )
    action = serializers.ChoiceField(choices=['cancel', 'retry', 'delete'])
    reason = serializers.CharField(required=False, allow_blank=True)
    
    def validate_job_ids(self, value):
        """Validate all job IDs exist."""
        existing_jobs = DownloadJob.objects.filter(job_id__in=value).values_list('job_id', flat=True)
        missing_jobs = set(value) - set(existing_jobs)
        
        if missing_jobs:
            raise serializers.ValidationError(
                f"Jobs not found: {', '.join(missing_jobs)}"
            )
        
        return value


class DownloadStatsSerializer(serializers.Serializer):
    """Serializer for download statistics."""
    
    # Job statistics
    total_jobs = serializers.IntegerField()
    pending_jobs = serializers.IntegerField()
    running_jobs = serializers.IntegerField()
    completed_jobs = serializers.IntegerField()
    failed_jobs = serializers.IntegerField()
    cancelled_jobs = serializers.IntegerField()
    
    # Download statistics
    total_downloads = serializers.IntegerField()
    successful_downloads = serializers.IntegerField()
    failed_downloads = serializers.IntegerField()
    success_rate = serializers.FloatField()
    
    # Performance metrics
    avg_job_duration = serializers.FloatField()
    avg_download_rate = serializers.FloatField()
    
    # Recent activity
    jobs_last_24h = serializers.IntegerField()
    downloads_last_24h = serializers.IntegerField()
    
    # Top symbols
    top_symbols = serializers.ListField(child=serializers.DictField())
    
    # System status
    active_configurations = serializers.IntegerField()
    storage_usage_gb = serializers.FloatField()
    
    # Timestamps
    stats_generated_at = serializers.DateTimeField()
    data_last_updated = serializers.DateTimeField()