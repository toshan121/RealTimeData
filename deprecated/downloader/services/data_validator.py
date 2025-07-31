"""
Data Validator Service

Validates downloaded data for integrity, completeness, and quality.
Provides comprehensive validation checks for different data types.

Following Single Responsibility: Only handles data validation concerns.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from ..configuration.download_config import DataType
from ..exceptions import ValidationError, DataIntegrityError


logger = logging.getLogger(__name__)


class DataValidator:
    """
    Service for validating downloaded market data files.
    
    Provides comprehensive validation including:
    - File format validation
    - Data completeness checks
    - Market data integrity validation
    - Timestamp ordering verification
    - Statistical anomaly detection
    """
    
    def __init__(self):
        """Initialize the data validator."""
        self.validation_rules = self._load_validation_rules()
    
    def _load_validation_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load validation rules for different data types."""
        return {
            'tick': {
                'required_columns': [
                    'timestamp', 'symbol', 'trade_price', 'trade_size',
                    'total_volume', 'trade_market_center', 'bid_price', 'ask_price'
                ],
                'numeric_columns': ['trade_price', 'trade_size', 'total_volume', 'bid_price', 'ask_price'],
                'min_records': 1,
                'max_price_change_percent': 50.0,  # Maximum single trade price change
                'min_price': 0.01,
                'max_price': 10000.0
            },
            'level1': {
                'required_columns': [
                    'timestamp', 'symbol', 'bid_price', 'bid_size',
                    'ask_price', 'ask_size', 'bid_market_center', 'ask_market_center'
                ],
                'numeric_columns': ['bid_price', 'bid_size', 'ask_price', 'ask_size'],
                'min_records': 1,
                'max_spread_percent': 5.0,  # Maximum bid-ask spread
                'min_price': 0.01,
                'max_price': 10000.0
            },
            'level2': {
                'required_columns': [
                    'timestamp', 'symbol', 'level', 'market_maker',
                    'operation', 'side', 'price', 'size'
                ],
                'numeric_columns': ['level', 'operation', 'side', 'price', 'size'],
                'min_records': 1,
                'max_levels': 20,  # Maximum order book levels
                'min_price': 0.01,
                'max_price': 10000.0
            }
        }
    
    def validate_file(self, file_path: Path, symbol: str, 
                     data_type: DataType, date: datetime) -> Dict[str, Any]:
        """
        Validate a downloaded data file.
        
        Args:
            file_path: Path to the data file
            symbol: Stock symbol
            data_type: Type of data (tick, level1, level2)
            date: Expected date of the data
            
        Returns:
            Validation result dictionary
            
        Raises:
            ValidationError: If validation fails
        """
        logger.info(f"Validating {data_type.value} file: {file_path}")
        
        try:
            # Check if file exists
            if not file_path.exists():
                raise ValidationError(
                    f"Data file does not exist: {file_path}",
                    validation_type="file_existence"
                )
            
            # Check file size
            file_size = file_path.stat().st_size
            if file_size == 0:
                raise ValidationError(
                    f"Data file is empty: {file_path}",
                    validation_type="file_size"
                )
            
            # Load data
            try:
                df = pd.read_csv(file_path)
            except Exception as e:
                raise ValidationError(
                    f"Failed to read CSV file: {e}",
                    validation_type="file_format"
                )
            
            # Get validation rules for this data type
            rules = self.validation_rules.get(data_type.value, {})
            
            # Perform validation checks
            validation_results = {
                'file_path': str(file_path),
                'file_size_bytes': file_size,
                'record_count': len(df),
                'validation_time': datetime.now().isoformat(),
                'data_type': data_type.value,
                'symbol': symbol,
                'expected_date': date.strftime('%Y-%m-%d'),
                'checks': {}
            }
            
            # Run all validation checks
            validation_results['checks']['structure'] = self._validate_structure(df, rules)
            validation_results['checks']['timestamps'] = self._validate_timestamps(df, date)
            validation_results['checks']['data_quality'] = self._validate_data_quality(df, data_type, rules)
            validation_results['checks']['market_data'] = self._validate_market_data(df, symbol, data_type, rules)
            validation_results['checks']['completeness'] = self._validate_completeness(df, date, rules)
            
            # Calculate overall validation score
            all_checks = []
            for check_category in validation_results['checks'].values():
                all_checks.extend(check_category.get('individual_checks', []))
            
            passed_checks = sum(1 for check in all_checks if check['passed'])
            total_checks = len(all_checks)
            
            validation_results['overall_score'] = (passed_checks / total_checks * 100.0) if total_checks > 0 else 0.0
            validation_results['is_valid'] = validation_results['overall_score'] >= 80.0  # 80% threshold
            validation_results['total_checks'] = total_checks
            validation_results['passed_checks'] = passed_checks
            validation_results['failed_checks'] = total_checks - passed_checks
            
            # Log validation summary
            if validation_results['is_valid']:
                logger.info(f"Validation passed for {file_path}: {validation_results['overall_score']:.1f}%")
            else:
                logger.warning(f"Validation failed for {file_path}: {validation_results['overall_score']:.1f}%")
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Validation error for {file_path}: {e}")
            raise ValidationError(f"Validation failed: {e}", validation_type="general")
    
    def _validate_structure(self, df: pd.DataFrame, rules: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data structure and required columns."""
        checks = []
        
        # Check required columns
        required_columns = rules.get('required_columns', [])
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        checks.append({
            'name': 'required_columns',
            'passed': len(missing_columns) == 0,
            'message': f"Missing columns: {missing_columns}" if missing_columns else "All required columns present",
            'details': {
                'required': required_columns,
                'present': list(df.columns),
                'missing': missing_columns
            }
        })
        
        # Check minimum record count
        min_records = rules.get('min_records', 1)
        record_count_ok = len(df) >= min_records
        
        checks.append({
            'name': 'minimum_records',
            'passed': record_count_ok,
            'message': f"Record count: {len(df)} (minimum: {min_records})",
            'details': {
                'actual_count': len(df),
                'minimum_required': min_records
            }
        })
        
        # Check for duplicate rows
        duplicate_count = df.duplicated().sum()
        no_duplicates = duplicate_count == 0
        
        checks.append({
            'name': 'no_duplicates',
            'passed': no_duplicates,
            'message': f"Duplicate rows: {duplicate_count}",
            'details': {
                'duplicate_count': duplicate_count,
                'total_rows': len(df)
            }
        })
        
        return {
            'category': 'structure',
            'passed': all(check['passed'] for check in checks),
            'individual_checks': checks
        }
    
    def _validate_timestamps(self, df: pd.DataFrame, expected_date: datetime) -> Dict[str, Any]:
        """Validate timestamp column and ordering."""
        checks = []
        
        if 'timestamp' not in df.columns:
            checks.append({
                'name': 'timestamp_column_exists',
                'passed': False,
                'message': "Timestamp column not found",
                'details': {}
            })
            return {
                'category': 'timestamps',
                'passed': False,
                'individual_checks': checks
            }
        
        # Convert timestamps
        try:
            df['timestamp_parsed'] = pd.to_datetime(df['timestamp'])
            timestamp_parsing_ok = True
        except Exception as e:
            timestamp_parsing_ok = False
            
        checks.append({
            'name': 'timestamp_parsing',
            'passed': timestamp_parsing_ok,
            'message': "Timestamp parsing successful" if timestamp_parsing_ok else f"Timestamp parsing failed: {e}",
            'details': {}
        })
        
        if not timestamp_parsing_ok:
            return {
                'category': 'timestamps',
                'passed': False,
                'individual_checks': checks
            }
        
        # Check timestamp ordering
        timestamps = df['timestamp_parsed'].values
        ordering_violations = 0
        
        for i in range(len(timestamps) - 1):
            if timestamps[i] > timestamps[i + 1]:
                ordering_violations += 1
        
        ordering_ok = ordering_violations == 0
        
        checks.append({
            'name': 'timestamp_ordering',
            'passed': ordering_ok,
            'message': f"Timestamp ordering violations: {ordering_violations}",
            'details': {
                'violations': ordering_violations,
                'total_comparisons': len(timestamps) - 1
            }
        })
        
        # Check date consistency
        if len(timestamps) > 0:
            min_date = timestamps.min()
            max_date = timestamps.max()
            expected_date_start = expected_date.replace(hour=0, minute=0, second=0, microsecond=0)
            expected_date_end = expected_date_start + timedelta(days=1)
            
            date_range_ok = (
                pd.Timestamp(min_date).date() == expected_date.date() or
                pd.Timestamp(max_date).date() == expected_date.date()
            )
            
            checks.append({
                'name': 'date_consistency',
                'passed': date_range_ok,
                'message': f"Data date range: {pd.Timestamp(min_date).date()} to {pd.Timestamp(max_date).date()}",
                'details': {
                    'min_date': str(pd.Timestamp(min_date).date()),
                    'max_date': str(pd.Timestamp(max_date).date()),
                    'expected_date': expected_date.strftime('%Y-%m-%d')
                }
            })
        
        return {
            'category': 'timestamps',
            'passed': all(check['passed'] for check in checks),
            'individual_checks': checks
        }
    
    def _validate_data_quality(self, df: pd.DataFrame, data_type: DataType, 
                              rules: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data quality and detect anomalies."""
        checks = []
        
        # Check for null values
        numeric_columns = rules.get('numeric_columns', [])
        null_counts = {}
        
        for column in numeric_columns:
            if column in df.columns:
                null_count = df[column].isnull().sum()
                null_counts[column] = null_count
        
        total_nulls = sum(null_counts.values())
        no_nulls = total_nulls == 0
        
        checks.append({
            'name': 'no_null_values',
            'passed': no_nulls,
            'message': f"Null values found: {total_nulls}",
            'details': {
                'null_counts_by_column': null_counts,
                'total_nulls': total_nulls
            }
        })
        
        # Check numeric ranges
        for column in numeric_columns:
            if column in df.columns and not df[column].empty:
                # Check for negative values where inappropriate
                if 'price' in column.lower() or 'size' in column.lower():
                    negative_count = (df[column] < 0).sum()
                    no_negatives = negative_count == 0
                    
                    checks.append({
                        'name': f'{column}_no_negatives',
                        'passed': no_negatives,
                        'message': f"Negative values in {column}: {negative_count}",
                        'details': {
                            'column': column,
                            'negative_count': negative_count,
                            'total_count': len(df)
                        }
                    })
                
                # Check reasonable price ranges
                if 'price' in column.lower():
                    min_price = rules.get('min_price', 0.01)
                    max_price = rules.get('max_price', 10000.0)
                    
                    out_of_range = ((df[column] < min_price) | (df[column] > max_price)).sum()
                    range_ok = out_of_range == 0
                    
                    checks.append({
                        'name': f'{column}_price_range',
                        'passed': range_ok,
                        'message': f"Out of range prices in {column}: {out_of_range}",
                        'details': {
                            'column': column,
                            'out_of_range_count': out_of_range,
                            'min_allowed': min_price,
                            'max_allowed': max_price,
                            'actual_min': float(df[column].min()) if not df[column].empty else None,
                            'actual_max': float(df[column].max()) if not df[column].empty else None
                        }
                    })
        
        return {
            'category': 'data_quality',
            'passed': all(check['passed'] for check in checks),
            'individual_checks': checks
        }
    
    def _validate_market_data(self, df: pd.DataFrame, symbol: str, 
                             data_type: DataType, rules: Dict[str, Any]) -> Dict[str, Any]:
        """Validate market data specific constraints."""
        checks = []
        
        if data_type == DataType.LEVEL1:
            # Check bid-ask spread
            if 'bid_price' in df.columns and 'ask_price' in df.columns:
                # Calculate spreads
                spreads = df['ask_price'] - df['bid_price']
                negative_spreads = (spreads < 0).sum()
                
                checks.append({
                    'name': 'no_crossed_quotes',
                    'passed': negative_spreads == 0,
                    'message': f"Crossed quotes (negative spreads): {negative_spreads}",
                    'details': {
                        'negative_spreads': negative_spreads,
                        'total_quotes': len(df)
                    }
                })
                
                # Check reasonable spread sizes
                max_spread_percent = rules.get('max_spread_percent', 5.0)
                if not spreads.empty:
                    spread_percentages = (spreads / df['bid_price']) * 100
                    large_spreads = (spread_percentages > max_spread_percent).sum()
                    
                    checks.append({
                        'name': 'reasonable_spreads',
                        'passed': large_spreads == 0,
                        'message': f"Unusually large spreads: {large_spreads}",
                        'details': {
                            'large_spreads': large_spreads,
                            'max_allowed_percent': max_spread_percent,
                            'avg_spread_percent': float(spread_percentages.mean()) if not spread_percentages.empty else 0
                        }
                    })
        
        elif data_type == DataType.TICK:
            # Check trade prices vs bid/ask
            if all(col in df.columns for col in ['trade_price', 'bid_price', 'ask_price']):
                # Trades should generally be between bid and ask
                outside_spread = (
                    (df['trade_price'] < df['bid_price']) | 
                    (df['trade_price'] > df['ask_price'])
                ).sum()
                
                # Allow some tolerance for legitimate trades outside spread
                outside_spread_ok = outside_spread < len(df) * 0.1  # Less than 10%
                
                checks.append({
                    'name': 'trades_within_spread',
                    'passed': outside_spread_ok,
                    'message': f"Trades outside spread: {outside_spread} ({outside_spread/len(df)*100:.1f}%)",
                    'details': {
                        'outside_spread_count': outside_spread,
                        'total_trades': len(df),
                        'outside_spread_percent': outside_spread/len(df)*100 if len(df) > 0 else 0
                    }
                })
        
        elif data_type == DataType.LEVEL2:
            # Check level consistency
            if 'level' in df.columns:
                max_levels = rules.get('max_levels', 20)
                actual_max_level = df['level'].max() if not df['level'].empty else 0
                
                levels_ok = actual_max_level <= max_levels
                
                checks.append({
                    'name': 'reasonable_levels',
                    'passed': levels_ok,
                    'message': f"Maximum level: {actual_max_level} (limit: {max_levels})",
                    'details': {
                        'max_level': actual_max_level,
                        'max_allowed': max_levels
                    }
                })
        
        return {
            'category': 'market_data',
            'passed': all(check['passed'] for check in checks),
            'individual_checks': checks
        }
    
    def _validate_completeness(self, df: pd.DataFrame, expected_date: datetime,
                              rules: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data completeness for the expected time period."""
        checks = []
        
        # Check if we have data throughout the trading day
        if 'timestamp' in df.columns and not df.empty:
            try:
                df['timestamp_parsed'] = pd.to_datetime(df['timestamp'])
                
                # Group by hour to check coverage
                df['hour'] = df['timestamp_parsed'].dt.hour
                trading_hours = range(9, 16)  # 9 AM to 4 PM EST (simplified)
                
                hours_with_data = set(df['hour'].unique())
                trading_hours_with_data = set(trading_hours) & hours_with_data
                coverage_percent = len(trading_hours_with_data) / len(trading_hours) * 100
                
                good_coverage = coverage_percent >= 50  # At least 50% of trading hours
                
                checks.append({
                    'name': 'trading_hours_coverage',
                    'passed': good_coverage,
                    'message': f"Trading hours coverage: {coverage_percent:.1f}%",
                    'details': {
                        'trading_hours': list(trading_hours),
                        'hours_with_data': list(hours_with_data),
                        'coverage_percent': coverage_percent
                    }
                })
                
            except Exception as e:
                checks.append({
                    'name': 'trading_hours_coverage',
                    'passed': False,
                    'message': f"Failed to analyze trading hours coverage: {e}",
                    'details': {}
                })
        
        # Check data density (records per minute during trading hours)
        if len(df) > 0:
            # Simplified density check
            expected_minutes = 6.5 * 60  # 6.5 trading hours * 60 minutes
            records_per_minute = len(df) / expected_minutes
            
            # Different data types have different expected densities
            min_density_thresholds = {
                'tick': 0.1,    # At least 1 trade per 10 minutes
                'level1': 1.0,  # At least 1 quote update per minute
                'level2': 2.0   # At least 2 L2 updates per minute
            }
            
            data_type_key = 'tick'  # Default fallback
            min_density = min_density_thresholds.get(data_type_key, 0.1)
            
            adequate_density = records_per_minute >= min_density
            
            checks.append({
                'name': 'adequate_data_density',
                'passed': adequate_density,
                'message': f"Data density: {records_per_minute:.2f} records/minute",
                'details': {
                    'records_per_minute': records_per_minute,
                    'minimum_required': min_density,
                    'total_records': len(df)
                }
            })
        
        return {
            'category': 'completeness', 
            'passed': all(check['passed'] for check in checks),
            'individual_checks': checks
        }
    
    def validate_batch(self, file_paths: List[Path], symbols: List[str],
                      data_types: List[DataType], dates: List[datetime]) -> Dict[str, Any]:
        """
        Validate multiple files in batch.
        
        Args:
            file_paths: List of file paths to validate
            symbols: Corresponding symbols for each file
            data_types: Corresponding data types for each file  
            dates: Corresponding dates for each file
            
        Returns:
            Batch validation results
        """
        logger.info(f"Starting batch validation of {len(file_paths)} files")
        
        results = {
            'total_files': len(file_paths),
            'validation_time': datetime.now().isoformat(),
            'individual_results': [],
            'summary': {}
        }
        
        valid_files = 0
        invalid_files = 0
        errors = []
        
        for i, (file_path, symbol, data_type, date) in enumerate(zip(file_paths, symbols, data_types, dates)):
            try:
                validation_result = self.validate_file(file_path, symbol, data_type, date)
                results['individual_results'].append(validation_result)
                
                if validation_result['is_valid']:
                    valid_files += 1
                else:
                    invalid_files += 1
                    
            except Exception as e:
                error_result = {
                    'file_path': str(file_path),
                    'symbol': symbol,
                    'data_type': data_type.value,
                    'error': str(e),
                    'is_valid': False
                }
                results['individual_results'].append(error_result)
                errors.append(error_result)
                invalid_files += 1
        
        # Calculate summary statistics
        results['summary'] = {
            'valid_files': valid_files,
            'invalid_files': invalid_files,
            'error_files': len(errors),
            'success_rate': (valid_files / len(file_paths) * 100.0) if file_paths else 0.0,
            'overall_valid': invalid_files == 0
        }
        
        logger.info(f"Batch validation completed: {valid_files}/{len(file_paths)} files valid")
        
        return results