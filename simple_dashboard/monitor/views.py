"""
Simple monitoring views - no over-engineering!
"""
import json
import subprocess
import psutil
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

import redis
import clickhouse_connect
from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, ConfigResource, ConfigResourceType


def get_system_status():
    """Get simple system status."""
    try:
        # Redis check
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
        redis_ok = r.ping()
        redis_info = r.info() if redis_ok else {}
    except:
        redis_ok = False
        redis_info = {}
    
    try:
        # ClickHouse check
        ch = clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            database=settings.CLICKHOUSE_DATABASE,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD
        )
        ch_ok = True
        
        # Get record counts
        tables = {}
        for table in ['trades', 'quotes', 'order_book_updates']:
            result = ch.query(f'SELECT COUNT(*) FROM {table}')
            tables[table] = result.result_rows[0][0] if result.result_rows else 0
    except:
        ch_ok = False
        tables = {}
    
    try:
        # Kafka check
        admin = KafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        topics = admin.list_topics()
        kafka_ok = True
    except:
        kafka_ok = False
        topics = []
    
    # Check if recording process is running
    recording_pid = None
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'start_495_stock_recording.py' in ' '.join(proc.info['cmdline'] or []):
                recording_pid = proc.info['pid']
                break
        except:
            pass
    
    return {
        'redis': {'status': redis_ok, 'info': redis_info},
        'clickhouse': {'status': ch_ok, 'tables': tables},
        'kafka': {'status': kafka_ok, 'topics': topics},
        'recording': {'running': recording_pid is not None, 'pid': recording_pid},
        'timestamp': datetime.now().isoformat()
    }


def dashboard(request):
    """Simple dashboard view."""
    status = get_system_status()
    return render(request, 'monitor/dashboard.html', {'status': status})


@csrf_exempt
def api_status(request):
    """API endpoint for status updates."""
    return JsonResponse(get_system_status())


@csrf_exempt
def api_recording(request):
    """Control recording process."""
    if request.method == 'POST':
        action = json.loads(request.body).get('action')
        
        if action == 'start':
            # Start recording in background
            subprocess.Popen([
                'python', '../start_495_stock_recording.py'
            ], cwd=settings.BASE_DIR.parent)
            return JsonResponse({'status': 'started'})
            
        elif action == 'stop':
            # Stop recording process
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'start_495_stock_recording.py' in ' '.join(proc.info['cmdline'] or []):
                        proc.terminate()
                        return JsonResponse({'status': 'stopped'})
                except:
                    pass
            return JsonResponse({'status': 'not_running'})
    
    return JsonResponse({'error': 'Invalid request'})


@csrf_exempt
def api_simulation(request):
    """Control simulation streams."""
    if request.method == 'POST':
        data = json.loads(request.body)
        action = data.get('action')
        sim_type = data.get('type', 'synthetic')  # synthetic, replay, or generated
        
        if action == 'start':
            if sim_type == 'synthetic':
                subprocess.Popen([
                    'python', '../simple_synthetic_test.py',
                    '--symbols', 'AAPL,TSLA,MSFT,NVDA,GOOGL',
                    '--rate', '50',
                    '--topic', 'simulation'
                ], cwd=settings.BASE_DIR.parent)
            elif sim_type == 'replay':
                subprocess.Popen([
                    'python', '../production_replay_example.py',
                    '--date', '2025-07-29',
                    '--topic', 'simulation'
                ], cwd=settings.BASE_DIR.parent)
            
            return JsonResponse({'status': 'started', 'type': sim_type})
            
        elif action == 'stop':
            # Stop simulation processes
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if 'simple_synthetic_test.py' in cmdline or 'production_replay_example.py' in cmdline:
                        proc.terminate()
                except:
                    pass
            return JsonResponse({'status': 'stopped'})
    
    return JsonResponse({'error': 'Invalid request'})


def api_kafka_check(request):
    """Check Kafka topics and lag."""
    try:
        consumer = KafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id='dashboard-check',
            auto_offset_reset='latest'
        )
        
        topics_info = {}
        for topic in ['trades', 'quotes', 'l2_order_book', 'simulation']:
            partitions = consumer.partitions_for_topic(topic) or []
            
            if partitions:
                # Get latest offset
                consumer.assign([])
                for partition in partitions:
                    consumer.seek_to_end([(topic, partition)])
                    offset = consumer.position((topic, partition))
                    topics_info[topic] = {
                        'partitions': len(partitions),
                        'latest_offset': offset
                    }
        
        consumer.close()
        return JsonResponse({'status': 'ok', 'topics': topics_info})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})


def api_lag_stats(request):
    """Get lag statistics from ClickHouse."""
    try:
        ch = clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            database=settings.CLICKHOUSE_DATABASE,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD
        )
        
        # Get recent lag statistics
        query = """
        SELECT 
            toStartOfMinute(timestamp) as minute,
            avg(network_lag_ms) as avg_network_lag,
            avg(processing_lag_ms) as avg_processing_lag,
            avg(total_lag_ms) as avg_total_lag,
            max(total_lag_ms) as max_total_lag,
            count() as message_count
        FROM (
            SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms FROM trades
            WHERE timestamp > now() - INTERVAL 30 MINUTE
            UNION ALL
            SELECT timestamp, network_lag_ms, processing_lag_ms, total_lag_ms FROM quotes
            WHERE timestamp > now() - INTERVAL 30 MINUTE
        )
        GROUP BY minute
        ORDER BY minute DESC
        LIMIT 30
        """
        
        result = ch.query(query)
        
        lag_data = []
        for row in result.result_rows:
            lag_data.append({
                'time': row[0].isoformat(),
                'network_lag': round(row[1], 2) if row[1] else 0,
                'processing_lag': round(row[2], 2) if row[2] else 0,
                'total_lag': round(row[3], 2) if row[3] else 0,
                'max_lag': round(row[4], 2) if row[4] else 0,
                'messages': row[5]
            })
        
        # Reverse to have chronological order
        lag_data.reverse()
        
        return JsonResponse({'status': 'ok', 'data': lag_data})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})