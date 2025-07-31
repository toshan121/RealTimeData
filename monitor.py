#!/usr/bin/env python3
"""
Simple TUI Monitor - No over-engineering!
Just the essentials with Rich + Click
"""
import time
import subprocess
import psutil

import click
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.text import Text

console = Console()


def check_service(name, test_func):
    """Simple service checker."""
    try:
        return test_func()
    except Exception:
        return f"{name}: DOWN"


def get_status():
    """Get all status info quickly."""
    status = {}

    # Redis
    try:
        import redis
        r = redis.Redis(host='localhost', port=6380, socket_connect_timeout=1)
        r.ping()
        status['redis'] = "UP"
    except Exception:
        status['redis'] = "DOWN"

    # ClickHouse
    try:
        import clickhouse_connect
        ch = clickhouse_connect.get_client(
            host='localhost',
            port=8123,
            database='l2_market_data',
            username='l2_user',
            password='l2_secure_pass',
            connect_timeout=2
        )
        ch.query("SELECT 1")
        status['clickhouse'] = "UP"
    except Exception:
        status['clickhouse'] = "DOWN"

    # Kafka
    try:
        from kafka import KafkaConsumer
        KafkaConsumer(bootstrap_servers='localhost:9092',
                      consumer_timeout_ms=1000)
        status['kafka'] = "UP"
    except Exception:
        status['kafka'] = "DOWN"

    # Recording process
    status['recording'] = "DOWN"
    try:
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if 'start_495_stock_recording.py' in cmdline:
                    status['recording'] = f"UP (PID: {proc.info['pid']})"
                    break
            except Exception:
                pass
    except Exception:
        # Handle case where psutil itself fails
        status['recording'] = "DOWN"

    return status


def make_table():
    """Create simple status table."""
    table = Table(title="System Status")
    table.add_column("Service")
    table.add_column("Status")

    status = get_status()
    for service, state in status.items():
        color = "green" if "UP" in state else "red"
        table.add_row(service.title(), Text(state, style=color))

    return table


@click.group()
def cli():
    """Simple Market Data Monitor"""
    pass


@cli.command()
@click.option('--refresh', default=5, help='Refresh seconds')
def watch(refresh):
    """Live monitoring."""
    console.print("Press Ctrl+C to exit")
    try:
        with Live(make_table(), refresh_per_second=1 / refresh) as live:
            while True:
                time.sleep(refresh)
                live.update(make_table())
    except KeyboardInterrupt:
        console.print("Stopped")


@cli.command()
def status():
    """One-time status check."""
    console.print(make_table())


@cli.command()
def start():
    """Start recording."""
    try:
        subprocess.Popen(['python', 'start_495_stock_recording.py'])
        console.print("[green]Recording started[/green]")
    except Exception as e:
        console.print(f"[red]Failed: {e}[/red]")


@cli.command()
def stop():
    """Stop recording."""
    killed = 0
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'start_495_stock_recording.py' in cmdline:
                proc.terminate()
                console.print(f"[green]Stopped PID {proc.info['pid']}[/green]")
                killed += 1
        except Exception:
            pass

    if killed == 0:
        console.print("[yellow]Nothing to stop[/yellow]")


@cli.command()
def test():
    """Test all services."""
    import sys
    status = get_status()
    all_up = all("UP" in state for state in status.values())

    for service, state in status.items():
        color = "green" if "UP" in state else "red"
        console.print(f"{service}: [{color}]{state}[/{color}]")

    if all_up:
        console.print("[green]All services OK[/green]")
        sys.exit(0)
    else:
        console.print("[red]Some services down[/red]")
        sys.exit(1)


if __name__ == '__main__':
    cli()
