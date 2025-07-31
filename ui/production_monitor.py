#!/usr/bin/env python3
"""
Hedge Fund Production Monitoring Dashboard
Always-on confidence monitor for single display deployment
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import json
import redis
import clickhouse_connect
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import psutil
import subprocess
import logging
from typing import Dict, List, Optional
import threading
import queue

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProductionMonitor:
    """Production monitoring dashboard for hedge fund operations"""

    def __init__(self):
        self.redis_client = self._connect_redis()
        self.clickhouse_client = self._connect_clickhouse()
        self.alert_queue = queue.Queue()
        self.health_status = {
            "overall": "HEALTHY",
            "services": {},
            "alerts": [],
            "last_update": datetime.now(),
        }

    def _connect_redis(self) -> Optional[redis.Redis]:
        """Connect to Redis for real-time metrics"""
        try:
            client = redis.Redis(
                host="localhost", port=6380, db=0, decode_responses=True
            )
            client.ping()
            return client
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return None

    def _connect_clickhouse(self):
        """Connect to ClickHouse for historical data"""
        try:
            client = clickhouse_connect.get_client(
                host="localhost",
                port=8123,
                database="l2_market_data",
                username="default",
                password="",
            )
            return client
        except Exception as e:
            logger.warning(f"ClickHouse connection failed: {e}")
            return None

    def get_system_metrics(self) -> Dict:
        """Get system performance metrics"""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # Network stats
        net_io = psutil.net_io_counters()

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_gb": memory.used / (1024**3),
            "memory_total_gb": memory.total / (1024**3),
            "disk_percent": disk.percent,
            "disk_used_tb": disk.used / (1024**4),
            "disk_total_tb": disk.total / (1024**4),
            "network_bytes_sent": net_io.bytes_sent,
            "network_bytes_recv": net_io.bytes_recv,
            "timestamp": datetime.now(),
        }

    def get_kafka_metrics(self) -> Dict:
        """Get Kafka performance metrics"""
        try:
            # Check Kafka consumer lag
            result = subprocess.run(
                [
                    "/opt/kafka/bin/kafka-consumer-groups.sh",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--describe",
                    "--all-groups",
                ],
                capture_output=True,
                text=True,
            )

            lag_info = self._parse_kafka_lag(result.stdout)

            return {
                "status": "HEALTHY" if result.returncode == 0 else "ERROR",
                "consumer_lag": lag_info,
                "topics_active": len(lag_info.get("topics", [])),
                "total_lag": sum(lag_info.get("lag_per_topic", {}).values()),
                "timestamp": datetime.now(),
            }
        except Exception as e:
            logger.error(f"Kafka metrics error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def _parse_kafka_lag(self, kafka_output: str) -> Dict:
        """Parse Kafka consumer lag output"""
        topics = set()
        lag_per_topic = {}

        for line in kafka_output.split("\n"):
            if "market-" in line:
                parts = line.split()
                if len(parts) >= 5:
                    topic = parts[1]
                    try:
                        lag = int(parts[4])
                        topics.add(topic)
                        lag_per_topic[topic] = lag_per_topic.get(topic, 0) + lag
                    except (ValueError, IndexError):
                        pass

        return {
            "topics": list(topics),
            "lag_per_topic": lag_per_topic,
            "total_topics": len(topics),
        }

    def get_data_flow_metrics(self) -> Dict:
        """Get real-time data flow metrics from Redis"""
        if not self.redis_client:
            return {"status": "ERROR", "error": "Redis unavailable"}

        try:
            # Get recent tick counts
            tick_count_key = "metrics:ticks:count:last_minute"
            l1_count_key = "metrics:l1:count:last_minute"
            l2_count_key = "metrics:l2:count:last_minute"

            tick_count = self.redis_client.get(tick_count_key) or 0
            l1_count = self.redis_client.get(l1_count_key) or 0
            l2_count = self.redis_client.get(l2_count_key) or 0

            # Get latency metrics
            latency_key = "metrics:latency:avg:last_minute"
            avg_latency = self.redis_client.get(latency_key) or 0

            return {
                "status": "HEALTHY",
                "ticks_per_minute": int(tick_count),
                "l1_updates_per_minute": int(l1_count),
                "l2_updates_per_minute": int(l2_count),
                "avg_latency_ms": float(avg_latency),
                "total_messages_per_minute": int(tick_count)
                + int(l1_count)
                + int(l2_count),
                "timestamp": datetime.now(),
            }
        except Exception as e:
            logger.error(f"Data flow metrics error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def get_clickhouse_metrics(self) -> Dict:
        """Get ClickHouse storage and query metrics"""
        if not self.clickhouse_client:
            return {"status": "ERROR", "error": "ClickHouse unavailable"}

        try:
            # Get table sizes
            result = self.clickhouse_client.query(
                """
                SELECT 
                    table,
                    sum(rows) as total_rows,
                    sum(bytes_on_disk) as total_bytes
                FROM system.parts 
                WHERE database = 'l2_market_data'
                  AND table IN ('market_ticks', 'market_l1', 'market_l2')
                GROUP BY table
            """
            )

            table_stats = {}
            total_rows = 0
            total_bytes = 0

            for row in result.result_rows:
                table, rows, bytes_size = row
                table_stats[table] = {
                    "rows": rows,
                    "bytes": bytes_size,
                    "size_gb": bytes_size / (1024**3),
                }
                total_rows += rows
                total_bytes += bytes_size

            # Get query performance
            query_result = self.clickhouse_client.query(
                """
                SELECT 
                    avg(query_duration_ms) as avg_duration,
                    count() as query_count
                FROM system.query_log 
                WHERE event_time >= now() - INTERVAL 1 MINUTE
                  AND type = 'QueryFinish'
            """
            )

            avg_duration = 0
            query_count = 0
            if query_result.result_rows:
                avg_duration, query_count = query_result.result_rows[0]

            return {
                "status": "HEALTHY",
                "table_stats": table_stats,
                "total_rows": total_rows,
                "total_size_gb": total_bytes / (1024**3),
                "avg_query_duration_ms": float(avg_duration or 0),
                "queries_per_minute": int(query_count or 0),
                "timestamp": datetime.now(),
            }
        except Exception as e:
            logger.error(f"ClickHouse metrics error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def check_service_health(self) -> Dict:
        """Check health of all critical services"""
        services = {
            "kafka": self._check_kafka_health(),
            "redis": self._check_redis_health(),
            "clickhouse": self._check_clickhouse_health(),
            "iqfeed": self._check_iqfeed_health(),
        }

        overall_status = "HEALTHY"
        for service, status in services.items():
            if status["status"] != "HEALTHY":
                overall_status = (
                    "DEGRADED" if overall_status == "HEALTHY" else "CRITICAL"
                )

        return {
            "overall_status": overall_status,
            "services": services,
            "timestamp": datetime.now(),
        }

    def _check_kafka_health(self) -> Dict:
        """Check Kafka service health"""
        try:
            result = subprocess.run(
                [
                    "/opt/kafka/bin/kafka-broker-api-versions.sh",
                    "--bootstrap-server",
                    "localhost:9092",
                ],
                capture_output=True,
                timeout=5,
            )

            return {
                "status": "HEALTHY" if result.returncode == 0 else "ERROR",
                "response_time_ms": 10,  # Approximate
            }
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def _check_redis_health(self) -> Dict:
        """Check Redis service health"""
        if not self.redis_client:
            return {"status": "ERROR", "error": "Not connected"}

        try:
            start_time = time.time()
            self.redis_client.ping()
            response_time = (time.time() - start_time) * 1000

            return {"status": "HEALTHY", "response_time_ms": response_time}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def _check_clickhouse_health(self) -> Dict:
        """Check ClickHouse service health"""
        if not self.clickhouse_client:
            return {"status": "ERROR", "error": "Not connected"}

        try:
            start_time = time.time()
            self.clickhouse_client.query("SELECT 1")
            response_time = (time.time() - start_time) * 1000

            return {"status": "HEALTHY", "response_time_ms": response_time}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def _check_iqfeed_health(self) -> Dict:
        """Check IQFeed connection health"""
        try:
            # This would check actual IQFeed connection
            # For now, simulate based on data flow
            data_metrics = self.get_data_flow_metrics()

            if data_metrics.get("status") == "HEALTHY":
                recent_data = data_metrics.get("total_messages_per_minute", 0) > 0
                return {
                    "status": "HEALTHY" if recent_data else "WARNING",
                    "message": "Data flowing" if recent_data else "No recent data",
                }
            else:
                return {"status": "ERROR", "error": "No data flow detected"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def generate_alerts(
        self,
        system_metrics: Dict,
        data_metrics: Dict,
        clickhouse_metrics: Dict,
        kafka_metrics: Dict,
    ) -> List[Dict]:
        """Generate alerts based on metric thresholds"""
        alerts = []
        now = datetime.now()

        # System alerts
        if system_metrics.get("cpu_percent", 0) > 80:
            alerts.append(
                {
                    "level": "WARNING",
                    "service": "System",
                    "message": f"High CPU usage: {system_metrics['cpu_percent']:.1f}%",
                    "timestamp": now,
                }
            )

        if system_metrics.get("memory_percent", 0) > 85:
            alerts.append(
                {
                    "level": "CRITICAL",
                    "service": "System",
                    "message": f"High memory usage: {system_metrics['memory_percent']:.1f}%",
                    "timestamp": now,
                }
            )

        if system_metrics.get("disk_percent", 0) > 80:
            alerts.append(
                {
                    "level": "WARNING",
                    "service": "System",
                    "message": f"High disk usage: {system_metrics['disk_percent']:.1f}%",
                    "timestamp": now,
                }
            )

        # Data flow alerts
        if data_metrics.get("avg_latency_ms", 0) > 500:
            alerts.append(
                {
                    "level": "CRITICAL",
                    "service": "Data Pipeline",
                    "message": f"High latency: {data_metrics['avg_latency_ms']:.1f}ms",
                    "timestamp": now,
                }
            )

        if data_metrics.get("total_messages_per_minute", 0) == 0:
            alerts.append(
                {
                    "level": "CRITICAL",
                    "service": "Data Pipeline",
                    "message": "No data flow detected",
                    "timestamp": now,
                }
            )

        # Kafka alerts
        if kafka_metrics.get("total_lag", 0) > 10000:
            alerts.append(
                {
                    "level": "WARNING",
                    "service": "Kafka",
                    "message": f"High consumer lag: {kafka_metrics['total_lag']}",
                    "timestamp": now,
                }
            )

        return alerts


def create_dashboard():
    """Create Streamlit dashboard"""

    st.set_page_config(
        page_title="Hedge Fund Production Monitor",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Custom CSS for hedge fund professional look
    st.markdown(
        """
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
        font-weight: bold;
    }
    .status-healthy { color: #28a745; font-weight: bold; }
    .status-warning { color: #ffc107; font-weight: bold; }
    .status-critical { color: #dc3545; font-weight: bold; }
    .metric-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
    }
    .alert-box {
        padding: 0.5rem;
        border-radius: 5px;
        margin: 0.25rem 0;
        border-left: 4px solid;
    }
    .alert-critical { border-color: #dc3545; background: #f8d7da; }
    .alert-warning { border-color: #ffc107; background: #fff3cd; }
    .alert-info { border-color: #17a2b8; background: #d1ecf1; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # Initialize monitor
    if "monitor" not in st.session_state:
        st.session_state.monitor = ProductionMonitor()

    monitor = st.session_state.monitor

    # Header
    st.markdown(
        '<h1 class="main-header">🏦 Hedge Fund Production Monitor</h1>',
        unsafe_allow_html=True,
    )

    # Auto-refresh
    placeholder = st.empty()

    # Main monitoring loop
    with placeholder.container():
        # Get all metrics
        system_metrics = monitor.get_system_metrics()
        data_metrics = monitor.get_data_flow_metrics()
        clickhouse_metrics = monitor.get_clickhouse_metrics()
        kafka_metrics = monitor.get_kafka_metrics()
        health_status = monitor.check_service_health()

        # Generate alerts
        alerts = monitor.generate_alerts(
            system_metrics, data_metrics, clickhouse_metrics, kafka_metrics
        )

        # Status overview
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            status_class = f"status-{health_status['overall_status'].lower()}"
            st.markdown(
                f'<div class="metric-box"><h3>Overall Status</h3><p class="{status_class}">{health_status["overall_status"]}</p></div>',
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                f'<div class="metric-box"><h3>Data Rate</h3><p>{data_metrics.get("total_messages_per_minute", 0):,}/min</p></div>',
                unsafe_allow_html=True,
            )

        with col3:
            st.markdown(
                f'<div class="metric-box"><h3>Latency</h3><p>{data_metrics.get("avg_latency_ms", 0):.1f}ms</p></div>',
                unsafe_allow_html=True,
            )

        with col4:
            st.markdown(
                f'<div class="metric-box"><h3>Active Alerts</h3><p>{len(alerts)}</p></div>',
                unsafe_allow_html=True,
            )

        # Service status grid
        st.subheader("🔧 Service Health")
        col1, col2, col3, col4 = st.columns(4)

        services = health_status.get("services", {})

        with col1:
            kafka_status = services.get("kafka", {}).get("status", "UNKNOWN")
            status_class = f"status-{kafka_status.lower()}"
            st.markdown(
                f"**Kafka:** <span class='{status_class}'>{kafka_status}</span>",
                unsafe_allow_html=True,
            )

        with col2:
            redis_status = services.get("redis", {}).get("status", "UNKNOWN")
            status_class = f"status-{redis_status.lower()}"
            st.markdown(
                f"**Redis:** <span class='{status_class}'>{redis_status}</span>",
                unsafe_allow_html=True,
            )

        with col3:
            ch_status = services.get("clickhouse", {}).get("status", "UNKNOWN")
            status_class = f"status-{ch_status.lower()}"
            st.markdown(
                f"**ClickHouse:** <span class='{status_class}'>{ch_status}</span>",
                unsafe_allow_html=True,
            )

        with col4:
            iqfeed_status = services.get("iqfeed", {}).get("status", "UNKNOWN")
            status_class = f"status-{iqfeed_status.lower()}"
            st.markdown(
                f"**IQFeed:** <span class='{status_class}'>{iqfeed_status}</span>",
                unsafe_allow_html=True,
            )

        # System metrics
        st.subheader("💻 System Performance")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "CPU Usage", f"{system_metrics.get('cpu_percent', 0):.1f}%", delta=None
            )

        with col2:
            memory_used = system_metrics.get("memory_used_gb", 0)
            memory_total = system_metrics.get("memory_total_gb", 1)
            st.metric(
                "Memory Usage",
                f"{memory_used:.1f}GB / {memory_total:.1f}GB",
                delta=f"{system_metrics.get('memory_percent', 0):.1f}%",
            )

        with col3:
            disk_used = system_metrics.get("disk_used_tb", 0)
            disk_total = system_metrics.get("disk_total_tb", 1)
            st.metric(
                "Disk Usage",
                f"{disk_used:.1f}TB / {disk_total:.1f}TB",
                delta=f"{system_metrics.get('disk_percent', 0):.1f}%",
            )

        # Data pipeline metrics
        st.subheader("📊 Data Pipeline")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Ticks/min", f"{data_metrics.get('ticks_per_minute', 0):,}")

        with col2:
            st.metric(
                "L1 Updates/min", f"{data_metrics.get('l1_updates_per_minute', 0):,}"
            )

        with col3:
            st.metric(
                "L2 Updates/min", f"{data_metrics.get('l2_updates_per_minute', 0):,}"
            )

        with col4:
            kafka_lag = kafka_metrics.get("total_lag", 0)
            st.metric("Kafka Lag", f"{kafka_lag:,}")

        # Storage metrics
        if clickhouse_metrics.get("status") == "HEALTHY":
            st.subheader("💾 Data Storage")
            col1, col2, col3 = st.columns(3)

            with col1:
                total_rows = clickhouse_metrics.get("total_rows", 0)
                st.metric("Total Records", f"{total_rows:,}")

            with col2:
                total_size = clickhouse_metrics.get("total_size_gb", 0)
                st.metric("Storage Size", f"{total_size:.2f}GB")

            with col3:
                avg_query_time = clickhouse_metrics.get("avg_query_duration_ms", 0)
                st.metric("Avg Query Time", f"{avg_query_time:.1f}ms")

        # Alerts section
        if alerts:
            st.subheader("🚨 Active Alerts")
            for alert in alerts[-10:]:  # Show last 10 alerts
                level = alert["level"].lower()
                alert_class = f"alert-{level}"
                timestamp = alert["timestamp"].strftime("%H:%M:%S")
                st.markdown(
                    f"""
                <div class="alert-box {alert_class}">
                    <strong>{alert['level']}</strong> - {alert['service']}: {alert['message']} 
                    <small>({timestamp})</small>
                </div>
                """,
                    unsafe_allow_html=True,
                )
        else:
            st.success("✅ No active alerts - All systems operating normally")

        # Last updated
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Auto-refresh every 5 seconds (disabled in test mode)
    if not os.environ.get("STREAMLIT_TEST_MODE"):
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    create_dashboard()
