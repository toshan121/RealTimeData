#!/usr/bin/env python3
"""
Simple tests for simple monitor - no over-engineering!
"""
import unittest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from monitor import cli, get_status


class TestSimpleMonitor(unittest.TestCase):
    """Test the simple monitor."""
    
    def setUp(self):
        self.runner = CliRunner()
    
    def test_status_command(self):
        """Test status command works."""
        # Test the underlying function instead of CLI output
        from monitor import make_table
        table = make_table()
        self.assertIsNotNone(table)
        
        # Test CLI exit code only (Rich output causes issues in testing)
        result = self.runner.invoke(cli, ['status'])
        self.assertEqual(result.exit_code, 0)
    
    def test_start_command(self):
        """Test start command."""
        with patch('subprocess.Popen') as mock_popen:
            result = self.runner.invoke(cli, ['start'])
            self.assertEqual(result.exit_code, 0)
            self.assertIn('started', result.output)
            mock_popen.assert_called_once()
    
    def test_stop_command(self):
        """Test stop command."""
        with patch('psutil.process_iter') as mock_iter:
            # Mock a running process
            mock_proc = MagicMock()
            mock_proc.info = {'pid': 123, 'cmdline': ['python', 'start_495_stock_recording.py']}
            mock_iter.return_value = [mock_proc]
            
            result = self.runner.invoke(cli, ['stop'])
            self.assertEqual(result.exit_code, 0)
            mock_proc.terminate.assert_called_once()
    
    def test_get_status_function(self):
        """Test get_status returns dict."""
        status = get_status()
        self.assertIsInstance(status, dict)
        self.assertIn('redis', status)
        self.assertIn('clickhouse', status)
        self.assertIn('kafka', status)
        self.assertIn('recording', status)
    
    def test_test_command_all_up(self):
        """Test when all services are up."""
        with patch('monitor.get_status') as mock_status:
            mock_status.return_value = {
                'redis': 'UP',
                'clickhouse': 'UP', 
                'kafka': 'UP',
                'recording': 'UP (PID: 123)'
            }
            
            result = self.runner.invoke(cli, ['test'])
            self.assertEqual(result.exit_code, 0)
            self.assertIn('All services OK', result.output)
    
    def test_test_command_some_down(self):
        """Test when some services are down."""
        with patch('monitor.get_status') as mock_status:
            mock_status.return_value = {
                'redis': 'DOWN',
                'clickhouse': 'UP',
                'kafka': 'DOWN', 
                'recording': 'DOWN'
            }
            
            result = self.runner.invoke(cli, ['test'])
            self.assertEqual(result.exit_code, 1)
            self.assertIn('Some services down', result.output)


if __name__ == '__main__':
    unittest.main()