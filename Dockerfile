# Multi-stage Dockerfile for Market Data System
# Stage 1: Base system with dependencies
FROM python:3.11-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    wget \
    git \
    docker.io \
    docker-compose \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd for web-based terminal access
RUN wget -O /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/download/1.7.3/ttyd.x86_64 && \
    chmod +x /usr/local/bin/ttyd

WORKDIR /app

# Stage 2: Python dependencies
FROM base as deps

# Copy requirements first for better caching
COPY requirements-minimal.txt .
RUN pip install --no-cache-dir -r requirements-minimal.txt

# Stage 3: Application
FROM deps as app

# Copy application code
COPY monitor.py .
COPY test_monitor.py .
COPY test_monitor_comprehensive.py .
COPY test_system_integration.py .
COPY start_495_stock_recording.py .
COPY production_replay_example.py .
COPY simple_synthetic_test.py .

# Copy essential modules
COPY ingestion/ ./ingestion/
COPY processing/ ./processing/
COPY storage/ ./storage/
COPY tests/ ./tests/
COPY config/ ./config/

# Copy infrastructure setup
COPY infrastructure/ ./infrastructure/
COPY iqfeed-docker/ ./iqfeed-docker/

# Copy Django dashboard (optional)
COPY simple_dashboard/ ./simple_dashboard/

# Create web TUI wrapper
COPY <<EOF web_tui.py
#!/usr/bin/env python3
"""
Web-accessible TUI using Flask + SocketIO
"""
import subprocess
import threading
import time
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import click
from monitor import get_status, make_table
from rich.console import Console

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# HTML template for web TUI
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Market Data TUI</title>
    <style>
        body { font-family: 'Courier New', monospace; background: #000; color: #00ff00; margin: 0; padding: 20px; }
        #output { white-space: pre-wrap; overflow-y: auto; height: 80vh; border: 1px solid #333; padding: 10px; }
        .controls { margin: 10px 0; }
        button { margin: 5px; padding: 8px 16px; background: #333; color: #00ff00; border: 1px solid #666; cursor: pointer; }
        button:hover { background: #555; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
</head>
<body>
    <h1>🖥️ Market Data System TUI</h1>
    <div class="controls">
        <button onclick="sendCommand('status')">Status</button>
        <button onclick="sendCommand('test')">Test Services</button>
        <button onclick="sendCommand('start')">Start Recording</button>
        <button onclick="sendCommand('stop')">Stop Recording</button>
        <button onclick="toggleWatch()">Toggle Live Monitor</button>
    </div>
    <div id="output"></div>
    
    <script>
        const socket = io();
        let watching = false;
        
        socket.on('output', function(data) {
            document.getElementById('output').innerHTML = data.content;
            document.getElementById('output').scrollTop = document.getElementById('output').scrollHeight;
        });
        
        function sendCommand(cmd) {
            socket.emit('command', {command: cmd});
        }
        
        function toggleWatch() {
            watching = !watching;
            socket.emit('watch', {enabled: watching});
        }
        
        // Initial status
        sendCommand('status');
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('command')
def handle_command(data):
    cmd = data['command']
    
    try:
        if cmd == 'status':
            console = Console()
            with console.capture() as capture:
                console.print(make_table())
            output = capture.get()
        elif cmd == 'test':
            result = subprocess.run(['python', 'monitor.py', 'test'], 
                                  capture_output=True, text=True, timeout=10)
            output = result.stdout + result.stderr
        elif cmd == 'start':
            result = subprocess.run(['python', 'monitor.py', 'start'], 
                                  capture_output=True, text=True, timeout=5)
            output = result.stdout + result.stderr
        elif cmd == 'stop':
            result = subprocess.run(['python', 'monitor.py', 'stop'], 
                                  capture_output=True, text=True, timeout=5)
            output = result.stdout + result.stderr
        else:
            output = f"Unknown command: {cmd}"
    except Exception as e:
        output = f"Error executing {cmd}: {str(e)}"
    
    emit('output', {'content': output})

@socketio.on('watch')
def handle_watch(data):
    global watch_thread
    if data['enabled']:
        watch_thread = threading.Thread(target=live_monitor)
        watch_thread.daemon = True
        watch_thread.start()
    
def live_monitor():
    while True:
        try:
            console = Console()
            with console.capture() as capture:
                console.print(make_table())
            output = capture.get()
            socketio.emit('output', {'content': output})
            time.sleep(5)
        except:
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=False)
EOF

# Make scripts executable
RUN chmod +x monitor.py web_tui.py

# Create startup script
COPY <<EOF start.sh
#!/bin/bash
echo "🚀 Starting Market Data System"

# Start infrastructure services in background
cd infrastructure
docker-compose up -d
cd ..

# Wait for services to be ready
echo "⏳ Waiting for services..."
sleep 10

# Start TUI options
echo "🖥️ Starting TUI interfaces..."
echo "Available interfaces:"
echo "  - CLI: python monitor.py status"
echo "  - Web TUI: http://localhost:8080"
echo "  - Terminal TUI: ttyd -p 8081 python monitor.py watch"

# Start web TUI by default
python web_tui.py
EOF

RUN chmod +x start.sh

# Expose ports
EXPOSE 8080 8081 6380 8123 9092

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python monitor.py test || exit 1

# Default command
CMD ["./start.sh"]