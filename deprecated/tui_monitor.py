#!/usr/bin/env python3
"""
Advanced TUI Monitor for Market Data System
Rich + Click based terminal interface with full functionality
"""
import asyncio
import json
import time
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path

import click
import psutil
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
from rich.prompt import Prompt, Confirm
from rich.columns import Columns
from rich.align import Align


class ServiceManager:
    """Manage system services and processes."""
    
    def __init__(self):
        self.console = Console()
        self._last_check = {}
        self._cache_duration = 2  # seconds
        
    def _is_cache_valid(self, service: str) -> bool:
        """Check if cached result is still valid."""
        if service not in self._last_check:
            return False
        return (time.time() - self._last_check[service]['time']) < self._cache_duration
    
    def _update_cache(self, service: str, result: Dict[str, Any]):
        """Update cache with result."""
        self._last_check[service] = {
            'time': time.time(),
            'result': result
        }
    
    def check_redis(self) -> Dict[str, Any]:
        """Check Redis status with caching."""
        if self._is_cache_valid('redis'):
            return self._last_check['redis']['result']
            
        try:
            import redis
            # Try Docker Redis first (port 6380), then host Redis (6379)
            for port in [6380, 6379]:
                try:
                    r = redis.Redis(host='localhost', port=port, socket_connect_timeout=1)
                    if r.ping():
                        info = r.info()
                        result = {
                            'status': 'UP',
                            'port': port,
                            'keys': info.get('db0', {}).get('keys', 0),
                            'memory': info.get('used_memory_human', 'N/A'),
                            'clients': info.get('connected_clients', 0)
                        }
                        self._update_cache('redis', result)
                        return result
                except:
                    continue
        except ImportError:
            pass
        except Exception as e:
            pass
            
        result = {'status': 'DOWN', 'port': None, 'keys': 0, 'memory': 'N/A', 'clients': 0}
        self._update_cache('redis', result)
        return result
    
    def check_clickhouse(self) -> Dict[str, Any]:
        """Check ClickHouse status with caching."""
        if self._is_cache_valid('clickhouse'):
            return self._last_check['clickhouse']['result']
            
        try:
            import clickhouse_connect
            client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='l2_market_data',
                username='l2_user',
                password='l2_secure_pass',
                connect_timeout=2
            )
            
            # Get row counts for each table
            tables = {}
            total_rows = 0
            for table in ['trades', 'quotes', 'order_book_updates']:
                try:
                    result_query = client.query(f'SELECT COUNT(*) FROM {table}')
                    count = result_query.result_rows[0][0] if result_query.result_rows else 0
                    tables[table] = count
                    total_rows += count
                except:
                    tables[table] = 0
                    
            result = {
                'status': 'UP',
                'tables': tables,
                'total_rows': total_rows
            }
            self._update_cache('clickhouse', result)
            return result
            
        except ImportError:
            pass
        except Exception as e:
            pass
            
        result = {'status': 'DOWN', 'tables': {}, 'total_rows': 0}
        self._update_cache('clickhouse', result)
        return result
    
    def check_kafka(self) -> Dict[str, Any]:
        """Check Kafka status with caching."""
        if self._is_cache_valid('kafka'):
            return self._last_check['kafka']['result']
            
        try:
            from kafka import KafkaConsumer, KafkaAdminClient
            admin = KafkaAdminClient(
                bootstrap_servers='localhost:9092',
                request_timeout_ms=2000
            )
            
            # Get topic information
            topics = admin.list_topics()
            topic_details = {}
            
            # Get partition info for main topics
            main_topics = ['trades', 'quotes', 'l2_order_book', 'simulation']
            for topic in main_topics:
                if topic in topics:
                    try:
                        consumer = KafkaConsumer(
                            topic,
                            bootstrap_servers='localhost:9092',
                            auto_offset_reset='latest',
                            consumer_timeout_ms=1000
                        )
                        partitions = consumer.partitions_for_topic(topic)
                        if partitions:
                            # Get latest offset
                            consumer.seek_to_end()
                            latest_offset = 0
                            for partition in partitions:
                                offset = consumer.position((topic, partition))
                                latest_offset += offset
                            topic_details[topic] = {
                                'partitions': len(partitions),
                                'latest_offset': latest_offset
                            }
                        consumer.close()
                    except:
                        topic_details[topic] = {'partitions': 0, 'latest_offset': 0}
            
            result = {
                'status': 'UP',
                'total_topics': len(topics),
                'topics': topic_details
            }
            self._update_cache('kafka', result)
            return result
            
        except ImportError:
            pass
        except Exception as e:
            pass
            
        result = {'status': 'DOWN', 'total_topics': 0, 'topics': {}}
        self._update_cache('kafka', result)
        return result
    
    def check_iqfeed(self) -> Dict[str, Any]:
        """Check IQFeed Docker container status."""
        if self._is_cache_valid('iqfeed'):
            return self._last_check['iqfeed']['result']
            
        try:
            # Check if Docker container is running
            result = subprocess.run(
                ['docker', 'ps', '--filter', 'name=iqfeed', '--format', '{{.Names}}'],
                capture_output=True, text=True, timeout=3
            )
            
            if 'iqfeed' in result.stdout:
                # Container is running, check health
                health_result = subprocess.run(
                    ['docker', 'inspect', '--format', '{{.State.Health.Status}}', 'iqfeed'],
                    capture_output=True, text=True, timeout=3
                )
                health = health_result.stdout.strip()
                
                # Test port connectivity
                import socket
                ports_open = 0
                test_ports = [5009, 9100, 9200, 9300]
                for port in test_ports:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        if sock.connect_ex(('localhost', port)) == 0:
                            ports_open += 1
                        sock.close()
                    except:
                        pass
                
                result_data = {
                    'status': 'UP' if health == 'healthy' else 'STARTING',
                    'health': health,
                    'ports_open': f"{ports_open}/{len(test_ports)}"
                }
            else:
                result_data = {'status': 'DOWN', 'health': 'not_running', 'ports_open': '0/4'}
                
        except Exception as e:
            result_data = {'status': 'ERROR', 'health': 'unknown', 'ports_open': '0/4'}
        
        self._update_cache('iqfeed', result_data)
        return result_data
    
    def check_recording_processes(self) -> Dict[str, Any]:
        """Check recording and simulation processes."""
        if self._is_cache_valid('processes'):
            return self._last_check['processes']['result']
            
        processes = {
            'recording': None,
            'simulation': [],
            'total': 0
        }
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                
                if 'start_495_stock_recording.py' in cmdline:
                    processes['recording'] = {
                        'pid': proc.info['pid'],
                        'uptime': time.time() - proc.info['create_time']
                    }
                    processes['total'] += 1
                    
                elif any(sim in cmdline for sim in ['simple_synthetic_test.py', 'production_replay_example.py']):
                    sim_type = 'synthetic' if 'synthetic' in cmdline else 'replay'
                    processes['simulation'].append({
                        'pid': proc.info['pid'],
                        'type': sim_type,
                        'uptime': time.time() - proc.info['create_time']
                    })
                    processes['total'] += 1
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        self._update_cache('processes', processes)
        return processes
    
    def get_lag_statistics(self) -> List[Dict[str, Any]]:
        """Get lag statistics from ClickHouse."""
        try:
            import clickhouse_connect
            client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='l2_market_data',
                username='l2_user',
                password='l2_secure_pass',
                connect_timeout=2
            )
            
            query = """
            SELECT 
                toStartOfMinute(timestamp) as minute,
                avg(network_lag_ms) as network_lag,
                avg(processing_lag_ms) as processing_lag,
                avg(total_lag_ms) as total_lag,
                max(total_lag_ms) as max_lag,
                count() as message_count
            FROM (
                SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms 
                FROM trades WHERE timestamp > now() - INTERVAL 15 MINUTE
                UNION ALL
                SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms 
                FROM quotes WHERE timestamp > now() - INTERVAL 15 MINUTE
            )
            GROUP BY minute
            ORDER BY minute DESC
            LIMIT 15
            """
            
            result = client.query(query)
            return [
                {
                    'time': row[0].strftime('%H:%M'),
                    'network': round(row[1], 2) if row[1] else 0,
                    'processing': round(row[2], 2) if row[2] else 0,
                    'total': round(row[3], 2) if row[3] else 0,
                    'max': round(row[4], 2) if row[4] else 0,
                    'messages': int(row[5]) if row[5] else 0
                }
                for row in result.result_rows
            ]
        except:
            return []


class TUIMonitor:
    """Main TUI monitoring class."""
    
    def __init__(self):
        self.console = Console()
        self.service_manager = ServiceManager()
        self.running = False
        
    def create_service_status_table(self) -> Table:
        """Create service status table."""
        table = Table(title="🔧 System Services", show_header=True, header_style="bold cyan")
        table.add_column("Service", style="white", width=12)
        table.add_column("Status", width=10)
        table.add_column("Details", style="dim")
        
        # Redis
        redis_info = self.service_manager.check_redis()
        status_style = "green" if redis_info['status'] == 'UP' else "red"
        details = f"Port: {redis_info['port']}, Keys: {redis_info['keys']}, Clients: {redis_info['clients']}"
        table.add_row(
            "Redis",
            Text("●", style=status_style) + f" {redis_info['status']}",
            details
        )
        
        # ClickHouse
        ch_info = self.service_manager.check_clickhouse()
        status_style = "green" if ch_info['status'] == 'UP' else "red"
        if ch_info['tables']:
            details = f"Total: {ch_info['total_rows']:,} rows | "
            details += f"Trades: {ch_info['tables'].get('trades', 0):,} | "
            details += f"Quotes: {ch_info['tables'].get('quotes', 0):,} | "
            details += f"L2: {ch_info['tables'].get('order_book_updates', 0):,}"
        else:
            details = "No connection"
        table.add_row(
            "ClickHouse",
            Text("●", style=status_style) + f" {ch_info['status']}",
            details
        )
        
        # Kafka
        kafka_info = self.service_manager.check_kafka()
        status_style = "green" if kafka_info['status'] == 'UP' else "red"
        if kafka_info['topics']:
            details = f"Topics: {kafka_info['total_topics']} | Active: {len(kafka_info['topics'])}"
        else:
            details = "No topics available"
        table.add_row(
            "Kafka",
            Text("●", style=status_style) + f" {kafka_info['status']}",
            details
        )
        
        # IQFeed
        iqfeed_info = self.service_manager.check_iqfeed()
        status_color = "green" if iqfeed_info['status'] == 'UP' else ("yellow" if iqfeed_info['status'] == 'STARTING' else "red")
        details = f"Health: {iqfeed_info['health']}, Ports: {iqfeed_info['ports_open']}"
        table.add_row(
            "IQFeed",
            Text("●", style=status_color) + f" {iqfeed_info['status']}",
            details
        )
        
        return table
    
    def create_process_status_table(self) -> Table:
        """Create process status table."""
        table = Table(title="⚡ Active Processes", show_header=True, header_style="bold yellow")
        table.add_column("Process", style="white", width=15)
        table.add_column("Status", width=10)
        table.add_column("Details", style="dim")
        
        processes = self.service_manager.check_recording_processes()
        
        # Recording process
        if processes['recording']:
            uptime_str = f"{int(processes['recording']['uptime']/60)}m {int(processes['recording']['uptime']%60)}s"
            table.add_row(
                "495 Recording",
                Text("●", style="green") + " RUNNING",
                f"PID: {processes['recording']['pid']}, Uptime: {uptime_str}"
            )
        else:
            table.add_row(
                "495 Recording",
                Text("●", style="red") + " STOPPED",
                "Not running"
            )
        
        # Simulation processes
        if processes['simulation']:
            for sim in processes['simulation']:
                uptime_str = f"{int(sim['uptime']/60)}m {int(sim['uptime']%60)}s"
                table.add_row(
                    f"Simulation",
                    Text("●", style="green") + " RUNNING",
                    f"Type: {sim['type']}, PID: {sim['pid']}, Uptime: {uptime_str}"
                )
        else:
            table.add_row(
                "Simulation",
                Text("●", style="dim_white") + " STOPPED",
                "No simulations running"
            )
        
        return table
    
    def create_lag_statistics_table(self) -> Table:
        """Create lag statistics table."""
        table = Table(title="📊 Lag Statistics (Last 15 min)", show_header=True, header_style="bold magenta")
        table.add_column("Time", style="cyan", width=8)
        table.add_column("Network", style="blue", width=10)
        table.add_column("Processing", style="green", width=12)
        table.add_column("Total", style="yellow", width=10)
        table.add_column("Max", style="red", width=10)
        table.add_column("Messages", style="dim", width=10)
        
        lag_stats = self.service_manager.get_lag_statistics()
        for stat in lag_stats[:8]:  # Show last 8 minutes
            table.add_row(
                stat['time'],
                f"{stat['network']:.1f}ms",
                f"{stat['processing']:.1f}ms",
                f"{stat['total']:.1f}ms",
                f"{stat['max']:.1f}ms",
                f"{stat['messages']:,}"
            )
        
        if not lag_stats:
            table.add_row("--", "No data", "No data", "No data", "No data", "0")
        
        return table
    
    def create_kafka_topics_table(self) -> Table:
        """Create Kafka topics status table."""
        table = Table(title="📡 Kafka Topics", show_header=True, header_style="bold blue")
        table.add_column("Topic", style="white")
        table.add_column("Partitions", style="cyan")
        table.add_column("Latest Offset", style="green")
        
        kafka_info = self.service_manager.check_kafka()
        if kafka_info['topics']:
            for topic, details in kafka_info['topics'].items():
                table.add_row(
                    topic,
                    str(details['partitions']),
                    f"{details['latest_offset']:,}"
                )
        else:
            table.add_row("No topics", "0", "0")
        
        return table
    
    def create_dashboard_layout(self) -> Layout:
        """Create the complete dashboard layout."""
        layout = Layout()
        
        # Header
        header_text = Text("Market Data System TUI Monitor", style="bold white on blue", justify="center")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_panel = Panel(
            Align.center(header_text),
            subtitle=f"Last Update: {timestamp}",
            border_style="blue"
        )
        
        # Footer with commands
        footer_text = "[bold cyan]Commands:[/bold cyan] [white]monitor[/white] | [white]record[/white] | [white]stop[/white] | [white]test[/white] | [white]lag[/white] | [white]quit[/white]"
        footer_panel = Panel(footer_text, border_style="dim")
        
        layout.split_column(
            Layout(header_panel, size=4),
            Layout(name="main"),
            Layout(footer_panel, size=3)
        )
        
        # Main area split
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        # Left side split
        layout["left"].split_column(
            Layout(self.create_service_status_table()),
            Layout(self.create_process_status_table())
        )
        
        # Right side split
        layout["right"].split_column(
            Layout(self.create_lag_statistics_table()),
            Layout(self.create_kafka_topics_table())
        )
        
        return layout


# CLI Commands
@click.group()
@click.pass_context
def cli(ctx):
    """Market Data System TUI Monitor - Rich + Click Interface"""
    ctx.ensure_object(dict)
    ctx.obj['monitor'] = TUIMonitor()


@cli.command()
@click.option('--refresh', default=3, help='Refresh interval in seconds')
@click.option('--duration', default=0, help='Run for specific duration (0 = infinite)')
@click.pass_context
def monitor(ctx, refresh, duration):
    """Start live monitoring dashboard."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    console.print(f"[bold cyan]Starting TUI Monitor[/bold cyan] (refresh: {refresh}s)")
    if duration > 0:
        console.print(f"Running for {duration} seconds...")
    console.print("Press [bold red]Ctrl+C[/bold red] to exit\n")
    
    start_time = time.time()
    
    try:
        with Live(monitor.create_dashboard_layout(), refresh_per_second=1/refresh, screen=True) as live:
            while True:
                if duration > 0 and (time.time() - start_time) > duration:
                    break
                time.sleep(refresh)
                live.update(monitor.create_dashboard_layout())
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped by user.[/yellow]")


@cli.command('test')
@click.pass_context
def test_services(ctx):
    """Test all service connections."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    console.print("[bold]Testing Service Connections[/bold]\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        
        # Test Redis
        task = progress.add_task("Testing Redis...", total=None)
        redis_info = monitor.service_manager.check_redis()
        progress.update(task, description=f"Redis: {redis_info['status']}")
        progress.remove_task(task)
        
        # Test ClickHouse
        task = progress.add_task("Testing ClickHouse...", total=None)
        ch_info = monitor.service_manager.check_clickhouse()
        progress.update(task, description=f"ClickHouse: {ch_info['status']}")
        progress.remove_task(task)
        
        # Test Kafka
        task = progress.add_task("Testing Kafka...", total=None)
        kafka_info = monitor.service_manager.check_kafka()
        progress.update(task, description=f"Kafka: {kafka_info['status']}")
        progress.remove_task(task)
        
        # Test IQFeed
        task = progress.add_task("Testing IQFeed...", total=None)
        iqfeed_info = monitor.service_manager.check_iqfeed()
        progress.update(task, description=f"IQFeed: {iqfeed_info['status']}")
        progress.remove_task(task)
    
    # Results table
    table = Table(title="Service Test Results", show_header=True)
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")
    
    services = [
        ("Redis", redis_info),
        ("ClickHouse", ch_info),
        ("Kafka", kafka_info),
        ("IQFeed", iqfeed_info)
    ]
    
    all_up = True
    for name, info in services:
        status = info.get('status', 'UNKNOWN')
        if status in ['UP']:
            status_text = Text(status, style="green")
        elif status in ['STARTING']:
            status_text = Text(status, style="yellow")
        else:
            status_text = Text(status, style="red")
            all_up = False
        
        # Format details
        if name == "Redis" and info['status'] == 'UP':
            details = f"Port: {info['port']}, Keys: {info['keys']}"
        elif name == "ClickHouse" and info['status'] == 'UP':
            details = f"Total rows: {info['total_rows']:,}"
        elif name == "Kafka" and info['status'] == 'UP':
            details = f"Topics: {info['total_topics']}"
        elif name == "IQFeed":
            details = f"Health: {info['health']}, Ports: {info['ports_open']}"
        else:
            details = "Not available"
        
        table.add_row(name, status_text, details)
    
    console.print(table)
    
    if all_up:
        console.print("\n[bold green]✓ All critical services operational![/bold green]")
        return 0
    else:
        console.print("\n[bold yellow]⚠ Some services need attention[/bold yellow]")
        return 1


@cli.command()
@click.option('--symbols', default='495', help='Number of symbols or specific symbols (comma-separated)')
@click.option('--verify', is_flag=True, help='Enable data verification')
@click.pass_context
def record(ctx, symbols, verify):
    """Start recording market data."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    # Check if already running
    processes = monitor.service_manager.check_recording_processes()
    if processes['recording']:
        console.print(f"[yellow]Recording already running (PID: {processes['recording']['pid']})[/yellow]")
        if not Confirm.ask("Stop current recording and start new one?"):
            return
        
        # Stop current recording
        try:
            psutil.Process(processes['recording']['pid']).terminate()
            console.print("[green]Stopped previous recording[/green]")
            time.sleep(2)
        except:
            console.print("[red]Failed to stop previous recording[/red]")
            return
    
    console.print(f"[cyan]Starting recording for {symbols} symbols...[/cyan]")
    
    # Build command
    cmd = ['python', 'start_495_stock_recording.py']
    if verify:
        cmd.append('--verify')
    
    try:
        process = subprocess.Popen(cmd, cwd=Path.cwd())
        console.print(f"[green]✓ Recording started successfully (PID: {process.pid})[/green]")
        console.print("Use [bold]tui_monitor.py status[/bold] to monitor progress")
    except Exception as e:
        console.print(f"[red]✗ Failed to start recording: {e}[/red]")


@cli.command()
@click.option('--force', is_flag=True, help='Force stop without confirmation')
@click.pass_context
def stop(ctx, force):
    """Stop recording and simulation processes."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    processes = monitor.service_manager.check_recording_processes()
    
    if processes['total'] == 0:
        console.print("[yellow]No processes running[/yellow]")
        return
    
    if not force:
        console.print(f"[yellow]Found {processes['total']} running process(es)[/yellow]")
        if not Confirm.ask("Stop all processes?"):
            return
    
    stopped = 0
    
    # Stop recording
    if processes['recording']:
        try:
            psutil.Process(processes['recording']['pid']).terminate()
            console.print(f"[green]✓ Stopped recording (PID: {processes['recording']['pid']})[/green]")
            stopped += 1
        except Exception as e:
            console.print(f"[red]✗ Failed to stop recording: {e}[/red]")
    
    # Stop simulations
    for sim in processes['simulation']:
        try:
            psutil.Process(sim['pid']).terminate()
            console.print(f"[green]✓ Stopped {sim['type']} simulation (PID: {sim['pid']})[/green]")
            stopped += 1
        except Exception as e:
            console.print(f"[red]✗ Failed to stop simulation: {e}[/red]")
    
    console.print(f"[cyan]Stopped {stopped} process(es)[/cyan]")


@cli.command()
@click.option('--type', 'sim_type', default='synthetic', type=click.Choice(['synthetic', 'replay']), help='Simulation type')
@click.option('--symbols', default='AAPL,TSLA,MSFT,NVDA,GOOGL', help='Symbols for synthetic data')
@click.option('--rate', default=50, help='Messages per second')
@click.option('--date', help='Date for replay (YYYY-MM-DD)')
@click.pass_context
def simulate(ctx, sim_type, symbols, rate, date):
    """Start data simulation."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    console.print(f"[cyan]Starting {sim_type} simulation...[/cyan]")
    
    if sim_type == 'synthetic':
        cmd = [
            'python', 'simple_synthetic_test.py',
            '--symbols', symbols,
            '--rate', str(rate),
            '--topic', 'simulation'
        ]
    else:  # replay
        if not date:
            date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        cmd = [
            'python', 'production_replay_example.py',
            '--date', date,
            '--topic', 'simulation'
        ]
    
    try:
        process = subprocess.Popen(cmd, cwd=Path.cwd())
        console.print(f"[green]✓ {sim_type.title()} simulation started (PID: {process.pid})[/green]")
        if sim_type == 'synthetic':
            console.print(f"Symbols: {symbols}, Rate: {rate} msg/s")
        else:
            console.print(f"Replaying data from: {date}")
    except Exception as e:
        console.print(f"[red]✗ Failed to start simulation: {e}[/red]")


@cli.command()
@click.option('--minutes', default=15, help='Minutes of lag data to show')
@click.pass_context
def lag(ctx, minutes):
    """Show detailed lag statistics."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    console.print(f"[bold]Lag Statistics (Last {minutes} minutes)[/bold]\n")
    
    lag_stats = monitor.service_manager.get_lag_statistics()
    
    if not lag_stats:
        console.print("[yellow]No lag data available[/yellow]")
        return
    
    # Statistics table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Time", style="dim")
    table.add_column("Network (ms)", style="blue")
    table.add_column("Processing (ms)", style="green")
    table.add_column("Total (ms)", style="yellow")
    table.add_column("Max (ms)", style="red")
    table.add_column("Messages", style="cyan")
    
    for stat in lag_stats:
        table.add_row(
            stat['time'],
            f"{stat['network']:.2f}",
            f"{stat['processing']:.2f}",
            f"{stat['total']:.2f}",
            f"{stat['max']:.2f}",
            f"{stat['messages']:,}"
        )
    
    console.print(table)
    
    # Summary statistics
    if lag_stats:
        avg_total = sum(s['total'] for s in lag_stats) / len(lag_stats)
        max_total = max(s['max'] for s in lag_stats)
        total_messages = sum(s['messages'] for s in lag_stats)
        
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"Average Total Lag: [yellow]{avg_total:.2f}ms[/yellow]")
        console.print(f"Maximum Lag Spike: [red]{max_total:.2f}ms[/red]")
        console.print(f"Total Messages: [cyan]{total_messages:,}[/cyan]")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current system status (one-time check)."""
    monitor = ctx.obj['monitor']
    console = monitor.console
    
    # Show all tables once
    console.print(monitor.create_service_status_table())
    console.print()
    console.print(monitor.create_process_status_table())
    console.print()
    console.print(monitor.create_kafka_topics_table())


if __name__ == '__main__':
    cli()