"""
Downloader System Exceptions

Custom exception classes for the standalone downloader system.
Following RULES.md: Fail fast and loud with structured error reporting.
"""

from typing import Optional, Dict, Any
from datetime import datetime


class DownloaderError(Exception):
    """Base exception for all downloader system errors."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/API responses."""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'context': self.context,
            'timestamp': self.timestamp.isoformat()
        }


class ConfigurationError(DownloaderError):
    """Raised when downloader configuration is invalid."""
    
    def __init__(self, message: str, config_key: Optional[str] = None, 
                 config_value: Any = None):
        context = {}
        if config_key:
            context['config_key'] = config_key
        if config_value is not None:
            context['config_value'] = str(config_value)
        
        super().__init__(message, context)
        self.config_key = config_key
        self.config_value = config_value


class DownloadJobError(DownloaderError):
    """Raised when download job operations fail."""
    
    def __init__(self, message: str, job_id: Optional[str] = None, 
                 symbol: Optional[str] = None, date: Optional[str] = None):
        context = {}
        if job_id:
            context['job_id'] = job_id
        if symbol:
            context['symbol'] = symbol
        if date:
            context['date'] = date
            
        super().__init__(message, context)
        self.job_id = job_id
        self.symbol = symbol
        self.date = date


class ProgressTrackingError(DownloaderError):
    """Raised when progress tracking operations fail."""
    
    def __init__(self, message: str, tracker_id: Optional[str] = None,
                 operation: Optional[str] = None):
        context = {}
        if tracker_id:
            context['tracker_id'] = tracker_id
        if operation:
            context['operation'] = operation
            
        super().__init__(message, context)
        self.tracker_id = tracker_id
        self.operation = operation


class ValidationError(DownloaderError):
    """Raised when data validation fails."""
    
    def __init__(self, message: str, validation_type: Optional[str] = None,
                 expected: Any = None, actual: Any = None):
        context = {}
        if validation_type:
            context['validation_type'] = validation_type
        if expected is not None:
            context['expected'] = str(expected)
        if actual is not None:
            context['actual'] = str(actual)
            
        super().__init__(message, context)
        self.validation_type = validation_type
        self.expected = expected
        self.actual = actual


class ConnectionError(DownloaderError):
    """Raised when connection to data sources fails."""
    
    def __init__(self, message: str, host: Optional[str] = None, 
                 port: Optional[int] = None, service: Optional[str] = None):
        context = {}
        if host:
            context['host'] = host
        if port:
            context['port'] = port
        if service:
            context['service'] = service
            
        super().__init__(message, context)
        self.host = host
        self.port = port
        self.service = service


class RateLimitError(DownloaderError):
    """Raised when rate limits are exceeded."""
    
    def __init__(self, message: str, limit: Optional[int] = None,
                 window: Optional[int] = None, retry_after: Optional[int] = None):
        context = {}
        if limit:
            context['limit'] = limit
        if window:
            context['window'] = window
        if retry_after:
            context['retry_after'] = retry_after
            
        super().__init__(message, context)
        self.limit = limit
        self.window = window
        self.retry_after = retry_after


class DataIntegrityError(DownloaderError):
    """Raised when downloaded data fails integrity checks."""
    
    def __init__(self, message: str, symbol: Optional[str] = None,
                 date: Optional[str] = None, data_type: Optional[str] = None,
                 expected_records: Optional[int] = None, 
                 actual_records: Optional[int] = None):
        context = {}
        if symbol:
            context['symbol'] = symbol
        if date:
            context['date'] = date
        if data_type:
            context['data_type'] = data_type
        if expected_records is not None:
            context['expected_records'] = expected_records
        if actual_records is not None:
            context['actual_records'] = actual_records
            
        super().__init__(message, context)
        self.symbol = symbol
        self.date = date
        self.data_type = data_type
        self.expected_records = expected_records
        self.actual_records = actual_records


class StorageError(DownloaderError):
    """Raised when data storage operations fail."""
    
    def __init__(self, message: str, storage_type: Optional[str] = None,
                 file_path: Optional[str] = None, table_name: Optional[str] = None):
        context = {}
        if storage_type:
            context['storage_type'] = storage_type
        if file_path:
            context['file_path'] = file_path
        if table_name:
            context['table_name'] = table_name
            
        super().__init__(message, context)
        self.storage_type = storage_type
        self.file_path = file_path
        self.table_name = table_name