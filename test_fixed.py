#!/usr/bin/env python3
"""
Fixed, simple tests that avoid Rich+Click issues
Focus on testing core functionality without UI output issues
"""
import unittest
import subprocess
import sys
from unittest.mock import patch, MagicMock
from monitor import get_status


class TestCoreFunctionality(unittest.TestCase):
    """Test core monitor functionality without Click issues."""
    
    def test_get_status_returns_dict(self):
        """Test get_status returns proper structure."""
        status = get_status()
        self.assertIsInstance(status, dict)
        self.assertIn('redis', status)
        self.assertIn('clickhouse', status)
        self.assertIn('kafka', status)
        self.assertIn('recording', status)
    
    def test_status_values_are_valid(self):
        """Test status values are in expected format."""
        status = get_status()
        for service, state in status.items():
            # Should be UP, DOWN, or UP (PID: xxx)
            self.assertTrue(
                state in ['UP', 'DOWN'] or state.startswith('UP (PID:'),
                f"Invalid status for {service}: {state}"
            )
    
    def test_redis_connection_logic(self):
        """Test Redis connection detection logic."""
        with patch('redis.Redis') as mock_redis:
            # Test successful connection
            mock_instance = MagicMock()
            mock_instance.ping.return_value = True
            mock_redis.return_value = mock_instance
            
            status = get_status()
            self.assertEqual(status['redis'], 'UP')
            
            # Test failed connection
            mock_redis.side_effect = Exception("Connection failed")
            status = get_status()
            self.assertEqual(status['redis'], 'DOWN')
    
    def test_process_detection_logic(self):
        """Test process detection works correctly."""
        with patch('psutil.process_iter') as mock_iter:
            # Test no recording process
            mock_iter.return_value = []
            status = get_status()
            self.assertEqual(status['recording'], 'DOWN')
            
            # Test with recording process
            mock_proc = MagicMock()
            mock_proc.info = {
                'pid': 12345,
                'cmdline': ['python', 'start_495_stock_recording.py']
            }
            mock_iter.return_value = [mock_proc]
            
            status = get_status()
            self.assertEqual(status['recording'], 'UP (PID: 12345)')
    
    def test_error_handling_resilience(self):
        """Test error handling doesn't crash the system."""
        # Test psutil failure
        with patch('psutil.process_iter', side_effect=Exception("psutil failed")):
            status = get_status()
            self.assertEqual(status['recording'], 'DOWN')
        
        # Test Redis failure
        with patch('redis.Redis', side_effect=ImportError("redis not available")):
            status = get_status()
            self.assertEqual(status['redis'], 'DOWN')


class TestCLIDirectly(unittest.TestCase):
    """Test CLI by calling subprocess directly."""
    
    def test_monitor_test_command(self):
        """Test monitor.py test command directly."""
        result = subprocess.run(
            [sys.executable, 'monitor.py', 'test'],
            capture_output=True, text=True, timeout=10
        )
        # Should return 0 (all up) or 1 (some down) - both are valid
        self.assertIn(result.returncode, [0, 1])
    
    def test_monitor_status_command(self):
        """Test monitor.py status command directly."""
        result = subprocess.run(
            [sys.executable, 'monitor.py', 'status'],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        # Should contain status information
        self.assertIn('System Status', result.stdout)
    
    def test_monitor_help_commands(self):
        """Test help commands work."""
        commands = ['status', 'watch', 'start', 'stop', 'test']
        
        for cmd in commands:
            result = subprocess.run(
                [sys.executable, 'monitor.py', cmd, '--help'],
                capture_output=True, text=True, timeout=5
            )
            self.assertEqual(result.returncode, 0, f"Help for {cmd} failed")
            self.assertIn('Usage:', result.stdout)


class TestServiceIntegration(unittest.TestCase):
    """Test service integration if available."""
    
    def test_service_connectivity(self):
        """Test actual service connectivity."""
        status = get_status()
        
        # Test Redis connectivity if it's UP
        if status['redis'] == 'UP':
            try:
                import redis
                r = redis.Redis(host='localhost', port=6380, socket_connect_timeout=1)
                self.assertTrue(r.ping())
            except ImportError:
                self.skipTest("Redis module not available")
        
        # Test ClickHouse connectivity if it's UP  
        if status['clickhouse'] == 'UP':
            try:
                import clickhouse_connect
                ch = clickhouse_connect.get_client(
                    host='localhost', port=8123,
                    database='l2_market_data',
                    username='l2_user', password='l2_secure_pass'
                )
                result = ch.query("SELECT 1")
                self.assertEqual(result.result_rows[0][0], 1)
            except ImportError:
                self.skipTest("ClickHouse client not available")


if __name__ == '__main__':
    unittest.main(verbosity=2)