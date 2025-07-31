#!/usr/bin/env python3
"""
Minimal ClickHouse Data Viewer
Ultra-simple interface for viewing stored market data - NO over-engineering!

CORE REQUIREMENTS ONLY:
- Connect to ClickHouse database
- Display market data in table format 
- Basic filtering by symbol and date range
- Simple pagination for large result sets
- Export to CSV functionality (basic)

ANTI-OVER-ENGINEERING:
- NO complex SQL query builder
- NO advanced data visualization 
- NO big data analytics features
- NO sophisticated filtering beyond basics
- NO multi-database join capabilities
"""

import streamlit as st
import pandas as pd
import clickhouse_connect
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any
import logging
import io
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MinimalClickHouseViewer:
    """Ultra-simple ClickHouse data viewer - shows data from database, nothing more."""
    
    def __init__(self):
        """Initialize with basic ClickHouse connection settings from environment."""
        self.config = {
            'host': os.getenv('CLICKHOUSE_HOST', 'localhost'),
            'port': int(os.getenv('CLICKHOUSE_PORT', '8123')),
            'database': os.getenv('CLICKHOUSE_DATABASE', 'l2_market_data'),
            'username': os.getenv('CLICKHOUSE_USER', 'l2_user'),
            'password': os.getenv('CLICKHOUSE_PASSWORD', 'l2_secure_pass')
        }
        self.client = None
        # Whitelist of allowed tables for security
        self.available_tables = ['l2_updates', 'trades', 'quotes', 'features', 'backtest_trades']
    
    def __del__(self):
        """Cleanup database connection when object is destroyed."""
        self.close_connection()
    
    def close_connection(self):
        """Explicitly close database connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            finally:
                self.client = None
    
    def connect(self) -> bool:
        """Simple connection to ClickHouse - basic success/failure."""
        try:
            self.client = clickhouse_connect.get_client(
                host=self.config['host'],
                port=self.config['port'],
                database=self.config['database'],
                username=self.config['username'],
                password=self.config['password']
            )
            # Test with simple query
            result = self.client.query("SELECT 1")
            return len(result.result_rows) > 0
        except clickhouse_connect.driver.exceptions.DatabaseError as e:
            logger.error(f"Database connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def get_data(self, table: str, symbol: Optional[str] = None, 
                 start_date: Optional[date] = None, end_date: Optional[date] = None,
                 limit: int = 1000) -> pd.DataFrame:
        """Simple data retrieval with basic filters using parameterized queries."""
        if not self.client:
            logger.error("No database connection available")
            return pd.DataFrame()
        
        # Validate table name against whitelist
        if table not in self.available_tables:
            logger.error(f"Invalid table name: {table}")
            return pd.DataFrame()
        
        # Validate date range
        if start_date and end_date and start_date > end_date:
            logger.error("Start date cannot be after end date")
            return pd.DataFrame()
        
        # Validate limit
        if limit < 1 or limit > 10000:
            logger.error(f"Invalid limit: {limit}. Must be between 1 and 10000")
            return pd.DataFrame()
            
        try:
            # Build parameterized query to prevent SQL injection
            query = f"SELECT * FROM {table}"  # Table name validated above
            conditions = []
            parameters = {}
            
            # Basic date filtering with parameters
            if start_date:
                conditions.append("toDate(timestamp) >= %(start_date)s")
                parameters['start_date'] = start_date.strftime('%Y-%m-%d')
            if end_date:
                conditions.append("toDate(timestamp) <= %(end_date)s")
                parameters['end_date'] = end_date.strftime('%Y-%m-%d')
            
            # Basic symbol filtering with parameters
            if symbol and symbol.strip():
                conditions.append("symbol = %(symbol)s")
                parameters['symbol'] = symbol.upper().strip()
            
            # Add WHERE clause if we have conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            # Basic ordering and limit (limit validated above)
            query += " ORDER BY timestamp DESC"
            query += f" LIMIT {limit}"
            
            # Execute parameterized query
            result = self.client.query(query, parameters=parameters)
            
            # Convert to DataFrame
            if result.result_rows:
                df = pd.DataFrame(result.result_rows, columns=result.column_names)
                return df
            else:
                return pd.DataFrame()
                
        except clickhouse_connect.driver.exceptions.DatabaseError as e:
            logger.error(f"Database error: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return pd.DataFrame()
    
    def get_table_info(self, table: str) -> Dict[str, Any]:
        """Basic table information - row count and date range."""
        if not self.client:
            logger.error("No database connection available")
            return {}
        
        # Validate table name against whitelist
        if table not in self.available_tables:
            logger.error(f"Invalid table name: {table}")
            return {}
            
        try:
            # Simple row count (table name already validated)
            count_result = self.client.query(f"SELECT count(*) FROM {table}")
            row_count = count_result.result_rows[0][0] if count_result.result_rows else 0
            
            # Basic date range (table name already validated)
            date_result = self.client.query(f"SELECT min(toDate(timestamp)), max(toDate(timestamp)) FROM {table}")
            min_date, max_date = date_result.result_rows[0] if date_result.result_rows else (None, None)
            
            return {
                'row_count': row_count,
                'min_date': min_date,
                'max_date': max_date
            }
        except clickhouse_connect.driver.exceptions.DatabaseError as e:
            logger.error(f"Database error getting table info: {e}")
            return {}
        except Exception as e:
            logger.error(f"Table info failed: {e}")
            return {}

def main():
    """Main Streamlit interface - ultra-simple UI for viewing data."""
    st.set_page_config(page_title="ClickHouse Data Viewer", layout="wide")
    
    st.title("🗃️ ClickHouse Data Viewer")
    st.markdown("**Simple interface for viewing stored market data**")
    
    # Initialize viewer
    viewer = MinimalClickHouseViewer()
    
    # Connection status
    st.subheader("Connection Status")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if viewer.connect():
            st.success("✅ Connected to ClickHouse")
            connected = True
        else:
            st.error("❌ Failed to connect to ClickHouse")
            st.info("Make sure ClickHouse is running: `docker-compose up -d clickhouse`")
            connected = False
    
    with col2:
        st.info(f"📍 {viewer.config['host']}:{viewer.config['port']}")
    
    if not connected:
        st.stop()
    
    # Basic data viewer interface
    st.subheader("Data Viewer")
    
    # Simple table selection
    col1, col2 = st.columns(2)
    
    with col1:
        selected_table = st.selectbox(
            "Select Table:",
            options=viewer.available_tables,
            help="Choose a market data table to view"
        )
    
    with col2:
        # Show basic table info
        table_info = viewer.get_table_info(selected_table)
        if table_info:
            st.info(f"📊 Rows: {table_info.get('row_count', 0):,}")
            if table_info.get('min_date') and table_info.get('max_date'):
                st.info(f"📅 {table_info['min_date']} to {table_info['max_date']}")
    
    # Basic filters
    st.markdown("**Filters:**")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        symbol_filter = st.text_input(
            "Symbol (optional):",
            placeholder="e.g., AAPL",
            help="Filter by specific symbol"
        )
    
    with col2:
        start_date = st.date_input(
            "Start Date:",
            value=date.today() - timedelta(days=1),
            help="Filter from this date"
        )
    
    with col3:
        end_date = st.date_input(
            "End Date:", 
            value=date.today(),
            help="Filter to this date"
        )
    
    with col4:
        limit = st.selectbox(
            "Record Limit:",
            options=[100, 500, 1000, 2000, 5000],
            index=2,
            help="Maximum records to display"
        )
    
    # Query data button
    if st.button("🔍 View Data", type="primary"):
        with st.spinner("Retrieving data..."):
            df = viewer.get_data(
                table=selected_table,
                symbol=symbol_filter if symbol_filter.strip() else None,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            
            if not df.empty:
                st.success(f"✅ Retrieved {len(df)} records")
                
                # Display data in simple table
                st.subheader("Data")
                st.dataframe(df, use_container_width=True, height=400)
                
                # Basic CSV export
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_data = csv_buffer.getvalue()
                
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"{selected_table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
                
                # Basic data summary
                st.subheader("Basic Summary")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Rows", len(df))
                
                with col2:
                    st.metric("Columns", len(df.columns))
                
                with col3:
                    if 'symbol' in df.columns:
                        unique_symbols = df['symbol'].nunique()
                        st.metric("Unique Symbols", unique_symbols)
                
            else:
                st.warning("⚠️ No data found with the specified filters")
    
    # Simple help section
    with st.expander("💡 Help"):
        st.markdown("""
        **How to use this viewer:**
        1. Select a table from the dropdown
        2. Optionally filter by symbol and date range  
        3. Click "View Data" to retrieve records
        4. Use "Download CSV" to export data
        
        **Available Tables:**
        - `l2_updates`: Level 2 order book updates
        - `trades`: Trade executions
        - `quotes`: NBBO quotes  
        - `features`: Calculated market features
        - `backtest_trades`: Backtesting results
        
        **Environment Variables (optional):**
        - `CLICKHOUSE_HOST`: Database host (default: localhost)
        - `CLICKHOUSE_PORT`: Database port (default: 8123)
        - `CLICKHOUSE_DATABASE`: Database name (default: l2_market_data)
        - `CLICKHOUSE_USER`: Username (default: l2_user)
        - `CLICKHOUSE_PASSWORD`: Password (default: l2_secure_pass)
        """)

if __name__ == "__main__":
    main()