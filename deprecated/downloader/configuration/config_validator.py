"""
Configuration Validator

Validates downloader configurations to ensure they are correct
and all required resources are available.

Following Fail Fast and Loud: Validates everything upfront before starting downloads.
"""

import socket
import redis
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging

from .download_config import DownloadConfiguration, DataSourceConfig, StorageConfig
from ..exceptions import ConfigurationError, ConnectionError


logger = logging.getLogger(__name__)


class ConfigurationValidator:
    """
    Validates downloader configurations to ensure they are correct
    and all required resources are accessible.
    """
    
    def __init__(self, config: DownloadConfiguration):
        self.config = config
        self.validation_results: List[Dict[str, Any]] = []
    
    def validate_all(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Perform comprehensive validation of all configuration aspects.
        
        Returns:
            Tuple of (is_valid, validation_results)
        """
        self.validation_results = []
        
        # Validate each component
        self._validate_data_source()
        self._validate_storage()
        self._validate_performance_settings()
        self._validate_monitoring_settings()
        
        # Check if any validation failed
        is_valid = not any(result['status'] == 'error' for result in self.validation_results)
        
        return is_valid, self.validation_results
    
    def _validate_data_source(self):
        """Validate data source configuration and connectivity."""
        logger.info("Validating data source configuration")
        
        config = self.config.data_source
        
        # Check IQFeed credentials
        if not config.iqfeed_username or not config.iqfeed_password:
            self.validation_results.append({
                'component': 'data_source',
                'check': 'credentials',
                'status': 'error',
                'message': 'IQFeed credentials not configured',
                'details': {
                    'username_set': bool(config.iqfeed_username),
                    'password_set': bool(config.iqfeed_password)
                }
            })
        else:
            self.validation_results.append({
                'component': 'data_source', 
                'check': 'credentials',
                'status': 'success',
                'message': 'IQFeed credentials configured'
            })
        
        # Test IQFeed connectivity
        self._test_iqfeed_connectivity(config)
        
        # Validate rate limiting settings
        if config.requests_per_second <= 0:
            self.validation_results.append({
                'component': 'data_source',
                'check': 'rate_limiting',
                'status': 'error',
                'message': 'Invalid requests per second setting',
                'details': {'requests_per_second': config.requests_per_second}
            })
        elif config.requests_per_second > 100:
            self.validation_results.append({
                'component': 'data_source',
                'check': 'rate_limiting', 
                'status': 'warning',
                'message': 'High requests per second may hit rate limits',
                'details': {'requests_per_second': config.requests_per_second}
            })
        else:
            self.validation_results.append({
                'component': 'data_source',
                'check': 'rate_limiting',
                'status': 'success',
                'message': 'Rate limiting settings validated'
            })
    
    def _test_iqfeed_connectivity(self, config: DataSourceConfig):
        """Test connectivity to IQFeed ports."""
        ports = {
            'level1': config.iqfeed_level1_port,
            'level2': config.iqfeed_level2_port,
            'admin': config.iqfeed_admin_port
        }
        
        for port_name, port in ports.items():
            try:
                # Test socket connection with timeout
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)  # 5 second timeout for validation
                
                result = sock.connect_ex((config.iqfeed_host, port))
                sock.close()
                
                if result == 0:
                    self.validation_results.append({
                        'component': 'data_source',
                        'check': f'connectivity_{port_name}',
                        'status': 'success',
                        'message': f'IQFeed {port_name} port accessible',
                        'details': {'host': config.iqfeed_host, 'port': port}
                    })
                else:
                    self.validation_results.append({
                        'component': 'data_source',
                        'check': f'connectivity_{port_name}',
                        'status': 'warning',
                        'message': f'IQFeed {port_name} port not accessible',
                        'details': {
                            'host': config.iqfeed_host, 
                            'port': port,
                            'error_code': result
                        }
                    })
                    
            except Exception as e:
                self.validation_results.append({
                    'component': 'data_source',
                    'check': f'connectivity_{port_name}',
                    'status': 'error',
                    'message': f'Failed to test IQFeed {port_name} connectivity',
                    'details': {
                        'host': config.iqfeed_host,
                        'port': port,
                        'error': str(e)
                    }
                })
    
    def _validate_storage(self):
        """Validate storage configuration and accessibility."""
        logger.info("Validating storage configuration")
        
        config = self.config.storage
        
        # Validate file storage
        self._validate_file_storage(config)
        
        # Validate ClickHouse if configured
        if config.storage_type.value in ['clickhouse', 'both']:
            self._validate_clickhouse_storage(config)
        
        # Validate Redis if configured
        self._validate_redis_storage(config)
    
    def _validate_file_storage(self, config: StorageConfig):
        """Validate file storage settings."""
        try:
            # Check if base directory exists and is writable
            if not config.base_data_dir.exists():
                config.base_data_dir.mkdir(parents=True, exist_ok=True)
            
            # Test write permissions by creating a test file
            test_file = config.base_data_dir / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                
                self.validation_results.append({
                    'component': 'storage',
                    'check': 'file_storage',
                    'status': 'success',
                    'message': 'File storage directory accessible and writable',
                    'details': {'base_dir': str(config.base_data_dir)}
                })
                
            except PermissionError:
                self.validation_results.append({
                    'component': 'storage',
                    'check': 'file_storage',
                    'status': 'error',
                    'message': 'File storage directory not writable',
                    'details': {'base_dir': str(config.base_data_dir)}
                })
                
        except Exception as e:
            self.validation_results.append({
                'component': 'storage',
                'check': 'file_storage',
                'status': 'error',
                'message': f'File storage validation failed: {e}',
                'details': {'base_dir': str(config.base_data_dir)}
            })
    
    def _validate_clickhouse_storage(self, config: StorageConfig):
        """Validate ClickHouse connectivity and configuration."""
        try:
            # Test ClickHouse connectivity (would use actual client in real implementation)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            
            result = sock.connect_ex((config.clickhouse_host, config.clickhouse_port))
            sock.close()
            
            if result == 0:
                self.validation_results.append({
                    'component': 'storage',
                    'check': 'clickhouse_connectivity',
                    'status': 'success',
                    'message': 'ClickHouse server accessible',
                    'details': {
                        'host': config.clickhouse_host,
                        'port': config.clickhouse_port,
                        'database': config.clickhouse_database
                    }
                })
            else:
                self.validation_results.append({
                    'component': 'storage',
                    'check': 'clickhouse_connectivity',
                    'status': 'warning',
                    'message': 'ClickHouse server not accessible',
                    'details': {
                        'host': config.clickhouse_host,
                        'port': config.clickhouse_port,
                        'error_code': result
                    }
                })
                
        except Exception as e:
            self.validation_results.append({
                'component': 'storage',
                'check': 'clickhouse_connectivity',
                'status': 'error',
                'message': f'ClickHouse validation failed: {e}',
                'details': {
                    'host': config.clickhouse_host,
                    'port': config.clickhouse_port
                }
            })
    
    def _validate_redis_storage(self, config: StorageConfig):
        """Validate Redis connectivity and configuration."""
        try:
            # Test Redis connectivity
            redis_client = redis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                db=config.redis_db,
                password=config.redis_password,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            
            # Test connection with ping
            redis_client.ping()
            
            self.validation_results.append({
                'component': 'storage',
                'check': 'redis_connectivity',
                'status': 'success',
                'message': 'Redis server accessible',
                'details': {
                    'host': config.redis_host,
                    'port': config.redis_port,
                    'db': config.redis_db
                }
            })
            
        except redis.ConnectionError as e:
            self.validation_results.append({
                'component': 'storage',
                'check': 'redis_connectivity',
                'status': 'warning',
                'message': 'Redis server not accessible',
                'details': {
                    'host': config.redis_host,
                    'port': config.redis_port,
                    'error': str(e)
                }
            })
            
        except Exception as e:
            self.validation_results.append({
                'component': 'storage',
                'check': 'redis_connectivity',
                'status': 'error',
                'message': f'Redis validation failed: {e}',
                'details': {
                    'host': config.redis_host,
                    'port': config.redis_port
                }
            })
    
    def _validate_performance_settings(self):
        """Validate performance and resource settings."""
        logger.info("Validating performance settings")
        
        # Validate memory limits
        if self.config.memory_limit_mb < 128:
            self.validation_results.append({
                'component': 'performance',
                'check': 'memory_limit',
                'status': 'error',
                'message': 'Memory limit too low (minimum 128MB required)',
                'details': {'memory_limit_mb': self.config.memory_limit_mb}
            })
        elif self.config.memory_limit_mb > 8192:
            self.validation_results.append({
                'component': 'performance',
                'check': 'memory_limit',
                'status': 'warning',
                'message': 'High memory limit configured',
                'details': {'memory_limit_mb': self.config.memory_limit_mb}
            })
        else:
            self.validation_results.append({
                'component': 'performance',
                'check': 'memory_limit',
                'status': 'success',
                'message': 'Memory limit settings validated'
            })
        
        # Validate batch size
        if self.config.batch_size <= 0:
            self.validation_results.append({
                'component': 'performance',
                'check': 'batch_size',
                'status': 'error',
                'message': 'Batch size must be positive',
                'details': {'batch_size': self.config.batch_size}
            })
        elif self.config.batch_size > 10000:
            self.validation_results.append({
                'component': 'performance',
                'check': 'batch_size',
                'status': 'warning',
                'message': 'Very large batch size may cause memory issues',
                'details': {'batch_size': self.config.batch_size}
            })
        else:
            self.validation_results.append({
                'component': 'performance',
                'check': 'batch_size',
                'status': 'success',
                'message': 'Batch size settings validated'
            })
    
    def _validate_monitoring_settings(self):
        """Validate monitoring and logging settings."""
        logger.info("Validating monitoring settings")
        
        # Validate log file path
        if self.config.log_file:
            try:
                log_dir = self.config.log_file.parent
                log_dir.mkdir(parents=True, exist_ok=True)
                
                # Test write permissions
                test_log = log_dir / ".log_test"
                test_log.write_text("test")
                test_log.unlink()
                
                self.validation_results.append({
                    'component': 'monitoring',
                    'check': 'log_file',
                    'status': 'success',
                    'message': 'Log file path accessible and writable',
                    'details': {'log_file': str(self.config.log_file)}
                })
                
            except Exception as e:
                self.validation_results.append({
                    'component': 'monitoring',
                    'check': 'log_file',
                    'status': 'error',
                    'message': f'Log file path validation failed: {e}',
                    'details': {'log_file': str(self.config.log_file)}
                })
        
        # Validate update intervals
        if self.config.progress_update_interval <= 0:
            self.validation_results.append({
                'component': 'monitoring',
                'check': 'update_intervals',
                'status': 'error',
                'message': 'Progress update interval must be positive',
                'details': {'progress_update_interval': self.config.progress_update_interval}
            })
        else:
            self.validation_results.append({
                'component': 'monitoring',
                'check': 'update_intervals',
                'status': 'success',
                'message': 'Monitoring intervals validated'
            })
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of validation results."""
        if not self.validation_results:
            return {'status': 'not_validated', 'message': 'Validation not performed'}
        
        error_count = sum(1 for r in self.validation_results if r['status'] == 'error')
        warning_count = sum(1 for r in self.validation_results if r['status'] == 'warning')
        success_count = sum(1 for r in self.validation_results if r['status'] == 'success')
        
        overall_status = 'success' if error_count == 0 else 'error'
        
        return {
            'status': overall_status,
            'total_checks': len(self.validation_results),
            'errors': error_count,
            'warnings': warning_count,
            'successes': success_count,
            'is_valid': error_count == 0,
            'details': self.validation_results
        }