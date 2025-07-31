"""
Download Configuration System

Flexible configuration management for different download scenarios,
data sources, and storage backends.

Following YAGNI principles: Only implements currently needed configuration options.
Following Single Responsibility: Each config class handles one aspect of configuration.
"""

import os
import yaml
import json
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum

from ..exceptions import ConfigurationError


class DataType(Enum):
    """Supported data types for download."""
    TICK = "tick"
    LEVEL1 = "level1" 
    LEVEL2 = "level2"
    BARS = "bars"


class StorageType(Enum):
    """Supported storage backends."""
    FILE = "file"
    CLICKHOUSE = "clickhouse"
    REDIS = "redis"
    BOTH = "both"  # File + ClickHouse


@dataclass
class DataSourceConfig:
    """Configuration for data source connections."""
    
    # IQFeed configuration
    iqfeed_host: str = "127.0.0.1"
    iqfeed_level1_port: int = 5009
    iqfeed_level2_port: int = 5010
    iqfeed_admin_port: int = 9300
    iqfeed_username: Optional[str] = None
    iqfeed_password: Optional[str] = None
    
    # Connection settings
    connection_timeout: int = 30
    retry_attempts: int = 3
    retry_delay: int = 5
    
    # Rate limiting
    requests_per_second: int = 10
    concurrent_connections: int = 3
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        # Load credentials from environment if not provided
        # Try multiple environment variable names for flexibility
        if not self.iqfeed_username:
            self.iqfeed_username = (
                os.getenv('IQFEED_USER') or 
                os.getenv('IQFEED_USERNAME') or 
                os.getenv('IQ_FEED_USER') or
                os.getenv('IQ_USERNAME')
            )
            
        if not self.iqfeed_password:
            self.iqfeed_password = (
                os.getenv('IQFEED_PASS') or 
                os.getenv('IQFEED_PASSWORD') or 
                os.getenv('IQ_FEED_PASS') or
                os.getenv('IQ_PASSWORD')
            )
            
        # Validate required fields with enhanced error message
        missing_credentials = []
        if not self.iqfeed_username:
            missing_credentials.append("username")
        if not self.iqfeed_password:
            missing_credentials.append("password")
            
        if missing_credentials:
            env_vars_tried = [
                'IQFEED_USER/IQFEED_USERNAME/IQ_FEED_USER/IQ_USERNAME',
                'IQFEED_PASS/IQFEED_PASSWORD/IQ_FEED_PASS/IQ_PASSWORD'
            ]
            raise ConfigurationError(
                f"IQFeed credentials not configured. Missing: {', '.join(missing_credentials)}. "
                f"Set environment variables: {', '.join(env_vars_tried)} or provide them directly in config.",
                config_key="iqfeed_credentials",
                config_value=f"Missing: {missing_credentials}"
            )
    
    def get_credential_status(self) -> Dict[str, Any]:
        """Get detailed credential status for debugging."""
        env_vars_checked = {
            'IQFEED_USER': os.getenv('IQFEED_USER'),
            'IQFEED_USERNAME': os.getenv('IQFEED_USERNAME'),
            'IQ_FEED_USER': os.getenv('IQ_FEED_USER'),
            'IQ_USERNAME': os.getenv('IQ_USERNAME'),
            'IQFEED_PASS': '***' if os.getenv('IQFEED_PASS') else None,
            'IQFEED_PASSWORD': '***' if os.getenv('IQFEED_PASSWORD') else None,
            'IQ_FEED_PASS': '***' if os.getenv('IQ_FEED_PASS') else None,
            'IQ_PASSWORD': '***' if os.getenv('IQ_PASSWORD') else None,
        }
        
        return {
            'username_configured': bool(self.iqfeed_username),
            'password_configured': bool(self.iqfeed_password),
            'environment_variables': env_vars_checked,
            'credentials_complete': bool(self.iqfeed_username and self.iqfeed_password)
        }


@dataclass 
class StorageConfig:
    """Configuration for data storage backends."""
    
    # Primary storage type
    storage_type: StorageType = StorageType.BOTH
    
    # File storage settings
    base_data_dir: Path = field(default_factory=lambda: Path("data"))
    file_format: str = "csv"  # csv, parquet, json
    compression: Optional[str] = None  # gzip, bz2, xz
    
    # ClickHouse settings
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 9000
    clickhouse_database: str = "market_data"
    clickhouse_username: str = "default"
    clickhouse_password: str = ""
    
    # Redis settings (for caching/metadata)
    redis_host: str = "127.0.0.1"
    redis_port: int = 6380
    redis_db: int = 0
    redis_password: Optional[str] = None
    
    # Data retention
    file_retention_days: int = 30
    clickhouse_retention_days: int = 365
    
    def __post_init__(self):
        """Validate and normalize storage configuration."""
        # Convert string paths to Path objects
        if isinstance(self.base_data_dir, str):
            self.base_data_dir = Path(self.base_data_dir)
            
        # Create data directory if it doesn't exist
        self.base_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate storage type
        if isinstance(self.storage_type, str):
            try:
                self.storage_type = StorageType(self.storage_type.lower())
            except ValueError:
                raise ConfigurationError(
                    f"Invalid storage type: {self.storage_type}",
                    config_key="storage_type"
                )


@dataclass
class DownloadJobConfig:
    """Configuration for individual download jobs."""
    
    # Job identification
    job_id: Optional[str] = None
    job_name: Optional[str] = None
    
    # Symbols and dates
    symbols: List[str] = field(default_factory=list)
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None    # YYYY-MM-DD format
    
    # Data types to download
    data_types: List[DataType] = field(default_factory=lambda: [DataType.TICK, DataType.LEVEL1])
    
    # Processing options
    validate_data: bool = True
    skip_existing: bool = True
    force_redownload: bool = False
    
    # Concurrency settings  
    max_concurrent_symbols: int = 2
    max_concurrent_dates: int = 1
    
    # Error handling
    continue_on_error: bool = True
    max_retries_per_symbol: int = 3
    
    def __post_init__(self):
        """Validate job configuration."""
        # Validate symbols
        if not self.symbols:
            raise ConfigurationError(
                "No symbols specified for download job",
                config_key="symbols"
            )
            
        # Validate date range
        if self.start_date and self.end_date:
            try:
                start = datetime.strptime(self.start_date, "%Y-%m-%d")
                end = datetime.strptime(self.end_date, "%Y-%m-%d")
                
                if start > end:
                    raise ConfigurationError(
                        "Start date cannot be after end date",
                        config_key="date_range"
                    )
                    
                if end > datetime.now():
                    raise ConfigurationError(
                        "End date cannot be in the future",
                        config_key="end_date"
                    )
                    
            except ValueError as e:
                raise ConfigurationError(
                    f"Invalid date format: {e}",
                    config_key="date_format"
                )
        
        # Convert string data types to enum
        if self.data_types and isinstance(self.data_types[0], str):
            try:
                self.data_types = [DataType(dt.lower()) for dt in self.data_types]
            except ValueError as e:
                raise ConfigurationError(
                    f"Invalid data type: {e}",
                    config_key="data_types"
                )
        
        # Generate job ID if not provided
        if not self.job_id:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            symbol_count = len(self.symbols)
            self.job_id = f"download_{symbol_count}symbols_{timestamp}"


@dataclass
class DownloadConfiguration:
    """Main configuration class for the downloader system."""
    
    # Component configurations
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig) 
    
    # Global settings
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    
    # Performance tuning
    buffer_size: int = 8192
    batch_size: int = 1000
    memory_limit_mb: int = 512
    
    # Monitoring
    enable_progress_tracking: bool = True
    progress_update_interval: int = 5  # seconds
    enable_health_checks: bool = True
    health_check_interval: int = 30    # seconds
    
    def __post_init__(self):
        """Validate overall configuration."""
        # Validate log level
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            raise ConfigurationError(
                f"Invalid log level: {self.log_level}",
                config_key="log_level"
            )
        self.log_level = self.log_level.upper()
        
        # Setup log file path if not provided
        if not self.log_file:
            self.log_file = self.storage.base_data_dir / "logs" / "downloader.log"
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_file(cls, config_path: Union[str, Path]) -> 'DownloadConfiguration':
        """Load configuration from YAML or JSON file."""
        config_path = Path(config_path)
        
        if not config_path.exists():
            raise ConfigurationError(
                f"Configuration file not found: {config_path}",
                config_key="config_file"
            )
        
        try:
            with open(config_path, 'r') as f:
                if config_path.suffix.lower() in ['.yml', '.yaml']:
                    data = yaml.safe_load(f)
                elif config_path.suffix.lower() == '.json':
                    data = json.load(f)
                else:
                    raise ConfigurationError(
                        f"Unsupported config file format: {config_path.suffix}",
                        config_key="config_format"
                    )
            
            return cls.from_dict(data)
            
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ConfigurationError(
                f"Failed to parse configuration file: {e}",
                config_key="config_parsing"
            )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloadConfiguration':
        """Create configuration from dictionary."""
        try:
            # Custom deserialization to handle Path objects
            def deserialize_path_fields(obj_dict, path_fields):
                """Convert string paths back to Path objects."""
                for field in path_fields:
                    if field in obj_dict and obj_dict[field] is not None:
                        obj_dict[field] = Path(obj_dict[field])
                return obj_dict
            
            # Handle data source config
            data_source_data = data.get('data_source', {}).copy()
            data_source_config = DataSourceConfig(**data_source_data)
            
            # Handle storage config with Path conversion
            storage_data = data.get('storage', {}).copy()
            deserialize_path_fields(storage_data, ['base_data_dir'])
            storage_config = StorageConfig(**storage_data)
            
            # Remove sub-config data and handle log_file Path conversion
            config_data = {k: v for k, v in data.items() 
                          if k not in ['data_source', 'storage']}
            
            # Convert log_file back to Path if it exists
            if 'log_file' in config_data and config_data['log_file'] is not None:
                config_data['log_file'] = Path(config_data['log_file'])
            
            return cls(
                data_source=data_source_config,
                storage=storage_config,
                **config_data
            )
            
        except TypeError as e:
            raise ConfigurationError(
                f"Invalid configuration data: {e}",
                config_key="config_structure"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        # Custom serialization to handle Path objects
        def serialize_path_fields(obj_dict):
            """Convert Path objects to strings for serialization."""
            for key, value in obj_dict.items():
                if isinstance(value, Path):
                    obj_dict[key] = str(value)
                elif isinstance(value, dict):
                    serialize_path_fields(value)
            return obj_dict
        
        data_source_dict = asdict(self.data_source)
        storage_dict = asdict(self.storage)
        
        # Handle Path objects in storage config
        serialize_path_fields(storage_dict)
        
        return {
            'data_source': data_source_dict,
            'storage': storage_dict,
            'log_level': self.log_level,
            'log_file': str(self.log_file) if self.log_file else None,
            'buffer_size': self.buffer_size,
            'batch_size': self.batch_size,
            'memory_limit_mb': self.memory_limit_mb,
            'enable_progress_tracking': self.enable_progress_tracking,
            'progress_update_interval': self.progress_update_interval,
            'enable_health_checks': self.enable_health_checks,
            'health_check_interval': self.health_check_interval
        }
    
    def save_to_file(self, config_path: Union[str, Path], format: str = 'yaml'):
        """Save configuration to file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = self.to_dict()
        
        # Additional serialization for enums and other complex types
        def serialize_all_types(obj):
            """Serialize all non-basic types to strings."""
            if isinstance(obj, dict):
                return {k: serialize_all_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [serialize_all_types(item) for item in obj]
            elif hasattr(obj, 'value'):  # Enum
                return obj.value
            elif isinstance(obj, (Path, datetime)):
                return str(obj)
            else:
                return obj
        
        serialized_data = serialize_all_types(data)
        
        with open(config_path, 'w') as f:
            if format.lower() in ['yml', 'yaml']:
                yaml.dump(serialized_data, f, default_flow_style=False, indent=2)
            elif format.lower() == 'json':
                json.dump(serialized_data, f, indent=2, default=str)
            else:
                raise ConfigurationError(
                    f"Unsupported save format: {format}",
                    config_key="save_format"
                )
    
    def create_job_config(self, symbols: List[str], start_date: str, 
                         end_date: str, data_types: List[str],
                         **kwargs) -> DownloadJobConfig:
        """Create a job configuration with validated parameters."""
        return DownloadJobConfig(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            data_types=data_types,
            **kwargs
        )
    
    def validate(self) -> List[str]:
        """Validate entire configuration and return list of issues."""
        issues = []
        
        # Validate data source connectivity
        try:
            # This would test actual connections in a real implementation
            if not self.data_source.iqfeed_username:
                issues.append("IQFeed username not configured")
        except Exception as e:
            issues.append(f"Data source validation failed: {e}")
        
        # Validate storage accessibility
        try:
            if not self.storage.base_data_dir.exists():
                issues.append(f"Storage directory does not exist: {self.storage.base_data_dir}")
        except Exception as e:
            issues.append(f"Storage validation failed: {e}")
        
        # Validate performance settings
        if self.memory_limit_mb < 128:
            issues.append("Memory limit too low (minimum 128MB)")
            
        if self.batch_size <= 0:
            issues.append("Batch size must be positive")
        
        return issues