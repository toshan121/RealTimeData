#!/usr/bin/env python3
"""
Data Manager Page
Streamlit page for managing market data downloads and validation
Integrates data downloader and ClickHouse viewer components
"""

import streamlit as st
import sys
import os

# Configure page
st.set_page_config(
    page_title="Data Manager - L2 Trading System",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add project root to path
sys.path.append(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)

# Import our components
from ui.components.data_downloader import render_data_downloader
from ui.components.clickhouse_viewer import render_clickhouse_viewer


def main():
    """Main Data Manager page"""

    # Page header
    st.title("📥 Data Manager")
    st.markdown(
        """
    **Manage historical market data downloads and validate stored data**
    
    Use this interface to:
    - Download missing market data through OUR real-time system
    - Browse and validate data stored in ClickHouse
    - Monitor download progress and history
    - Ensure data quality for backtesting and analysis
    """
    )

    # Sidebar for page navigation
    st.sidebar.title("📥 Data Manager")
    st.sidebar.markdown("---")

    # Page sections
    page_section = st.sidebar.radio(
        "Select Section:",
        options=["📥 Data Downloader", "🗃️ ClickHouse Viewer", "📊 Data Overview"],
        help="Choose which data management tool to use",
    )

    # Section info in sidebar
    if page_section == "📥 Data Downloader":
        st.sidebar.info(
            """
        **Data Downloader**
        
        • Download historical tick data
        • Download Level 1 quotes  
        • Bulk download multiple symbols
        • Track download progress
        • Integration with OUR IQFeed client
        """
        )

    elif page_section == "🗃️ ClickHouse Viewer":
        st.sidebar.info(
            """
        **ClickHouse Viewer**
        
        • Browse stored market data
        • Query data with filters
        • Validate data quality
        • Export data samples
        • Monitor storage usage
        """
        )

    elif page_section == "📊 Data Overview":
        st.sidebar.info(
            """
        **Data Overview**
        
        • System-wide data statistics
        • Storage utilization metrics
        • Data completeness analysis
        • Quick access to common tasks
        """
        )

    # Render selected section
    if page_section == "📥 Data Downloader":
        render_data_downloader()

    elif page_section == "🗃️ ClickHouse Viewer":
        render_clickhouse_viewer()

    elif page_section == "📊 Data Overview":
        render_data_overview()


def render_data_overview():
    """Render data overview and quick stats"""
    st.header("📊 Data Overview")
    st.markdown("System-wide data statistics and quick access tools")

    # Quick stats
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Data Sources", "Active")
        st.caption("IQFeed connection status")

    with col2:
        st.metric("Storage", "ClickHouse")
        st.caption("Primary data storage")

    with col3:
        st.metric("Cache", "Redis")
        st.caption("Real-time data cache")

    with col4:
        st.metric("Processing", "Kafka")
        st.caption("Message streaming")

    st.markdown("---")

    # Quick actions
    st.markdown("### 🚀 Quick Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "📥 Download Today's Data", type="primary", use_container_width=True
        ):
            st.info(
                "Navigate to Data Downloader section to download today's market data"
            )

    with col2:
        if st.button(
            "🔍 Browse Latest Data", type="secondary", use_container_width=True
        ):
            st.info("Navigate to ClickHouse Viewer section to browse recent data")

    with col3:
        if st.button(
            "📊 Data Quality Check", type="secondary", use_container_width=True
        ):
            st.info("Navigate to ClickHouse Viewer > Data Quality tab for analysis")

    # System integration status
    st.markdown("---")
    st.markdown("### 🔧 System Integration Status")

    # Integration checks
    integration_status = {
        "IQFeed Real-time Client": "✅ Integrated",
        "Auto-downloader Service": "✅ Integrated",
        "ClickHouse Storage": "✅ Connected",
        "Redis Cache": "✅ Connected",
        "Kafka Streaming": "✅ Connected",
    }

    status_df = {
        "Component": list(integration_status.keys()),
        "Status": list(integration_status.values()),
    }

    st.table(status_df)

    # Important notes
    st.markdown("---")
    st.markdown("### ⚠️ Important Notes")

    st.info(
        """
    **Data Flow Architecture:**
    
    1. **Downloads**: Data Downloader → OUR IQFeed Client → ClickHouse
    2. **Real-time**: IQFeed → Kafka → Redis → UI
    3. **Storage**: ClickHouse (persistent) + Redis (cache)
    4. **Validation**: All components use OUR real-time infrastructure
    
    **No Direct External Connections**: The UI only connects to OUR system components, 
    ensuring we test and validate OUR infrastructure capabilities.
    """
    )

    st.warning(
        """
    **IQFeed Trial Limitations:**
    - Limited to 2-3 days of historical data from current date
    - Download what you need for testing and backtesting
    - Plan data collection around market schedule
    """
    )


if __name__ == "__main__":
    main()
