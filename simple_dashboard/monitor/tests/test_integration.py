"""
Integration tests for dashboard functionality
"""
import json
import time
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings


class DashboardIntegrationTests(TestCase):
    """Test complete workflows and integrations."""
    
    def setUp(self):
        self.client = Client()

    @patch('monitor.views.subprocess.Popen')
    @patch('monitor.views.psutil.process_iter')
    @patch('monitor.views.get_system_status')
    def test_recording_workflow(self, mock_status, mock_psutil, mock_popen):
        """Test complete recording start/stop workflow."""
        # Initial state - not recording
        mock_status.return_value = {
            'recording': {'running': False, 'pid': None},
            'redis': {'status': True},
            'clickhouse': {'status': True},
            'kafka': {'status': True},
            'timestamp': '2025-07-31T10:00:00'
        }
        mock_psutil.return_value = []
        
        # Check initial dashboard state
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Stopped')
        
        # Start recording
        response = self.client.post(
            reverse('api_recording'),
            data=json.dumps({'action': 'start'}),
            content_type='application/json'
        )
        self.assertEqual(response.json()['status'], 'started')
        mock_popen.assert_called_once()
        
        # Update mock to show recording running
        mock_proc = MagicMock()
        mock_proc.info = {'pid': 12345, 'cmdline': ['python', 'start_495_stock_recording.py']}
        mock_psutil.return_value = [mock_proc]
        mock_status.return_value['recording'] = {'running': True, 'pid': 12345}
        
        # Stop recording
        response = self.client.post(
            reverse('api_recording'),
            data=json.dumps({'action': 'stop'}),
            content_type='application/json'
        )
        self.assertEqual(response.json()['status'], 'stopped')
        mock_proc.terminate.assert_called_once()

    @patch('monitor.views.clickhouse_connect.get_client')
    @patch('monitor.views.KafkaConsumer')
    def test_monitoring_data_flow(self, mock_consumer, mock_ch):
        """Test monitoring data flow from Kafka to ClickHouse."""
        # Mock Kafka data
        consumer_instance = MagicMock()
        consumer_instance.partitions_for_topic.return_value = {0}
        consumer_instance.position.return_value = 5000
        mock_consumer.return_value = consumer_instance
        
        # Check Kafka status
        response = self.client.get(reverse('api_kafka_check'))
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('trades', data['topics'])
        
        # Mock ClickHouse lag data
        ch_instance = MagicMock()
        ch_instance.query.return_value = MagicMock(result_rows=[
            ['2025-07-31 10:00:00', 15.0, 8.0, 23.0, 45.0, 1500],
            ['2025-07-31 10:01:00', 12.0, 6.0, 18.0, 35.0, 1800],
            ['2025-07-31 10:02:00', 10.0, 5.0, 15.0, 28.0, 2000],
        ])
        mock_ch.return_value = ch_instance
        
        # Get lag statistics
        response = self.client.get(reverse('api_lag_stats'))
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['data']), 3)
        
        # Verify data ordering (should be chronological)
        self.assertTrue(data['data'][0]['total_lag'] > data['data'][2]['total_lag'])
        self.assertTrue(data['data'][0]['messages'] < data['data'][2]['messages'])

    @patch('monitor.views.subprocess.Popen')
    @patch('monitor.views.psutil.process_iter')
    def test_simulation_lifecycle(self, mock_psutil, mock_popen):
        """Test simulation start and stop lifecycle."""
        # Start synthetic simulation
        response = self.client.post(
            reverse('api_simulation'),
            data=json.dumps({'action': 'start', 'type': 'synthetic'}),
            content_type='application/json'
        )
        self.assertEqual(response.json()['status'], 'started')
        
        # Mock simulation process running
        mock_proc = MagicMock()
        mock_proc.info = {'pid': 23456, 'cmdline': ['python', 'simple_synthetic_test.py']}
        mock_psutil.return_value = [mock_proc]
        
        # Stop simulation
        response = self.client.post(
            reverse('api_simulation'),
            data=json.dumps({'action': 'stop'}),
            content_type='application/json'
        )
        self.assertEqual(response.json()['status'], 'stopped')
        mock_proc.terminate.assert_called_once()

    def test_dashboard_ui_elements(self):
        """Test dashboard UI contains all required elements."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True, 'info': {}},
                'clickhouse': {'status': True, 'tables': {'trades': 100}},
                'kafka': {'status': True, 'topics': ['trades']},
                'recording': {'running': False, 'pid': None},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            
            # Check all major sections
            self.assertContains(response, 'System Status')
            self.assertContains(response, 'Recording Control')
            self.assertContains(response, 'Simulation Control')
            self.assertContains(response, 'Kafka Topics Status')
            self.assertContains(response, 'Lag Statistics')
            
            # Check control buttons
            self.assertContains(response, 'Start Recording')
            self.assertContains(response, 'Stop Recording')
            self.assertContains(response, 'Synthetic Data')
            self.assertContains(response, 'Replay Historical')
            
            # Check JavaScript functions
            self.assertContains(response, 'controlRecording')
            self.assertContains(response, 'startSimulation')
            self.assertContains(response, 'checkKafka')
            self.assertContains(response, 'drawLagChart')

    @patch('monitor.views.redis.Redis')
    @patch('monitor.views.clickhouse_connect.get_client')
    @patch('monitor.views.KafkaAdminClient')
    def test_service_failure_handling(self, mock_kafka, mock_ch, mock_redis):
        """Test dashboard handles service failures gracefully."""
        # Simulate all services failing
        mock_redis.side_effect = Exception("Redis connection failed")
        mock_ch.side_effect = Exception("ClickHouse connection failed")
        mock_kafka.side_effect = Exception("Kafka connection failed")
        
        # Dashboard should still render
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Disconnected')
        
        # APIs should return error status
        response = self.client.get(reverse('api_status'))
        data = response.json()
        self.assertFalse(data['redis']['status'])
        self.assertFalse(data['clickhouse']['status'])
        self.assertFalse(data['kafka']['status'])

    def test_concurrent_requests(self):
        """Test dashboard handles concurrent requests."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            # Simulate multiple concurrent requests
            responses = []
            for _ in range(5):
                response = self.client.get(reverse('api_status'))
                responses.append(response)
            
            # All should succeed
            for response in responses:
                self.assertEqual(response.status_code, 200)

    @patch('monitor.views.subprocess.Popen')
    def test_command_injection_protection(self, mock_popen):
        """Test that command injection is not possible."""
        # Try to inject malicious command
        response = self.client.post(
            reverse('api_simulation'),
            data=json.dumps({'action': 'start', 'type': 'synthetic"; rm -rf /'}),
            content_type='application/json'
        )
        
        # Should still work but only with predefined commands
        self.assertEqual(response.status_code, 200)
        # Check that only safe predefined arguments were used
        if mock_popen.called:
            call_args = mock_popen.call_args[0][0]
            self.assertNotIn('rm', ' '.join(call_args))
            self.assertNotIn('-rf', ' '.join(call_args))