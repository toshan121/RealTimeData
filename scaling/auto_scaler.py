#!/usr/bin/env python3
"""
Auto-Scaling and Resource Optimization System
Dynamic scaling for multi-symbol operations based on load and performance metrics

Key Features:
- Dynamic connection pool scaling based on symbol load
- Adaptive buffer sizing and memory management
- Performance-based resource allocation
- Predictive scaling using historical patterns
- Cost optimization and resource efficiency
"""

import asyncio
import threading
import time
import logging
import json
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque, defaultdict
from enum import Enum
import statistics
import os

logger = logging.getLogger(__name__)


class ScalingDirection(Enum):
    """Scaling direction"""
    UP = "scale_up"
    DOWN = "scale_down"
    MAINTAIN = "maintain"


class ResourceType(Enum):
    """Types of resources to scale"""
    CONNECTIONS = "connections"
    BUFFERS = "buffers"
    MEMORY = "memory"
    PROCESSING_THREADS = "processing_threads"


@dataclass
class ScalingMetrics:
    """Metrics used for scaling decisions"""
    symbol_count: int
    active_symbols: int
    avg_latency_ms: float
    throughput_msg_per_sec: float
    memory_usage_mb: float
    cpu_usage_percent: float
    connection_utilization_percent: float
    buffer_utilization_percent: float
    error_rate_percent: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ScalingRule:
    """Scaling rule definition"""
    name: str
    resource_type: ResourceType
    metric_name: str
    scale_up_threshold: float
    scale_down_threshold: float
    min_value: int
    max_value: int
    scale_factor: float = 1.5
    cooldown_minutes: int = 5
    enabled: bool = True


@dataclass
class ScalingAction:
    """Scaling action record"""
    id: str
    timestamp: datetime
    resource_type: ResourceType
    direction: ScalingDirection
    old_value: int
    new_value: int
    trigger_metric: str
    trigger_value: float
    threshold: float
    success: bool
    error_message: Optional[str] = None


@dataclass
class ResourceLimits:
    """System resource limits and constraints"""
    max_connections: int = 20
    max_memory_gb: float = 16.0
    max_cpu_percent: float = 80.0
    max_buffer_memory_gb: float = 4.0
    max_processing_threads: int = 32
    min_connections: int = 2
    min_memory_gb: float = 1.0
    min_processing_threads: int = 4


class PredictiveScaler:
    """Predictive scaling based on historical patterns"""
    
    def __init__(self, history_hours: int = 24):
        self.history_hours = history_hours
        self.metrics_history: deque = deque(maxlen=1440)  # Store 24 hours at 1-minute intervals
        
    def add_metrics(self, metrics: ScalingMetrics):
        """Add metrics to historical data"""
        self.metrics_history.append(metrics)
    
    def predict_load(self, minutes_ahead: int = 30) -> Dict[str, float]:
        """Predict resource requirements for future timeframe"""
        if len(self.metrics_history) < 10:
            return {}
        
        # Simple trend analysis
        recent_metrics = list(self.metrics_history)[-60:]  # Last hour
        
        # Calculate trends
        symbol_trend = self._calculate_trend([m.symbol_count for m in recent_metrics])
        latency_trend = self._calculate_trend([m.avg_latency_ms for m in recent_metrics])
        throughput_trend = self._calculate_trend([m.throughput_msg_per_sec for m in recent_metrics])
        memory_trend = self._calculate_trend([m.memory_usage_mb for m in recent_metrics])
        
        # Project future values
        current_symbols = recent_metrics[-1].symbol_count if recent_metrics else 0
        current_latency = recent_metrics[-1].avg_latency_ms if recent_metrics else 0
        current_memory = recent_metrics[-1].memory_usage_mb if recent_metrics else 0
        
        predicted_symbols = max(0, current_symbols + (symbol_trend * minutes_ahead))
        predicted_latency = max(0, current_latency + (latency_trend * minutes_ahead))
        predicted_memory = max(0, current_memory + (memory_trend * minutes_ahead))
        
        return {
            'predicted_symbol_count': predicted_symbols,
            'predicted_latency_ms': predicted_latency,
            'predicted_memory_mb': predicted_memory,
            'confidence_score': min(100, len(self.metrics_history) / 60)  # Based on data availability
        }
    
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend (rate of change per minute)"""
        if len(values) < 2:
            return 0.0
        
        # Simple linear trend calculation
        n = len(values)
        x_values = list(range(n))
        
        # Calculate slope using least squares
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(values)
        
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)
        
        return numerator / denominator if denominator != 0 else 0.0


class AutoScaler:
    """
    Auto-scaling system for multi-symbol operations
    
    Features:
    - Dynamic resource scaling based on load metrics
    - Predictive scaling using historical patterns
    - Cost optimization and efficiency monitoring
    - Configurable scaling rules and policies
    """
    
    def __init__(
        self,
        resource_limits: Optional[ResourceLimits] = None,
        scaling_rules: Optional[List[ScalingRule]] = None,
        enable_predictive_scaling: bool = True,
        metrics_collection_interval: float = 60.0,  # 1 minute
        enable_cost_optimization: bool = True
    ):
        self.resource_limits = resource_limits or ResourceLimits()
        self.scaling_rules = scaling_rules or self._create_default_scaling_rules()
        self.enable_predictive_scaling = enable_predictive_scaling
        self.metrics_collection_interval = metrics_collection_interval
        self.enable_cost_optimization = enable_cost_optimization
        
        # Current resource allocations
        self.current_resources = {
            ResourceType.CONNECTIONS: 5,
            ResourceType.BUFFERS: 10,
            ResourceType.MEMORY: 2048,  # MB
            ResourceType.PROCESSING_THREADS: 8
        }
        
        # Scaling history and cooldowns
        self.scaling_history: deque = deque(maxlen=1000)
        self.last_scaling_times: Dict[ResourceType, datetime] = {}
        
        # Metrics and prediction
        self.current_metrics: Optional[ScalingMetrics] = None
        self.predictive_scaler = PredictiveScaler() if enable_predictive_scaling else None
        
        # Callbacks for actual scaling actions
        self.scaling_callbacks: Dict[ResourceType, Callable] = {}
        
        # Threading
        self._running = False
        self._scaling_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        
        # Performance tracking
        self._scaling_stats = {
            'total_scaling_actions': 0,
            'successful_scale_ups': 0,
            'successful_scale_downs': 0,
            'failed_scaling_actions': 0,
            'cost_savings_percent': 0.0,
            'performance_improvements': 0
        }
        
        logger.info("AutoScaler initialized with predictive scaling enabled" if enable_predictive_scaling else "disabled")
    
    def start(self) -> bool:
        """Start the auto-scaling system"""
        try:
            logger.info("Starting auto-scaling system...")
            
            self._running = True
            
            # Start scaling thread
            self._scaling_thread = threading.Thread(
                target=self._scaling_loop,
                daemon=True
            )
            self._scaling_thread.start()
            
            logger.info("Auto-scaling system started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start auto-scaling system: {e}")
            return False
    
    def stop(self):
        """Stop the auto-scaling system"""
        logger.info("Stopping auto-scaling system...")
        
        self._running = False
        
        if self._scaling_thread:
            self._scaling_thread.join(timeout=10.0)
        
        logger.info("Auto-scaling system stopped")
    
    def update_metrics(self, metrics: ScalingMetrics):
        """Update current metrics for scaling decisions"""
        with self._lock:
            self.current_metrics = metrics
            
            if self.predictive_scaler:
                self.predictive_scaler.add_metrics(metrics)
        
        logger.debug(f"Updated metrics: symbols={metrics.symbol_count}, "
                    f"latency={metrics.avg_latency_ms:.2f}ms, "
                    f"memory={metrics.memory_usage_mb:.0f}MB")
    
    def register_scaling_callback(
        self,
        resource_type: ResourceType,
        callback: Callable[[int], bool]
    ):
        """Register callback function for actual resource scaling"""
        self.scaling_callbacks[resource_type] = callback
        logger.info(f"Registered scaling callback for {resource_type.value}")
    
    def add_scaling_rule(self, rule: ScalingRule):
        """Add custom scaling rule"""
        with self._lock:
            self.scaling_rules.append(rule)
        logger.info(f"Added scaling rule: {rule.name}")
    
    def remove_scaling_rule(self, rule_name: str):
        """Remove scaling rule by name"""
        with self._lock:
            self.scaling_rules = [r for r in self.scaling_rules if r.name != rule_name]
        logger.info(f"Removed scaling rule: {rule_name}")
    
    def get_current_resources(self) -> Dict[ResourceType, int]:
        """Get current resource allocations"""
        with self._lock:
            return self.current_resources.copy()
    
    def get_scaling_stats(self) -> Dict[str, Any]:
        """Get auto-scaling statistics"""
        with self._lock:
            recent_actions = [
                action for action in self.scaling_history
                if action.timestamp > datetime.now() - timedelta(hours=24)
            ]
            
            return {
                **self._scaling_stats,
                'current_resources': self.current_resources.copy(),
                'recent_scaling_actions': len(recent_actions),
                'average_scaling_frequency_per_hour': len(recent_actions) / 24 if recent_actions else 0,
                'last_scaling_time': max(self.last_scaling_times.values()) if self.last_scaling_times else None
            }
    
    def get_scaling_recommendations(self) -> List[Dict[str, Any]]:
        """Get current scaling recommendations"""
        if not self.current_metrics:
            return []
        
        recommendations = []
        
        with self._lock:
            for rule in self.scaling_rules:
                if not rule.enabled:
                    continue
                
                current_value = self._get_metric_value(self.current_metrics, rule.metric_name)
                if current_value is None:
                    continue
                
                resource_current = self.current_resources.get(rule.resource_type, 0)
                
                # Check for scale up
                if (current_value > rule.scale_up_threshold and 
                    resource_current < rule.max_value and
                    self._can_scale(rule.resource_type)):
                    
                    new_value = min(
                        rule.max_value,
                        int(resource_current * rule.scale_factor)
                    )
                    
                    recommendations.append({
                        'rule_name': rule.name,
                        'resource_type': rule.resource_type.value,
                        'direction': ScalingDirection.UP.value,
                        'current_value': resource_current,
                        'recommended_value': new_value,
                        'trigger_metric': rule.metric_name,
                        'metric_value': current_value,
                        'threshold': rule.scale_up_threshold,
                        'urgency': 'high' if current_value > rule.scale_up_threshold * 1.5 else 'medium'
                    })
                
                # Check for scale down
                elif (current_value < rule.scale_down_threshold and 
                      resource_current > rule.min_value and
                      self._can_scale(rule.resource_type)):
                    
                    new_value = max(
                        rule.min_value,
                        int(resource_current / rule.scale_factor)
                    )
                    
                    recommendations.append({
                        'rule_name': rule.name,
                        'resource_type': rule.resource_type.value,
                        'direction': ScalingDirection.DOWN.value,
                        'current_value': resource_current,
                        'recommended_value': new_value,
                        'trigger_metric': rule.metric_name,
                        'metric_value': current_value,
                        'threshold': rule.scale_down_threshold,
                        'urgency': 'low'
                    })
            
            # Add predictive recommendations
            if self.predictive_scaler and self.enable_predictive_scaling:
                predictions = self.predictive_scaler.predict_load()
                if predictions and predictions.get('confidence_score', 0) > 50:
                    predictive_recs = self._generate_predictive_recommendations(predictions)
                    recommendations.extend(predictive_recs)
        
        return recommendations
    
    def force_scaling_action(
        self,
        resource_type: ResourceType,
        new_value: int,
        reason: str = "manual"
    ) -> bool:
        """Force a specific scaling action"""
        with self._lock:
            current_value = self.current_resources.get(resource_type, 0)
            
            if new_value == current_value:
                logger.info(f"No scaling needed for {resource_type.value}: already at {new_value}")
                return True
            
            # Validate limits
            if resource_type == ResourceType.CONNECTIONS:
                if not (self.resource_limits.min_connections <= new_value <= self.resource_limits.max_connections):
                    logger.error(f"Connection count {new_value} outside limits")
                    return False
            
            # Execute scaling
            success = self._execute_scaling_action(
                resource_type=resource_type,
                new_value=new_value,
                trigger_metric="manual",
                trigger_value=0.0,
                threshold=0.0
            )
            
            if success:
                logger.info(f"Successfully forced scaling {resource_type.value} from {current_value} to {new_value}")
            else:
                logger.error(f"Failed to force scaling {resource_type.value}")
            
            return success
    
    def _scaling_loop(self):
        """Main scaling loop"""
        logger.info("Auto-scaling loop started")
        
        while self._running:
            try:
                if self.current_metrics:
                    # Get scaling recommendations
                    recommendations = self.get_scaling_recommendations()
                    
                    # Execute high-priority recommendations
                    for rec in recommendations:
                        if rec.get('urgency') == 'high':
                            resource_type = ResourceType(rec['resource_type'])
                            direction = ScalingDirection(rec['direction'])
                            
                            if direction == ScalingDirection.UP:
                                self._execute_scaling_action(
                                    resource_type=resource_type,
                                    new_value=rec['recommended_value'],
                                    trigger_metric=rec['trigger_metric'],
                                    trigger_value=rec['metric_value'],
                                    threshold=rec['threshold']
                                )
                            elif direction == ScalingDirection.DOWN and self.enable_cost_optimization:
                                # Be more conservative with scale-down
                                time.sleep(30)  # Wait 30 seconds before scale-down
                                if self._should_still_scale_down(resource_type, rec):
                                    self._execute_scaling_action(
                                        resource_type=resource_type,
                                        new_value=rec['recommended_value'],
                                        trigger_metric=rec['trigger_metric'],
                                        trigger_value=rec['metric_value'],
                                        threshold=rec['threshold']
                                    )
                
                time.sleep(self.metrics_collection_interval)
                
            except Exception as e:
                logger.error(f"Error in scaling loop: {e}")
                time.sleep(30)
        
        logger.info("Auto-scaling loop stopped")
    
    def _execute_scaling_action(
        self,
        resource_type: ResourceType,
        new_value: int,
        trigger_metric: str,
        trigger_value: float,
        threshold: float
    ) -> bool:
        """Execute a scaling action"""
        current_value = self.current_resources.get(resource_type, 0)
        direction = ScalingDirection.UP if new_value > current_value else ScalingDirection.DOWN
        
        action_id = f"{resource_type.value}_{int(time.time())}"
        
        action = ScalingAction(
            id=action_id,
            timestamp=datetime.now(),
            resource_type=resource_type,
            direction=direction,
            old_value=current_value,
            new_value=new_value,
            trigger_metric=trigger_metric,
            trigger_value=trigger_value,
            threshold=threshold,
            success=False
        )
        
        try:
            # Check cooldown period
            if not self._can_scale(resource_type):
                logger.info(f"Scaling {resource_type.value} in cooldown period")
                return False
            
            # Execute scaling via callback
            callback = self.scaling_callbacks.get(resource_type)
            if callback:
                success = callback(new_value)
                if success:
                    self.current_resources[resource_type] = new_value
                    self.last_scaling_times[resource_type] = datetime.now()
                    action.success = True
                    
                    # Update statistics
                    self._scaling_stats['total_scaling_actions'] += 1
                    if direction == ScalingDirection.UP:
                        self._scaling_stats['successful_scale_ups'] += 1
                    else:
                        self._scaling_stats['successful_scale_downs'] += 1
                    
                    logger.info(f"Successfully scaled {resource_type.value} from {current_value} to {new_value}")
                else:
                    action.success = False
                    action.error_message = "Scaling callback returned False"
                    self._scaling_stats['failed_scaling_actions'] += 1
                    logger.error(f"Failed to scale {resource_type.value}: callback returned False")
            else:
                logger.warning(f"No scaling callback registered for {resource_type.value}")
                action.success = False
                action.error_message = "No scaling callback registered"
            
        except Exception as e:
            action.success = False
            action.error_message = str(e)
            self._scaling_stats['failed_scaling_actions'] += 1
            logger.error(f"Error executing scaling action: {e}")
        
        # Record action
        self.scaling_history.append(action)
        
        return action.success
    
    def _can_scale(self, resource_type: ResourceType) -> bool:
        """Check if resource can be scaled (not in cooldown)"""
        if resource_type not in self.last_scaling_times:
            return True
        
        # Find cooldown period for this resource type
        cooldown_minutes = 5  # Default
        for rule in self.scaling_rules:
            if rule.resource_type == resource_type:
                cooldown_minutes = rule.cooldown_minutes
                break
        
        last_scaling = self.last_scaling_times[resource_type]
        cooldown_period = timedelta(minutes=cooldown_minutes)
        
        return datetime.now() - last_scaling > cooldown_period
    
    def _should_still_scale_down(
        self,
        resource_type: ResourceType,
        recommendation: Dict[str, Any]
    ) -> bool:
        """Double-check if we should still scale down after waiting"""
        if not self.current_metrics:
            return False
        
        # Re-evaluate the metric
        current_value = self._get_metric_value(
            self.current_metrics,
            recommendation['trigger_metric']
        )
        
        if current_value is None:
            return False
        
        # Still below threshold?
        return current_value < recommendation['threshold']
    
    def _get_metric_value(self, metrics: ScalingMetrics, metric_name: str) -> Optional[float]:
        """Get metric value by name"""
        metric_map = {
            'symbol_count': metrics.symbol_count,
            'avg_latency_ms': metrics.avg_latency_ms,
            'throughput_msg_per_sec': metrics.throughput_msg_per_sec,
            'memory_usage_mb': metrics.memory_usage_mb,
            'cpu_usage_percent': metrics.cpu_usage_percent,
            'connection_utilization_percent': metrics.connection_utilization_percent,
            'buffer_utilization_percent': metrics.buffer_utilization_percent,
            'error_rate_percent': metrics.error_rate_percent
        }
        
        return metric_map.get(metric_name)
    
    def _generate_predictive_recommendations(
        self,
        predictions: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations based on predictions"""
        recommendations = []
        
        predicted_symbols = predictions.get('predicted_symbol_count', 0)
        predicted_memory = predictions.get('predicted_memory_mb', 0)
        confidence = predictions.get('confidence_score', 0)
        
        if confidence < 50:
            return recommendations
        
        # Predict connection needs
        current_connections = self.current_resources.get(ResourceType.CONNECTIONS, 5)
        symbols_per_connection = 400  # Target
        needed_connections = max(2, int(predicted_symbols / symbols_per_connection))
        
        if needed_connections > current_connections * 1.2:  # 20% buffer
            recommendations.append({
                'rule_name': 'predictive_connections',
                'resource_type': ResourceType.CONNECTIONS.value,
                'direction': ScalingDirection.UP.value,
                'current_value': current_connections,
                'recommended_value': min(self.resource_limits.max_connections, needed_connections),
                'trigger_metric': 'predicted_symbol_count',
                'metric_value': predicted_symbols,
                'threshold': current_connections * symbols_per_connection,
                'urgency': 'medium',
                'type': 'predictive'
            })
        
        # Predict memory needs
        current_memory = self.current_resources.get(ResourceType.MEMORY, 2048)
        if predicted_memory > current_memory * 1.3:  # 30% buffer
            new_memory = min(
                self.resource_limits.max_memory_gb * 1024,
                int(predicted_memory * 1.2)
            )
            
            recommendations.append({
                'rule_name': 'predictive_memory',
                'resource_type': ResourceType.MEMORY.value,
                'direction': ScalingDirection.UP.value,
                'current_value': current_memory,
                'recommended_value': new_memory,
                'trigger_metric': 'predicted_memory_mb',
                'metric_value': predicted_memory,
                'threshold': current_memory,
                'urgency': 'medium',
                'type': 'predictive'
            })
        
        return recommendations
    
    def _create_default_scaling_rules(self) -> List[ScalingRule]:
        """Create default scaling rules"""
        return [
            # Connection scaling based on symbol count
            ScalingRule(
                name="connection_scale_up_symbols",
                resource_type=ResourceType.CONNECTIONS,
                metric_name="symbol_count",
                scale_up_threshold=1500,  # Scale up at 1500 symbols
                scale_down_threshold=800,  # Scale down below 800 symbols
                min_value=2,
                max_value=20,
                scale_factor=1.5,
                cooldown_minutes=5
            ),
            
            # Connection scaling based on latency
            ScalingRule(
                name="connection_scale_up_latency",
                resource_type=ResourceType.CONNECTIONS,
                metric_name="avg_latency_ms",
                scale_up_threshold=100.0,  # Scale up if latency > 100ms
                scale_down_threshold=30.0,  # Scale down if latency < 30ms
                min_value=2,
                max_value=20,
                scale_factor=1.3,
                cooldown_minutes=3
            ),
            
            # Memory scaling based on usage
            ScalingRule(
                name="memory_scale_up",
                resource_type=ResourceType.MEMORY,
                metric_name="memory_usage_mb",
                scale_up_threshold=6144,  # Scale up at 6GB
                scale_down_threshold=2048,  # Scale down below 2GB
                min_value=1024,
                max_value=16384,
                scale_factor=1.5,
                cooldown_minutes=10
            ),
            
            # Buffer scaling based on utilization
            ScalingRule(
                name="buffer_scale_up",
                resource_type=ResourceType.BUFFERS,
                metric_name="buffer_utilization_percent",
                scale_up_threshold=80.0,  # Scale up at 80% utilization
                scale_down_threshold=40.0,  # Scale down below 40%
                min_value=5,
                max_value=50,
                scale_factor=1.4,
                cooldown_minutes=2
            ),
            
            # Processing threads based on CPU
            ScalingRule(
                name="threads_scale_up_cpu",
                resource_type=ResourceType.PROCESSING_THREADS,
                metric_name="cpu_usage_percent",
                scale_up_threshold=70.0,  # Scale up at 70% CPU
                scale_down_threshold=30.0,  # Scale down below 30%
                min_value=4,
                max_value=32,
                scale_factor=1.5,
                cooldown_minutes=5
            )
        ]


# Export main components
__all__ = [
    'AutoScaler',
    'ScalingMetrics',
    'ScalingRule',
    'ScalingAction',
    'ResourceLimits',
    'ResourceType',
    'ScalingDirection',
    'PredictiveScaler'
]