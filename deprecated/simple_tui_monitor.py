#!/usr/bin/env python3
"""
Simple TUI (Terminal User Interface) Monitor for Market Data System
Uses Rich for easy testing and clean display
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
import click
import psutil
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn

# Service connections (imported when needed to avoid errors)
console = Console()


class SystemMonitor:
    """Monitor system services and data flow."""
    
    def __init__(self):
        self.console = Console()
        self.services_status = {}
        self.kafka_stats = {}
        self.lag_stats = []
        self.recording_pid = None
        
    def check_redis(self) -> Dict[str, Any]:
        """Check Redis status."""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6380)  # Docker Redis
            if r.ping():
                info = r.info()
                return {
                    'status': 'UP',
                    'keys': info.get('db0', {}).get('keys', 0),
                    'memory': info.get('used_memory_human', 'N/A')
                }
        except:
            pass
        return {'status': 'DOWN', 'keys': 0, 'memory': 'N/A'}
    
    def check_clickhouse(self) -> Dict[str, Any]:
        """Check ClickHouse status."""
        try:
            import clickhouse_connect
            client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='l2_market_data',
                username='l2_user',
                password='l2_secure_pass'
            )
            
            # Get row counts
            tables = {}
            for table in ['trades', 'quotes', 'order_book_updates']:
                result = client.query(f'SELECT COUNT(*) FROM {table}')
                tables[table] = result.result_rows[0][0] if result.result_rows else 0
                
            return {'status': 'UP', 'tables': tables}
        except:
            return {'status': 'DOWN', 'tables': {}}
    
    def check_kafka(self) -> Dict[str, Any]:
        """Check Kafka status."""
        try:
            from kafka import KafkaConsumer
            consumer = KafkaConsumer(
                bootstrap_servers='localhost:9092',
                consumer_timeout_ms=1000
            )
            topics = consumer.topics()
            consumer.close()
            return {'status': 'UP', 'topics': len(topics) if topics else 0}
        except:
            return {'status': 'DOWN', 'topics': 0}
    
    def check_recording_process(self) -> Dict[str, Any]:
        """Check if recording process is running."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if 'start_495_stock_recording.py' in cmdline:
                    return {'status': 'RUNNING', 'pid': proc.info['pid']}
            except:
                pass
        return {'status': 'STOPPED', 'pid': None}
    
    def get_lag_stats(self) -> list:
        """Get recent lag statistics from ClickHouse."""
        try:
            import clickhouse_connect
            client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='l2_market_data',
                username='l2_user',
                password='l2_secure_pass'
            )
            
            query = """
            SELECT 
                toStartOfMinute(timestamp) as minute,
                avg(network_lag_ms) as network_lag,
                avg(processing_lag_ms) as processing_lag,
                avg(total_lag_ms) as total_lag,
                max(total_lag_ms) as max_lag
            FROM (
                SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms 
                FROM trades WHERE timestamp > now() - INTERVAL 10 MINUTE
                UNION ALL
                SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms 
                FROM quotes WHERE timestamp > now() - INTERVAL 10 MINUTE
            )
            GROUP BY minute
            ORDER BY minute DESC
            LIMIT 10
            """
            
            result = client.query(query)
            return [
                {
                    'time': row[0].strftime('%H:%M'),
                    'network': round(row[1], 2) if row[1] else 0,
                    'processing': round(row[2], 2) if row[2] else 0,
                    'total': round(row[3], 2) if row[3] else 0,
                    'max': round(row[4], 2) if row[4] else 0,
                }
                for row in result.result_rows
            ]
        except:
            return []
    
    def create_status_table(self) -> Table:
        """Create service status table."""
        table = Table(title="System Status", show_header=True)
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Details", style="dim")
        
        # Redis
        redis_info = self.check_redis()
        status_style = "green" if redis_info['status'] == 'UP' else "red"
        table.add_row(
            "Redis",
            Text(redis_info['status'], style=status_style),
            f"Keys: {redis_info['keys']}, Memory: {redis_info['memory']}"
        )
        
        # ClickHouse
        ch_info = self.check_clickhouse()
        status_style = "green" if ch_info['status'] == 'UP' else "red"
        details = ""
        if ch_info['tables']:
            details = f"Trades: {ch_info['tables'].get('trades', 0):,}, "
            details += f"Quotes: {ch_info['tables'].get('quotes', 0):,}, "
            details += f"L2: {ch_info['tables'].get('order_book_updates', 0):,}"
        table.add_row(
            "ClickHouse",
            Text(ch_info['status'], style=status_style),
            details
        )
        
        # Kafka
        kafka_info = self.check_kafka()
        status_style = "green" if kafka_info['status'] == 'UP' else "red"
        table.add_row(
            "Kafka",
            Text(kafka_info['status'], style=status_style),
            f"Topics: {kafka_info['topics']}"
        )
        
        # Recording Process
        rec_info = self.check_recording_process()
        status_style = "green" if rec_info['status'] == 'RUNNING' else "yellow"
        details = f"PID: {rec_info['pid']}" if rec_info['pid'] else "Not running"
        table.add_row(
            "Recording",
            Text(rec_info['status'], style=status_style),
            details
        )
        
        return table
    
    def create_lag_table(self) -> Table:
        """Create lag statistics table."""
        table = Table(title="Lag Statistics (ms)", show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Network", style="blue")
        table.add_column("Processing", style="green")
        table.add_column("Total", style="yellow")
        table.add_column("Max", style="red")
        
        lag_stats = self.get_lag_stats()
        for stat in lag_stats[:5]:  # Show last 5 minutes
            table.add_row(
                stat['time'],
                str(stat['network']),
                str(stat['processing']),
                str(stat['total']),
                str(stat['max'])
            )
        
        return table
    
    def create_dashboard(self) -> Layout:
        """Create the full dashboard layout."""
        layout = Layout()
        
        layout.split_column(
            Layout(Panel(
                Text("Market Data Monitor TUI", justify="center", style="bold cyan"),
                title="Real-Time System Monitor"
            ), size=3),
            Layout(name="main"),
            Layout(Panel(
                f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                "Commands: [r]ecord, [s]top, [q]uit",
                style="dim"
            ), size=3)
        )
        
        # Split main area
        layout["main"].split_row(
            Layout(self.create_status_table(), name="status"),
            Layout(self.create_lag_table(), name="lag")
        )
        
        return layout


@click.group()
def cli():
    """Market Data System TUI Monitor."""
    pass


@cli.command()
@click.option('--refresh', default=5, help='Refresh interval in seconds')
def monitor(refresh):
    """Start the monitoring dashboard."""
    monitor = SystemMonitor()
    
    console.print("[bold cyan]Starting Market Data Monitor TUI...[/bold cyan]")
    console.print(f"Refresh interval: {refresh} seconds")
    console.print("Press Ctrl+C to exit\n")
    
    try:
        with Live(monitor.create_dashboard(), refresh_per_second=1/refresh) as live:
            while True:
                time.sleep(refresh)
                live.update(monitor.create_dashboard())
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")


@cli.command()
def start_recording():
    """Start recording 495 stocks."""
    console.print("[cyan]Starting 495 stock recording...[/cyan]")
    import subprocess
    try:
        subprocess.Popen(['python', 'start_495_stock_recording.py'])
        console.print("[green]✓ Recording started successfully[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to start recording: {e}[/red]")


@cli.command()
def stop_recording():
    """Stop recording process."""
    console.print("[cyan]Stopping recording process...[/cyan]")
    stopped = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'start_495_stock_recording.py' in cmdline:
                proc.terminate()
                console.print(f"[green]✓ Stopped process PID: {proc.info['pid']}[/green]")
                stopped = True
        except:
            pass
    
    if not stopped:
        console.print("[yellow]No recording process found[/yellow]")


@cli.command()
def test_services():
    """Test all service connections."""
    monitor = SystemMonitor()
    
    console.print("[bold]Testing Service Connections[/bold]\n")
    
    # Test each service
    services = [
        ("Redis", monitor.check_redis()),
        ("ClickHouse", monitor.check_clickhouse()),
        ("Kafka", monitor.check_kafka()),
        ("Recording", monitor.check_recording_process())
    ]
    
    all_up = True
    for name, info in services:
        status = info.get('status', 'UNKNOWN')
        if status in ['UP', 'RUNNING']:
            console.print(f"✓ {name}: [green]{status}[/green]")
        else:
            console.print(f"✗ {name}: [red]{status}[/red]")
            all_up = False
    
    if all_up:
        console.print("\n[green]All services operational![/green]")
    else:
        console.print("\n[yellow]Some services need attention[/yellow]")
    
    return 0 if all_up else 1


if __name__ == '__main__':
    cli()