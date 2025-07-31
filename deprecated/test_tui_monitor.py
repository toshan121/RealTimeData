#!/usr/bin/env python3
"""
Test suite for TUI monitor - much simpler than Django tests!
"""
import unittest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from simple_tui_monitor import SystemMonitor, cli


class TestTUIMonitor(unittest.TestCase):
    """Test TUI monitor functionality."""
    
    def setUp(self):
        self.monitor = SystemMonitor()
        self.runner = CliRunner()
    
    def test_redis_check_success(self):
        """Test Redis check when connected."""
        with patch('redis.Redis') as mock_redis:
            mock_instance = MagicMock()
            mock_instance.ping.return_value = True
            mock_instance.info.return_value = {
                'db0': {'keys': '42'},
                'used_memory_human': '1.2M'
            }
            mock_redis.return_value = mock_instance
            
            result = self.monitor.check_redis()
            self.assertEqual(result['status'], 'UP')
            self.assertEqual(result['keys'], '42')
            self.assertEqual(result['memory'], '1.2M')
    
    def test_redis_check_failure(self):
        """Test Redis check when disconnected."""
        with patch('redis.Redis') as mock_redis:
            mock_redis.side_effect = Exception("Connection failed")
            
            result = self.monitor.check_redis()
            self.assertEqual(result['status'], 'DOWN')
            self.assertEqual(result['keys'], 0)
    
    def test_clickhouse_check_success(self):
        """Test ClickHouse check when connected."""
        with patch('clickhouse_connect.get_client') as mock_ch:
            mock_client = MagicMock()
            mock_client.query.side_effect = [
                MagicMock(result_rows=[[1000]]),  # trades
                MagicMock(result_rows=[[2000]]),  # quotes
                MagicMock(result_rows=[[500]])    # order_book_updates
            ]
            mock_ch.return_value = mock_client
            
            result = self.monitor.check_clickhouse()
            self.assertEqual(result['status'], 'UP')
            self.assertEqual(result['tables']['trades'], 1000)
            self.assertEqual(result['tables']['quotes'], 2000)
    
    def test_kafka_check(self):
        """Test Kafka check."""
        with patch('kafka.KafkaConsumer') as mock_consumer:
            mock_instance = MagicMock()
            mock_instance.topics.return_value = {'trades', 'quotes', 'l2_order_book'}
            mock_consumer.return_value = mock_instance
            
            result = self.monitor.check_kafka()
            self.assertEqual(result['status'], 'UP')
            self.assertEqual(result['topics'], 3)
    
    def test_recording_process_check(self):
        """Test recording process detection."""
        with patch('psutil.process_iter') as mock_iter:
            mock_proc = MagicMock()
            mock_proc.info = {
                'pid': 12345,
                'name': 'python',
                'cmdline': ['python', 'start_495_stock_recording.py']
            }
            mock_iter.return_value = [mock_proc]
            
            result = self.monitor.check_recording_process()
            self.assertEqual(result['status'], 'RUNNING')
            self.assertEqual(result['pid'], 12345)
    
    def test_cli_test_services_command(self):
        """Test the test-services CLI command."""
        with patch.object(SystemMonitor, 'check_redis') as mock_redis, \
             patch.object(SystemMonitor, 'check_clickhouse') as mock_ch, \
             patch.object(SystemMonitor, 'check_kafka') as mock_kafka, \
             patch.object(SystemMonitor, 'check_recording_process') as mock_rec:
            
            mock_redis.return_value = {'status': 'UP'}
            mock_ch.return_value = {'status': 'UP'}
            mock_kafka.return_value = {'status': 'UP'}
            mock_rec.return_value = {'status': 'STOPPED'}
            
            result = self.runner.invoke(cli, ['test-services'])
            self.assertEqual(result.exit_code, 1)  # Not all services up
            self.assertIn('Redis: UP', result.output)
            self.assertIn('Some services need attention', result.output)
    
    def test_cli_start_recording(self):
        """Test start-recording command."""
        with patch('subprocess.Popen') as mock_popen:
            result = self.runner.invoke(cli, ['start-recording'])
            self.assertEqual(result.exit_code, 0)
            self.assertIn('Recording started successfully', result.output)
            mock_popen.assert_called_once()
    
    def test_cli_stop_recording(self):
        """Test stop-recording command."""
        with patch('psutil.process_iter') as mock_iter:
            mock_proc = MagicMock()
            mock_proc.info = {
                'pid': 12345,
                'cmdline': ['python', 'start_495_stock_recording.py']
            }
            mock_proc.terminate.return_value = None
            mock_iter.return_value = [mock_proc]
            
            result = self.runner.invoke(cli, ['stop-recording'])
            self.assertEqual(result.exit_code, 0)
            self.assertIn('Stopped process PID: 12345', result.output)
    
    def test_status_table_creation(self):
        """Test status table generation."""
        with patch.object(SystemMonitor, 'check_redis') as mock_redis, \
             patch.object(SystemMonitor, 'check_clickhouse') as mock_ch, \
             patch.object(SystemMonitor, 'check_kafka') as mock_kafka, \
             patch.object(SystemMonitor, 'check_recording_process') as mock_rec:
            
            mock_redis.return_value = {'status': 'UP', 'keys': 10, 'memory': '1M'}
            mock_ch.return_value = {
                'status': 'UP', 
                'tables': {'trades': 100, 'quotes': 200, 'order_book_updates': 50}
            }
            mock_kafka.return_value = {'status': 'UP', 'topics': 3}
            mock_rec.return_value = {'status': 'RUNNING', 'pid': 12345}
            
            table = self.monitor.create_status_table()
            self.assertIsNotNone(table)
            # Table should have 4 rows (services)
            self.assertEqual(len(table.rows), 4)
    
    def test_lag_stats_retrieval(self):
        """Test lag statistics retrieval."""
        with patch('clickhouse_connect.get_client') as mock_ch:
            mock_client = MagicMock()
            mock_client.query.return_value = MagicMock(result_rows=[
                ['2025-07-31 10:00:00', 10.5, 5.2, 15.7, 25.3],
                ['2025-07-31 10:01:00', 11.2, 4.8, 16.0, 22.1],
            ])
            mock_ch.return_value = mock_client
            
            stats = self.monitor.get_lag_stats()
            self.assertEqual(len(stats), 2)
            self.assertEqual(stats[0]['network'], 10.5)
            self.assertEqual(stats[0]['total'], 15.7)


class TestTUIIntegration(unittest.TestCase):
    """Integration tests for TUI."""
    
    def test_full_dashboard_creation(self):
        """Test complete dashboard creation."""
        monitor = SystemMonitor()
        
        with patch.object(monitor, 'check_redis') as mock_redis, \
             patch.object(monitor, 'check_clickhouse') as mock_ch, \
             patch.object(monitor, 'check_kafka') as mock_kafka, \
             patch.object(monitor, 'check_recording_process') as mock_rec, \
             patch.object(monitor, 'get_lag_stats') as mock_lag:
            
            # Mock all services as UP
            mock_redis.return_value = {'status': 'UP', 'keys': 10, 'memory': '1M'}
            mock_ch.return_value = {'status': 'UP', 'tables': {}}
            mock_kafka.return_value = {'status': 'UP', 'topics': 3}
            mock_rec.return_value = {'status': 'RUNNING', 'pid': 12345}
            mock_lag.return_value = []
            
            # Should not raise any exceptions
            layout = monitor.create_dashboard()
            self.assertIsNotNone(layout)


if __name__ == '__main__':
    unittest.main()