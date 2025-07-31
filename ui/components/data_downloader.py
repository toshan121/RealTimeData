#!/usr/bin/env python3
"""
Data Downloader UI Component
Interface to trigger downloads via OUR real-time system components
Tests and validates OUR infrastructure, not external providers

Uses IQFeedRealTimeClient to:
- Check existing data availability through OUR auto-downloader
- Trigger downloads through OUR real-time infrastructure
- Validate OUR system's download and storage capabilities
"""

import streamlit as st
import subprocess
import threading
import time
import json
import os
import sys
import redis
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
import pandas as pd

# Add project root to path
sys.path.append(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)

# Import OUR real-time system components
from realtime.core.iqfeed_realtime_client import IQFeedRealTimeClient


class DataDownloaderComponent:
    """
    Streamlit component for manual data downloads via OUR real-time system
    - Date/time picker interface
    - Symbol selection (single + bulk)
    - Data type selection (tick/L1/L2/bars)
    - Progress tracking during downloads
    - Success/error feedback
    - Integration with OUR IQFeedRealTimeClient for system validation

    This component tests and validates OUR real-time infrastructure by:
    - Using OUR auto-downloader for data availability checks
    - Triggering downloads through OUR real-time client
    - Validating OUR data flow and storage capabilities
    """

    def __init__(self):
        # Initialize OUR real-time client instead of direct external connections
        config = {
            "iqfeed": {
                "host": "127.0.0.1",
                "ports": {"level1": 5009, "level2": 5010, "admin": 9300},
            },
            "clickhouse": {
                "host": "localhost",
                "port": 9000,
                "database": "market_data",
            },
        }
        self.realtime_client = IQFeedRealTimeClient(config)

        # Initialize session state
        if "download_status" not in st.session_state:
            st.session_state.download_status = {}
        if "download_history" not in st.session_state:
            st.session_state.download_history = []
        if "bulk_symbols" not in st.session_state:
            st.session_state.bulk_symbols = []

    def render(self):
        """Render the data downloader interface"""
        st.header("📥 Data Downloader")
        st.markdown("Download historical market data from IQFeed")

        # Create tabs for different download modes
        tab1, tab2, tab3 = st.tabs(
            ["Single Symbol", "Bulk Download", "Download History"]
        )

        with tab1:
            self._render_single_download()

        with tab2:
            self._render_bulk_download()

        with tab3:
            self._render_download_history()

    def _render_single_download(self):
        """Render single symbol download interface"""
        st.subheader("Single Symbol Download")

        # Symbol input
        col1, col2 = st.columns([2, 1])

        with col1:
            symbol = (
                st.text_input(
                    "Stock Symbol",
                    value="AAPL",
                    help="Enter a stock symbol (e.g., AAPL, TSLA, MSFT)",
                )
                .upper()
                .strip()
            )

        with col2:
            # Quick symbol buttons
            if st.button("AAPL"):
                symbol = "AAPL"
            if st.button("TSLA"):
                symbol = "TSLA"
            if st.button("MSFT"):
                symbol = "MSFT"

        # Date selection
        col1, col2 = st.columns(2)

        with col1:
            download_date = st.date_input(
                "Date",
                value=date.today() - timedelta(days=1),  # Default to yesterday
                max_value=date.today(),
                help="Select the date for historical data download",
            )

        with col2:
            # Data type selection
            data_types = st.multiselect(
                "Data Types",
                options=["Tick", "Level 1", "Level 2"],
                default=["Tick", "Level 1"],
                help="Select which types of market data to download",
            )

        # Download options
        with st.expander("Advanced Options"):
            col1, col2 = st.columns(2)

            with col1:
                save_to_clickhouse = st.checkbox(
                    "Save to ClickHouse",
                    value=True,
                    help="Also save downloaded data to ClickHouse database",
                )

            with col2:
                force_redownload = st.checkbox(
                    "Force Re-download",
                    value=False,
                    help="Re-download even if data already exists",
                )

        # Check existing data
        if symbol:
            self._show_existing_data_status(symbol, download_date.strftime("%Y%m%d"))

        # Download button
        if st.button(
            "📥 Download Data", type="primary", disabled=not symbol or not data_types
        ):
            self._start_single_download(
                symbol, download_date, data_types, save_to_clickhouse, force_redownload
            )

        # Show download progress if active
        self._show_download_progress(f"single_{symbol}_{download_date}")

    def _render_bulk_download(self):
        """Render bulk download interface"""
        st.subheader("Bulk Symbol Download")

        # Symbol list input
        col1, col2 = st.columns([3, 1])

        with col1:
            symbols_text = st.text_area(
                "Stock Symbols (one per line)",
                height=100,
                help="Enter multiple stock symbols, one per line",
            )

            # Parse symbols
            if symbols_text:
                symbols = [
                    s.strip().upper() for s in symbols_text.split("\n") if s.strip()
                ]
                st.info(
                    f"Parsed {len(symbols)} symbols: {', '.join(symbols[:10])}{' ...' if len(symbols) > 10 else ''}"
                )

        with col2:
            # Predefined symbol lists
            st.markdown("**Quick Lists:**")

            if st.button("Top 10 Stocks"):
                top_10 = [
                    "AAPL",
                    "MSFT",
                    "GOOGL",
                    "AMZN",
                    "TSLA",
                    "META",
                    "NVDA",
                    "BRK.B",
                    "UNH",
                    "JNJ",
                ]
                st.session_state.bulk_symbols = top_10
                symbols_text = "\n".join(top_10)
                st.rerun()

            if st.button("Tech Stocks"):
                tech_stocks = [
                    "AAPL",
                    "MSFT",
                    "GOOGL",
                    "AMZN",
                    "META",
                    "NVDA",
                    "CRM",
                    "ADBE",
                    "NFLX",
                    "INTC",
                ]
                st.session_state.bulk_symbols = tech_stocks
                symbols_text = "\n".join(tech_stocks)
                st.rerun()

        # Date range selection
        col1, col2 = st.columns(2)

        with col1:
            start_date = st.date_input(
                "Start Date",
                value=date.today() - timedelta(days=7),  # Default to last week
                max_value=date.today(),
            )

        with col2:
            end_date = st.date_input(
                "End Date",
                value=date.today() - timedelta(days=1),  # Default to yesterday
                max_value=date.today(),
                min_value=start_date,
            )

        # Bulk options
        col1, col2 = st.columns(2)

        with col1:
            bulk_data_types = st.multiselect(
                "Data Types",
                options=["Tick", "Level 1"],  # Simplified for bulk
                default=["Tick", "Level 1"],
            )

        with col2:
            max_concurrent = st.slider(
                "Max Concurrent Downloads",
                min_value=1,
                max_value=5,
                value=2,
                help="Number of symbols to download simultaneously",
            )

        # Download button
        symbols = (
            [s.strip().upper() for s in symbols_text.split("\n") if s.strip()]
            if "symbols_text" in locals()
            else []
        )

        total_downloads = len(symbols) * (end_date - start_date).days if symbols else 0

        if total_downloads > 50:
            st.warning(
                f"⚠️ This will trigger {total_downloads} downloads. Consider reducing the date range or number of symbols."
            )

        if st.button(
            "📥 Start Bulk Download",
            type="primary",
            disabled=not symbols or not bulk_data_types,
        ):
            self._start_bulk_download(
                symbols, start_date, end_date, bulk_data_types, max_concurrent
            )

        # Show bulk progress
        self._show_download_progress("bulk_download")

    def _render_download_history(self):
        """Render download history and status"""
        st.subheader("Download History")

        if st.session_state.download_history:
            # Create DataFrame from history
            df = pd.DataFrame(st.session_state.download_history)
            df["Start Time"] = pd.to_datetime(df["start_time"]).dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            df["Duration"] = df.apply(self._format_duration, axis=1)
            df["Status"] = df["status"].apply(self._format_status)

            # Display table
            display_df = df[
                ["Start Time", "Symbol", "Date", "Data Types", "Status", "Duration"]
            ].sort_values("Start Time", ascending=False)
            st.dataframe(display_df, use_container_width=True)

            # Summary statistics
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                total_downloads = len(df)
                st.metric("Total Downloads", total_downloads)

            with col2:
                successful = len(df[df["status"] == "completed"])
                st.metric("Successful", successful)

            with col3:
                failed = len(df[df["status"] == "failed"])
                st.metric("Failed", failed)

            with col4:
                in_progress = len(df[df["status"] == "in_progress"])
                st.metric("In Progress", in_progress)

            # Clear history button
            if st.button("🗑️ Clear History"):
                st.session_state.download_history = []
                st.rerun()

        else:
            st.info("No download history available.")

    def _show_existing_data_status(self, symbol: str, date_str: str):
        """Show status of existing data for symbol/date"""
        try:
            (
                tick_exists,
                l1_exists,
            ) = self.realtime_client.auto_downloader.check_data_exists(symbol, date_str)

            col1, col2, col3 = st.columns(3)

            with col1:
                if tick_exists:
                    st.success("✅ Tick data exists")
                else:
                    st.warning("❌ Tick data missing")

            with col2:
                if l1_exists:
                    st.success("✅ L1 data exists")
                else:
                    st.warning("❌ L1 data missing")

            with col3:
                if tick_exists and l1_exists:
                    st.info("📊 All data available")
                elif tick_exists or l1_exists:
                    st.info("📊 Partial data available")
                else:
                    st.info("📊 No data available")

        except Exception as e:
            st.error(f"Error checking existing data: {e}")

    def _start_single_download(
        self,
        symbol: str,
        download_date: date,
        data_types: List[str],
        save_to_clickhouse: bool,
        force_redownload: bool,
    ):
        """Start single symbol download"""
        date_str = download_date.strftime("%Y%m%d")
        job_id = f"single_{symbol}_{date_str}"

        # Add to history
        download_entry = {
            "job_id": job_id,
            "symbol": symbol,
            "date": date_str,
            "data_types": ", ".join(data_types),
            "start_time": datetime.now(),
            "status": "in_progress",
            "save_to_clickhouse": save_to_clickhouse,
            "force_redownload": force_redownload,
        }

        st.session_state.download_history.append(download_entry)
        st.session_state.download_status[job_id] = {"status": "starting", "progress": 0}

        # Start download in background thread
        thread = threading.Thread(
            target=self._run_download_subprocess,
            args=(job_id, symbol, date_str, data_types, save_to_clickhouse),
            daemon=True,
        )
        thread.start()

        st.success(f"🚀 Started download for {symbol} on {date_str}")
        st.rerun()

    def _start_bulk_download(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
        data_types: List[str],
        max_concurrent: int,
    ):
        """Start bulk download"""
        job_id = "bulk_download"

        # Create date range
        date_range = []
        current_date = start_date
        while current_date <= end_date:
            date_range.append(current_date.strftime("%Y%m%d"))
            current_date += timedelta(days=1)

        # Create all symbol/date combinations
        download_pairs = [
            (symbol, date_str) for symbol in symbols for date_str in date_range
        ]

        # Add to history
        download_entry = {
            "job_id": job_id,
            "symbol": f"{len(symbols)} symbols",
            "date": f"{start_date} to {end_date}",
            "data_types": ", ".join(data_types),
            "start_time": datetime.now(),
            "status": "in_progress",
            "total_pairs": len(download_pairs),
        }

        st.session_state.download_history.append(download_entry)
        st.session_state.download_status[job_id] = {
            "status": "starting",
            "progress": 0,
            "total": len(download_pairs),
            "completed": 0,
            "failed": 0,
        }

        # Start bulk download in background thread
        thread = threading.Thread(
            target=self._run_bulk_download,
            args=(job_id, download_pairs, data_types, max_concurrent),
            daemon=True,
        )
        thread.start()

        st.success(
            f"🚀 Started bulk download: {len(symbols)} symbols, {len(date_range)} dates ({len(download_pairs)} total downloads)"
        )
        st.rerun()

    def _run_download_subprocess(
        self,
        job_id: str,
        symbol: str,
        date_str: str,
        data_types: List[str],
        save_to_clickhouse: bool,
    ):
        """Run download using OUR real-time client"""
        try:
            # Update status
            st.session_state.download_status[job_id]["status"] = "downloading"

            # Use OUR real-time client for download
            success = self.realtime_client.download_historical_data(
                symbol, date_str, save_to_clickhouse=save_to_clickhouse
            )

            # Update status based on result
            if success:
                st.session_state.download_status[job_id] = {
                    "status": "completed",
                    "progress": 100,
                }
                # Update history
                for entry in st.session_state.download_history:
                    if entry["job_id"] == job_id:
                        entry["status"] = "completed"
                        entry["end_time"] = datetime.now()
                        break
            else:
                st.session_state.download_status[job_id] = {
                    "status": "failed",
                    "progress": 0,
                    "error": "Download failed",
                }
                # Update history
                for entry in st.session_state.download_history:
                    if entry["job_id"] == job_id:
                        entry["status"] = "failed"
                        entry["end_time"] = datetime.now()
                        break

        except Exception as e:
            st.session_state.download_status[job_id] = {
                "status": "failed",
                "progress": 0,
                "error": str(e),
            }
            # Update history
            for entry in st.session_state.download_history:
                if entry["job_id"] == job_id:
                    entry["status"] = "failed"
                    entry["end_time"] = datetime.now()
                    entry["error"] = str(e)
                    break

    def _run_bulk_download(
        self,
        job_id: str,
        download_pairs: List[Tuple[str, str]],
        data_types: List[str],
        max_concurrent: int,
    ):
        """Run bulk download with concurrency control"""
        try:
            completed = 0
            failed = 0

            for i, (symbol, date_str) in enumerate(download_pairs):
                try:
                    # Update progress
                    progress = (i / len(download_pairs)) * 100
                    st.session_state.download_status[job_id].update(
                        {
                            "status": "downloading",
                            "progress": progress,
                            "completed": completed,
                            "failed": failed,
                            "current_symbol": symbol,
                            "current_date": date_str,
                        }
                    )

                    # Download using OUR real-time client
                    success = self.realtime_client.download_historical_data(
                        symbol, date_str, save_to_clickhouse=True
                    )

                    if success:
                        completed += 1
                    else:
                        failed += 1

                    # Rate limiting
                    if i % max_concurrent == 0 and i > 0:
                        time.sleep(1)  # Brief pause between batches

                except Exception as e:
                    failed += 1
                    print(f"Error downloading {symbol} {date_str}: {e}")

            # Final status
            st.session_state.download_status[job_id] = {
                "status": "completed",
                "progress": 100,
                "completed": completed,
                "failed": failed,
                "total": len(download_pairs),
            }

            # Update history
            for entry in st.session_state.download_history:
                if entry["job_id"] == job_id:
                    entry["status"] = "completed"
                    entry["end_time"] = datetime.now()
                    entry["completed"] = completed
                    entry["failed"] = failed
                    break

        except Exception as e:
            st.session_state.download_status[job_id] = {
                "status": "failed",
                "error": str(e),
            }
            # Update history
            for entry in st.session_state.download_history:
                if entry["job_id"] == job_id:
                    entry["status"] = "failed"
                    entry["end_time"] = datetime.now()
                    entry["error"] = str(e)
                    break

    def _show_download_progress(self, job_id: str):
        """Show download progress for a job"""
        if job_id in st.session_state.download_status:
            status = st.session_state.download_status[job_id]

            if status["status"] == "starting":
                st.info("🔄 Initializing download...")

            elif status["status"] == "downloading":
                progress = status.get("progress", 0)
                st.progress(progress / 100)

                if "current_symbol" in status:
                    st.info(
                        f"📥 Downloading {status['current_symbol']} for {status['current_date']} - {status['completed']}/{status['total']} completed"
                    )
                else:
                    st.info(f"📥 Downloading... {progress:.1f}% complete")

            elif status["status"] == "completed":
                st.success("✅ Download completed successfully!")
                if "completed" in status:
                    st.info(
                        f"📊 Results: {status['completed']} successful, {status['failed']} failed out of {status['total']} total"
                    )

            elif status["status"] == "failed":
                st.error(f"❌ Download failed: {status.get('error', 'Unknown error')}")

    def _format_duration(self, row) -> str:
        """Format duration for display"""
        if "end_time" in row and row["end_time"]:
            duration = row["end_time"] - row["start_time"]
            return f"{duration.total_seconds():.1f}s"
        elif row["status"] == "in_progress":
            duration = datetime.now() - row["start_time"]
            return f"{duration.total_seconds():.1f}s (ongoing)"
        else:
            return "N/A"

    def _format_status(self, status: str) -> str:
        """Format status for display"""
        status_mapping = {
            "in_progress": "🔄 In Progress",
            "completed": "✅ Completed",
            "failed": "❌ Failed",
        }
        return status_mapping.get(status, status)


def render_data_downloader():
    """Standalone function to render data downloader component"""
    component = DataDownloaderComponent()
    component.render()
