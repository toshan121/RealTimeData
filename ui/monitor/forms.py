"""
Django Forms for Monitor App
"""
from django import forms
from .models import DownloadJob, DownloadConfiguration


class JobSubmissionForm(forms.ModelForm):
    """Form for submitting new download jobs"""
    
    class Meta:
        model = DownloadJob
        fields = ['configuration', 'symbols', 'start_date', 'end_date', 
                  'data_types', 'priority', 'scheduled_time']
        widgets = {
            'symbols': forms.Textarea(attrs={'rows': 3}),
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'scheduled_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'data_types': forms.CheckboxSelectMultiple(),
        }


class ConfigurationForm(forms.ModelForm):
    """Form for creating/editing download configurations"""
    
    class Meta:
        model = DownloadConfiguration
        fields = ['name', 'description', 'is_active', 'is_default',
                  'iqfeed_host', 'iqfeed_level1_port', 'iqfeed_level2_port', 
                  'iqfeed_admin_port', 'requests_per_second', 'concurrent_connections',
                  'storage_type', 'base_data_dir', 'file_format', 'clickhouse_host', 
                  'clickhouse_port', 'clickhouse_database', 'buffer_size', 
                  'batch_size', 'memory_limit_mb']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }