"""
IQFeed Ingestion Exceptions

Following RULES.md: Structured error handling with specific failure modes
Following PROJECT_ROADMAP.md: LOUD FAILURES - Every error must be visible and actionable
"""

from typing import Optional, Any, Dict


class IQFeedError(Exception):
    """Base exception for all IQFeed-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, 
                 recovery_hint: Optional[str] = None):
        """
        Initialize IQFeed error with detailed context.
        
        Args:
            message: Human-readable error description
            details: Additional context for debugging
            recovery_hint: Suggested recovery action
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.recovery_hint = recovery_hint
        
    def __str__(self) -> str:
        """Return detailed error message for logging."""
        result = f"IQFeedError: {self.message}"
        
        if self.details:
            result += f"\nDetails: {self.details}"
            
        if self.recovery_hint:
            result += f"\nRecovery: {self.recovery_hint}"
            
        return result


class IQFeedConnectionError(IQFeedError):
    """Raised when IQFeed connection fails."""
    
    def __init__(self, message: str, host: str, port: int, 
                 underlying_error: Optional[Exception] = None):
        details = {
            "host": host,
            "port": port,
            "underlying_error": str(underlying_error) if underlying_error else None
        }
        
        recovery_hint = (
            f"Check IQConnect.exe is running and accessible at {host}:{port}. "
            f"Verify firewall settings and network connectivity."
        )
        
        super().__init__(message, details, recovery_hint)
        self.host = host
        self.port = port
        self.underlying_error = underlying_error


class IQFeedAuthenticationError(IQFeedError):
    """Raised when IQFeed authentication fails."""
    
    def __init__(self, message: str, username: str, 
                 response_code: Optional[str] = None):
        details = {
            "username": username,
            "response_code": response_code
        }
        
        recovery_hint = (
            f"Verify IQFeed credentials for user '{username}'. "
            f"Check account status and subscription validity. "
            f"Ensure .env file contains correct IQFEED_USER and IQFEED_PASS."
        )
        
        super().__init__(message, details, recovery_hint)
        self.username = username
        self.response_code = response_code


class DataIntegrityError(IQFeedError):
    """Raised when data integrity checks fail."""
    
    def __init__(self, message: str, symbol: str, 
                 timestamp: Optional[str] = None,
                 expected_value: Optional[Any] = None,
                 actual_value: Optional[Any] = None):
        details = {
            "symbol": symbol,
            "timestamp": timestamp,
            "expected": expected_value,
            "actual": actual_value
        }
        
        recovery_hint = (
            f"Data integrity violation for {symbol}. "
            f"Re-download data or check IQFeed data quality. "
            f"Verify timestamp ordering and value ranges."
        )
        
        super().__init__(message, details, recovery_hint)
        self.symbol = symbol
        self.timestamp = timestamp


class DataGapError(DataIntegrityError):
    """Raised when gaps are found in data sequences."""
    
    def __init__(self, message: str, symbol: str, 
                 gap_start: Optional[str] = None,
                 gap_end: Optional[str] = None,
                 gap_duration: Optional[str] = None):
        details = {
            "symbol": symbol,
            "gap_start": gap_start,
            "gap_end": gap_end,
            "gap_duration": gap_duration
        }
        
        recovery_hint = (
            f"Data gap detected for {symbol}. "
            f"Check if gap occurred during market hours. "
            f"Consider re-downloading data with different time range."
        )
        
        super().__init__(message, symbol, details=details)
        self.gap_start = gap_start
        self.gap_end = gap_end
        self.gap_duration = gap_duration


class MessageParsingError(IQFeedError):
    """Raised when IQFeed message parsing fails."""
    
    def __init__(self, message: str, raw_message: str, 
                 message_type: str, line_number: Optional[int] = None):
        details = {
            "raw_message": raw_message[:200] + "..." if len(raw_message) > 200 else raw_message,
            "message_type": message_type,
            "line_number": line_number,
            "message_length": len(raw_message)
        }
        
        recovery_hint = (
            f"Failed to parse {message_type} message. "
            f"Check IQFeed protocol documentation. "
            f"Verify message format and field count."
        )
        
        super().__init__(message, details, recovery_hint)
        self.raw_message = raw_message
        self.message_type = message_type
        self.line_number = line_number


class RateLimitError(IQFeedError):
    """Raised when IQFeed rate limits are exceeded."""
    
    def __init__(self, message: str, current_rate: Optional[float] = None,
                 limit_rate: Optional[float] = None,
                 retry_after: Optional[int] = None):
        details = {
            "current_rate": current_rate,
            "limit_rate": limit_rate,
            "retry_after_seconds": retry_after
        }
        
        recovery_hint = (
            f"IQFeed rate limit exceeded. "
            f"Wait {retry_after} seconds before retrying. " if retry_after else
            f"Implement backoff strategy or reduce request rate."
        )
        
        super().__init__(message, details, recovery_hint)
        self.current_rate = current_rate
        self.limit_rate = limit_rate
        self.retry_after = retry_after


class OrderBookCorruptionError(IQFeedError):
    """Raised when order book state becomes corrupted."""
    
    def __init__(self, message: str, symbol: str, book_state: Dict[str, Any],
                 timestamp: str, operation: Optional[str] = None):
        details = {
            "symbol": symbol,
            "timestamp": timestamp,
            "operation": operation,
            "book_state": str(book_state)[:500] + "..." if len(str(book_state)) > 500 else str(book_state)
        }
        
        recovery_hint = (
            f"Order book corruption detected for {symbol} at {timestamp}. "
            f"Reset book state and re-subscribe to L2 data. "
            f"Check for missing or out-of-order L2 updates."
        )
        
        super().__init__(message, details, recovery_hint)
        self.symbol = symbol
        self.book_state = book_state
        self.timestamp = timestamp
        self.operation = operation


class ProcessingError(IQFeedError):
    """Raised when data processing fails."""
    
    def __init__(self, message: str, data: Any, 
                 processing_stage: str,
                 underlying_error: Optional[Exception] = None):
        details = {
            "processing_stage": processing_stage,
            "data_type": type(data).__name__,
            "data_sample": str(data)[:200] + "..." if len(str(data)) > 200 else str(data),
            "underlying_error": str(underlying_error) if underlying_error else None
        }
        
        recovery_hint = (
            f"Processing failed at stage: {processing_stage}. "
            f"Check data format and processing logic. "
            f"Verify input data integrity."
        )
        
        super().__init__(message, details, recovery_hint)
        self.data = data
        self.processing_stage = processing_stage
        self.underlying_error = underlying_error


class KafkaPublishingError(IQFeedError):
    """Raised when Kafka publishing fails."""
    
    def __init__(self, message: str, operation: str, topic: Optional[str] = None,
                 underlying_error: Optional[Exception] = None):
        details = {
            "operation": operation,
            "topic": topic,
            "underlying_error": str(underlying_error) if underlying_error else None
        }
        
        recovery_hint = (
            f"Kafka publishing failed for operation: {operation}. "
            f"Check Kafka broker connectivity and topic configuration. "
            f"Verify producer configuration and authentication."
        )
        
        super().__init__(message, details, recovery_hint)
        self.operation = operation
        self.topic = topic
        self.underlying_error = underlying_error


class DataValidationError(IQFeedError):
    """Raised when data validation fails."""
    
    def __init__(self, message: str, data: Any = None, 
                 expected_format: Optional[str] = None,
                 validation_rule: Optional[str] = None):
        details = {
            "data_type": type(data).__name__ if data is not None else None,
            "data_sample": str(data)[:200] + "..." if data and len(str(data)) > 200 else str(data),
            "expected_format": expected_format,
            "validation_rule": validation_rule
        }
        
        recovery_hint = (
            f"Data validation failed. "
            f"Expected format: {expected_format}. " if expected_format else ""
            f"Check data structure, types, and required fields."
        )
        
        super().__init__(message, details, recovery_hint)
        self.data = data
        self.expected_format = expected_format
        self.validation_rule = validation_rule


class SymbolValidationError(DataValidationError):
    """Raised when symbol validation fails - critical security issue."""
    
    def __init__(self, message: str, symbol: str, violation_type: str):
        details = {
            "symbol": symbol,
            "violation_type": violation_type,
            "security_risk": "HIGH - Potential injection attack"
        }
        
        recovery_hint = (
            f"Symbol '{symbol}' failed security validation: {violation_type}. "
            f"Only alphanumeric symbols with safe characters are allowed. "
            f"Check for injection attempts or data corruption."
        )
        
        super().__init__(message, symbol, "Valid trading symbol", violation_type)
        self.symbol = symbol
        self.violation_type = violation_type


class FinancialDataValidationError(DataValidationError):
    """Raised when financial data validation fails - critical security issue."""
    
    def __init__(self, message: str, symbol: str, field_name: str, 
                 value: Any, violation_type: str):
        details = {
            "symbol": symbol,
            "field_name": field_name,
            "invalid_value": value,
            "violation_type": violation_type,
            "security_risk": "HIGH - Financial data corruption"
        }
        
        recovery_hint = (
            f"Financial data validation failed for {symbol}.{field_name}: {violation_type}. "
            f"Value: {value}. Check for data corruption, overflow attacks, or system compromise."
        )
        
        super().__init__(message, details, f"Valid financial data for {field_name}", violation_type)
        self.symbol = symbol
        self.field_name = field_name
        self.value = value
        self.violation_type = violation_type


class SecurityValidationError(IQFeedError):
    """Raised when security validation fails - indicates potential attack."""
    
    def __init__(self, message: str, attack_type: str, 
                 source_data: Optional[str] = None,
                 risk_level: str = "HIGH"):
        from datetime import datetime
        details = {
            "attack_type": attack_type,
            "source_data": source_data[:100] + "..." if source_data and len(source_data) > 100 else source_data,
            "risk_level": risk_level,
            "timestamp": datetime.now().isoformat()
        }
        
        recovery_hint = (
            f"SECURITY ALERT: {attack_type} detected. "
            f"Risk level: {risk_level}. "
            f"Investigate source of malicious data. "
            f"Review logs and implement additional filtering."
        )
        
        super().__init__(message, details, recovery_hint)
        self.attack_type = attack_type
        self.source_data = source_data
        self.risk_level = risk_level


class ConnectionPoolExhaustionError(IQFeedError):
    """Raised when connection pool is exhausted."""
    
    def __init__(self, message: str, pool_size: int, active_connections: int):
        details = {
            "pool_size": pool_size,
            "active_connections": active_connections,
            "pool_utilization": (active_connections / pool_size) * 100 if pool_size > 0 else 0
        }
        
        recovery_hint = (
            f"Connection pool exhausted ({active_connections}/{pool_size} connections). "
            f"Increase pool size, reduce connection usage, or implement connection reuse."
        )
        
        super().__init__(message, details, recovery_hint)
        self.pool_size = pool_size
        self.active_connections = active_connections


class CircuitBreakerOpenError(IQFeedError):
    """Raised when circuit breaker is open."""
    
    def __init__(self, message: str, failure_count: int, last_failure_time):
        from datetime import datetime
        details = {
            "failure_count": failure_count,
            "last_failure_time": last_failure_time.isoformat(),
            "time_since_last_failure": (datetime.now() - last_failure_time).total_seconds()
        }
        
        recovery_hint = (
            f"Circuit breaker is open after {failure_count} failures. "
            f"Wait for recovery timeout or investigate underlying connection issues."
        )
        
        super().__init__(message, details, recovery_hint)
        self.failure_count = failure_count
        self.last_failure_time = last_failure_time


class HighLatencyError(IQFeedError):
    """Raised when latency exceeds acceptable thresholds."""
    
    def __init__(self, message: str, current_latency_ms: float, 
                 threshold_ms: float, symbol: Optional[str] = None):
        details = {
            "current_latency_ms": current_latency_ms,
            "threshold_ms": threshold_ms,
            "latency_ratio": current_latency_ms / threshold_ms if threshold_ms > 0 else 0,
            "symbol": symbol
        }
        
        recovery_hint = (
            f"Latency {current_latency_ms:.1f}ms exceeds threshold {threshold_ms:.1f}ms. "
            f"Check network conditions, IQFeed server load, or processing bottlenecks."
        )
        
        super().__init__(message, details, recovery_hint)
        self.current_latency_ms = current_latency_ms
        self.threshold_ms = threshold_ms
        self.symbol = symbol


class MessageQueueOverflowError(IQFeedError):
    """Raised when message queue overflows."""
    
    def __init__(self, message: str, queue_name: str, 
                 queue_size: int, max_size: int):
        details = {
            "queue_name": queue_name,
            "queue_size": queue_size,
            "max_size": max_size,
            "utilization_percentage": (queue_size / max_size) * 100 if max_size > 0 else 0
        }
        
        recovery_hint = (
            f"Message queue '{queue_name}' overflow ({queue_size}/{max_size}). "
            f"Increase queue size, improve processing speed, or implement backpressure."
        )
        
        super().__init__(message, details, recovery_hint)
        self.queue_name = queue_name
        self.queue_size = queue_size
        self.max_size = max_size


class DataCorruptionError(IQFeedError):
    """Raised when data corruption is detected."""
    
    def __init__(self, message: str, data_type: str, 
                 corruption_details: Dict[str, Any]):
        from datetime import datetime
        details = {
            "data_type": data_type,
            "corruption_details": corruption_details,
            "timestamp": datetime.now().isoformat()
        }
        
        recovery_hint = (
            f"Data corruption detected in {data_type}. "
            f"Verify data integrity, check for transmission errors, or restart data feed."
        )
        
        super().__init__(message, details, recovery_hint)
        self.data_type = data_type
        self.corruption_details = corruption_details


class SubscriptionLimitExceededError(IQFeedError):
    """Raised when subscription limits are exceeded."""
    
    def __init__(self, message: str, current_subscriptions: int, 
                 limit: int, subscription_type: str):
        details = {
            "current_subscriptions": current_subscriptions,
            "limit": limit,
            "subscription_type": subscription_type,
            "utilization_percentage": (current_subscriptions / limit) * 100 if limit > 0 else 0
        }
        
        recovery_hint = (
            f"Subscription limit exceeded for {subscription_type} "
            f"({current_subscriptions}/{limit}). "
            f"Unsubscribe from unused symbols or upgrade subscription plan."
        )
        
        super().__init__(message, details, recovery_hint)
        self.current_subscriptions = current_subscriptions
        self.limit = limit
        self.subscription_type = subscription_type


class ResourceExhaustionError(IQFeedError):
    """Raised when system resources are exhausted."""
    
    def __init__(self, message: str, resource_type: str, 
                 current_usage: float, limit: float):
        details = {
            "resource_type": resource_type,
            "current_usage": current_usage,
            "limit": limit,
            "utilization_percentage": (current_usage / limit) * 100 if limit > 0 else 0
        }
        
        recovery_hint = (
            f"Resource exhaustion: {resource_type} usage {current_usage} "
            f"exceeds limit {limit}. "
            f"Optimize resource usage or increase system capacity."
        )
        
        super().__init__(message, details, recovery_hint)
        self.resource_type = resource_type
        self.current_usage = current_usage
        self.limit = limit


# Maintain backwards compatibility with old naming
L2Exception = IQFeedError