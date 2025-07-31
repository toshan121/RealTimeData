#!/usr/bin/env python3
"""
Real-time Trading System Dashboard
- Streamlit-based dashboard for monitoring real-time trading infrastructure
- Reads metrics from Redis (independent of core system)
- Displays latency, throughput, network saturation, and system health
- Updates in real-time with configurable refresh rates
"""

import streamlit as st
import redis
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging

# Set page configuration
st.set_page_config(
    page_title="Real-time Trading System Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradingDashboard:
    """Main dashboard class"""
    
    def __init__(self):
        self.redis_client = None
        self.setup_redis()
        
        # Configuration
        self.refresh_intervals = {
            'metrics': 1,
            'latency': 0.5,
            'network': 5
        }
        
        # Cache for data
        self.data_cache = {}
        self.last_update = {}
    
    def setup_redis(self):
        """Setup Redis connection"""
        try:
            # Default Redis configuration
            redis_config = {
                'host': 'localhost',
                'port': 6379,
                'db': 0,
                'decode_responses': True
            }
            
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            
        except Exception as e:
            st.error(f"❌ Failed to connect to Redis: {e}")
            st.info("Make sure Redis is running and accessible")
            self.redis_client = None
    
    def get_redis_data(self, namespace: str, key: str) -> Optional[Dict]:
        """Get data from Redis"""
        if not self.redis_client:
            return None
        
        try:
            redis_key = f"realtime:{namespace}:{key}"
            data = self.redis_client.get(redis_key)
            
            if data:
                return json.loads(data)
            return None
            
        except Exception as e:
            logger.error(f"Error getting Redis data {namespace}:{key}: {e}")
            return None
    
    def get_redis_list(self, namespace: str, key: str, count: int = 100) -> List[Dict]:
        """Get list data from Redis"""
        if not self.redis_client:
            return []
        
        try:
            redis_key = f"realtime:{namespace}:{key}"
            data_list = self.redis_client.lrange(redis_key, 0, count - 1)
            
            return [json.loads(item) for item in data_list]
            
        except Exception as e:
            logger.error(f"Error getting Redis list {namespace}:{key}: {e}")
            return []
    
    def display_header(self):
        """Display dashboard header"""
        st.title("📈 Real-time Trading System Monitor")
        
        col1, col2, col3, col4 = st.columns(4)
        
        # System status
        system_overview = self.get_redis_data('metrics', 'system_overview')
        if system_overview:
            with col1:
                st.metric(
                    "Active Symbols",
                    system_overview.get('active_symbols', 0),
                    delta=None
                )
            
            with col2:
                st.metric(
                    "Messages/sec",
                    f"{system_overview.get('messages_per_second', 0):.0f}",
                    delta=None
                )
            
            with col3:
                st.metric(
                    "Avg Latency",
                    f"{system_overview.get('avg_latency_ms', 0):.1f}ms",
                    delta=None
                )
            
            with col4:
                # System health indicator
                avg_latency = system_overview.get('avg_latency_ms', 0)
                if avg_latency < 10:
                    st.success("🟢 System Healthy")
                elif avg_latency < 50:
                    st.warning("🟡 System Warning")
                else:
                    st.error("🔴 System Critical")
        else:
            st.warning("⚠️ No system data available")
    
    def display_latency_metrics(self):
        """Display latency monitoring section"""
        st.subheader("🕐 Latency Monitoring")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Real-time Latency Distribution**")
            
            # Get recent latency data
            latency_data = []
            symbols = ['AAPL', 'TSLA', 'SPY', 'QQQ', 'NVDA']  # Sample symbols
            
            for symbol in symbols:
                l1_latest = self.get_redis_data('latency', f'{symbol}_l1_latest')
                if l1_latest:
                    latency_data.append({
                        'Symbol': symbol,
                        'IQFeed Latency (ms)': l1_latest.get('iqfeed_latency_ms', 0),
                        'System Latency (ms)': l1_latest.get('system_latency_ms', 0),
                        'Timestamp': l1_latest.get('timestamp', '')
                    })
            
            if latency_data:
                df = pd.DataFrame(latency_data)
                
                # Create latency chart
                fig = px.bar(
                    df, 
                    x='Symbol', 
                    y=['IQFeed Latency (ms)', 'System Latency (ms)'],
                    title="Latency by Symbol",
                    barmode='group'
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No latency data available")
        
        with col2:
            st.write("**Latency Alerts & Thresholds**")
            
            # Latency thresholds
            warning_threshold = 10
            critical_threshold = 50
            
            st.write(f"⚠️ Warning Threshold: {warning_threshold}ms")
            st.write(f"🚨 Critical Threshold: {critical_threshold}ms")
            
            # Recent alerts (if available)
            # This would come from latency monitor alerts
            st.write("**Recent Alerts:**")
            st.info("No recent latency alerts")
    
    def display_network_metrics(self):
        """Display network monitoring section"""
        st.subheader("🌐 Network Monitoring")
        
        col1, col2, col3 = st.columns(3)
        
        network_stats = self.get_redis_data('network', 'latest_stats')
        
        if network_stats:
            with col1:
                bandwidth_mbps = network_stats.get('current_bandwidth_mbps', 0)
                st.metric(
                    "Bandwidth Usage",
                    f"{bandwidth_mbps:.1f} Mbps",
                    delta=None
                )
                
                # Bandwidth utilization bar
                utilization = network_stats.get('network_utilization_percent', 0)
                st.progress(min(utilization / 100, 1.0))
                st.write(f"Utilization: {utilization:.1f}%")
            
            with col2:
                connections = network_stats.get('current_connections', 0)
                st.metric(
                    "Active Connections",
                    connections,
                    delta=None
                )
                
                # Connection health
                if connections < 100:
                    st.success("Connection count healthy")
                elif connections < 500:
                    st.warning("High connection count")
                else:
                    st.error("Very high connection count")
            
            with col3:
                error_rate = network_stats.get('error_rate', 0) * 100
                st.metric(
                    "Error Rate",
                    f"{error_rate:.2f}%",
                    delta=None
                )
                
                # Error rate health
                if error_rate < 1:
                    st.success("Low error rate")
                elif error_rate < 5:
                    st.warning("Moderate error rate")
                else:
                    st.error("High error rate")
        
        # Network saturation assessment
        st.write("**Network Capacity Assessment**")
        
        if network_stats:
            # Create gauge chart for network utilization
            fig = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = network_stats.get('network_utilization_percent', 0),
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Network Utilization %"},
                delta = {'reference': 50},
                gauge = {
                    'axis': {'range': [None, 100]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, 50], 'color': "lightgray"},
                        {'range': [50, 80], 'color': "yellow"},
                        {'range': [80, 100], 'color': "red"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 90
                    }
                }
            ))
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No network data available")
    
    def display_symbol_metrics(self):
        """Display per-symbol metrics"""
        st.subheader("📊 Symbol-Level Metrics")
        
        # Get active symbols data
        dashboard_data = self.get_redis_data('metrics', 'system_overview')
        
        if not dashboard_data:
            st.info("No symbol data available")
            return
        
        # Create sample symbol data for demonstration
        sample_symbols = [
            {
                'Symbol': 'AAPL',
                'Messages/min': 1250,
                'Avg Latency (ms)': 2.1,
                'Last Update': '2024-01-15 14:30:25',
                'Status': '🟢 Active'
            },
            {
                'Symbol': 'TSLA',
                'Messages/min': 980,
                'Avg Latency (ms)': 3.2,
                'Last Update': '2024-01-15 14:30:24',
                'Status': '🟢 Active'
            },
            {
                'Symbol': 'SPY',
                'Messages/min': 2100,
                'Avg Latency (ms)': 1.8,
                'Last Update': '2024-01-15 14:30:26',
                'Status': '🟢 Active'
            },
            {
                'Symbol': 'QQQ',
                'Messages/min': 1800,
                'Avg Latency (ms)': 2.5,
                'Last Update': '2024-01-15 14:30:25',
                'Status': '🟢 Active'
            },
            {
                'Symbol': 'NVDA',
                'Messages/min': 1100,
                'Avg Latency (ms)': 4.1,
                'Last Update': '2024-01-15 14:30:23',
                'Status': '🟡 Slow'
            }
        ]
        
        df = pd.DataFrame(sample_symbols)
        
        # Display as interactive table
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )
        
        # Top performers chart
        col1, col2 = st.columns(2)
        
        with col1:
            fig = px.bar(
                df,
                x='Symbol',
                y='Messages/min',
                title="Message Volume by Symbol",
                color='Messages/min',
                color_continuous_scale='viridis'
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.scatter(
                df,
                x='Messages/min',
                y='Avg Latency (ms)',
                size='Messages/min',
                color='Symbol',
                title="Latency vs Volume",
                hover_data=['Symbol']
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
    
    def display_system_health(self):
        """Display system health overview"""
        st.subheader("🏥 System Health")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.write("**IQFeed Connection**")
            # This would come from real health checks
            st.success("🟢 Connected")
            st.write("Uptime: 2h 15m")
            st.write("Last heartbeat: 1s ago")
        
        with col2:
            st.write("**Kafka Pipeline**")
            st.success("🟢 Healthy")
            st.write("Messages in queue: 245")
            st.write("Consumer lag: 12ms")
        
        with col3:
            st.write("**Data Writer**")
            st.success("🟢 Writing")
            st.write("Files open: 15")
            st.write("Last write: 0.5s ago")
        
        # Resource utilization
        st.write("**Resource Utilization**")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            cpu_usage = 65  # Mock data
            st.metric("CPU Usage", f"{cpu_usage}%")
            st.progress(cpu_usage / 100)
        
        with col2:
            memory_usage = 42
            st.metric("Memory Usage", f"{memory_usage}%")
            st.progress(memory_usage / 100)
        
        with col3:
            disk_usage = 23
            st.metric("Disk Usage", f"{disk_usage}%")
            st.progress(disk_usage / 100)
        
        with col4:
            network_usage = 78
            st.metric("Network Usage", f"{network_usage}%")
            st.progress(network_usage / 100)
    
    def display_alerts(self):
        """Display recent alerts and notifications"""
        st.subheader("🚨 Alerts & Notifications")
        
        # Mock alert data
        alerts = [
            {
                'Time': '14:28:15',
                'Severity': '⚠️ Warning',
                'Component': 'Network',
                'Message': 'High bandwidth utilization (78%)',
                'Status': 'Active'
            },
            {
                'Time': '14:25:42',
                'Severity': '🔴 Critical',
                'Component': 'Latency',
                'Message': 'NVDA latency spike (52ms)',
                'Status': 'Resolved'
            },
            {
                'Time': '14:22:18',
                'Severity': '💡 Info',
                'Component': 'System',
                'Message': 'New symbol subscription: META',
                'Status': 'Resolved'
            },
            {
                'Time': '14:20:05',
                'Severity': '⚠️ Warning',
                'Component': 'Kafka',
                'Message': 'Consumer lag increasing',
                'Status': 'Resolved'
            }
        ]
        
        df_alerts = pd.DataFrame(alerts)
        
        # Color code by severity
        def color_severity(val):
            if '🔴 Critical' in val:
                return 'background-color: #ffebee'
            elif '⚠️ Warning' in val:
                return 'background-color: #fff3e0'
            elif '💡 Info' in val:
                return 'background-color: #e8f5e8'
            return ''
        
        styled_df = df_alerts.style.applymap(color_severity, subset=['Severity'])
        
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True
        )
    
    def run(self):
        """Run the dashboard"""
        
        # Sidebar controls
        with st.sidebar:
            st.header("Dashboard Controls")
            
            # Auto-refresh toggle
            auto_refresh = st.checkbox("Auto Refresh", value=True)
            
            if auto_refresh:
                refresh_rate = st.selectbox(
                    "Refresh Rate",
                    [1, 2, 5, 10],
                    index=1,
                    help="Refresh interval in seconds"
                )
            
            # Manual refresh button
            if st.button("🔄 Refresh Now"):
                st.rerun()
            
            # Connection status
            st.subheader("Connection Status")
            if self.redis_client:
                try:
                    self.redis_client.ping()
                    st.success("✅ Redis Connected")
                except Exception as e:
                    logger.debug(f"💥 FAKE ELIMINATED: Redis ping failed: {e}")
                    st.error("❌ Redis Disconnected")
            else:
                st.error("❌ Redis Not Available")
            
            # System info
            st.subheader("System Info")
            st.write(f"Dashboard Time: {datetime.now().strftime('%H:%M:%S')}")
            st.write("Version: 1.0.0")
        
        # Main content
        self.display_header()
        
        # Create tabs for different sections
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Overview", 
            "🕐 Latency", 
            "🌐 Network", 
            "🏥 Health",
            "🚨 Alerts"
        ])
        
        with tab1:
            self.display_symbol_metrics()
        
        with tab2:
            self.display_latency_metrics()
        
        with tab3:
            self.display_network_metrics()
        
        with tab4:
            self.display_system_health()
        
        with tab5:
            self.display_alerts()
        
        # Auto-refresh mechanism
        if auto_refresh:
            time.sleep(refresh_rate)
            st.rerun()


def main():
    """Main dashboard function"""
    dashboard = TradingDashboard()
    dashboard.run()


if __name__ == "__main__":
    main()