"""
Standalone Historical Data Downloader System

This module provides a comprehensive standalone downloader system that integrates 
with Django for professional management of historical market data downloads.

Key Components:
- AutoDownloaderService: Core standalone downloader service
- DownloadConfiguration: Flexible configuration management  
- DownloadJobManager: Background job management and queue processing
- ProgressTracker: Real-time progress monitoring and status updates
- ErrorHandler: Robust error handling and recovery mechanisms

The system is designed to be:
- Framework agnostic (no UI coupling)
- Scalable (supports concurrent downloads)
- Reliable (comprehensive error handling)
- Monitorable (real-time progress tracking)
- Professional (Django integration for management interface)
"""

__version__ = "1.0.0"
__author__ = "Claude Code"

from .services.auto_downloader_service import AutoDownloaderService
from .services.download_job_manager import DownloadJobManager
from .services.progress_tracker import ProgressTracker
from .configuration.download_config import DownloadConfiguration
from .exceptions import (
    DownloaderError,
    ConfigurationError,
    DownloadJobError,
    ProgressTrackingError
)

__all__ = [
    'AutoDownloaderService',
    'DownloadJobManager', 
    'ProgressTracker',
    'DownloadConfiguration',
    'DownloaderError',
    'ConfigurationError',
    'DownloadJobError',
    'ProgressTrackingError'
]