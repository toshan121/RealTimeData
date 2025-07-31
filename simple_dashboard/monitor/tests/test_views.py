"""
Comprehensive tests for dashboard views
"""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse


class DashboardViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    @patch('monitor.views.get_system_status')
    def test_dashboard_view_renders(self, mock_status):
        """Test dashboard page renders successfully."""
        mock_status.return_value = {
            'redis': {'status': True, 'info': {'db0': {'keys': 100}}},
            'clickhouse': {'status': True, 'tables': {'trades': 1000, 'quotes': 2000, 'order_book_updates': 500}},
            'kafka': {'status': True, 'topics': ['trades', 'quotes', 'l2_order_book']},
            'recording': {'running': False, 'pid': None},
            'timestamp': '2025-07-31T10:00:00'
        }
        
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Simple Market Data Dashboard')
        self.assertContains(response, 'System Status')
        self.assertContains(response, 'Recording Control')
        self.assertContains(response, 'Lag Statistics')

    @patch('monitor.views.redis.Redis')
    @patch('monitor.views.clickhouse_connect.get_client')
    @patch('monitor.views.KafkaAdminClient')
    @patch('monitor.views.psutil.process_iter')
    def test_get_system_status_all_services_up(self, mock_psutil, mock_kafka, mock_ch, mock_redis):
        """Test system status when all services are running."""
        # Mock Redis
        redis_instance = MagicMock()
        redis_instance.ping.return_value = True
        redis_instance.info.return_value = {'db0': {'keys': '42'}}
        mock_redis.return_value = redis_instance
        
        # Mock ClickHouse
        ch_instance = MagicMock()
        ch_instance.query.side_effect = [
            MagicMock(result_rows=[[1000]]),  # trades count
            MagicMock(result_rows=[[2000]]),  # quotes count
            MagicMock(result_rows=[[500]])    # order_book_updates count
        ]
        mock_ch.return_value = ch_instance
        
        # Mock Kafka
        kafka_instance = MagicMock()
        kafka_instance.list_topics.return_value = ['trades', 'quotes', 'l2_order_book']
        mock_kafka.return_value = kafka_instance
        
        # Mock recording process
        mock_proc = MagicMock()
        mock_proc.info = {'pid': 12345, 'name': 'python', 'cmdline': ['python', 'start_495_stock_recording.py']}
        mock_psutil.return_value = [mock_proc]
        
        from monitor.views import get_system_status
        status = get_system_status()
        
        self.assertTrue(status['redis']['status'])
        self.assertEqual(status['redis']['info']['db0']['keys'], '42')
        self.assertTrue(status['clickhouse']['status'])
        self.assertEqual(status['clickhouse']['tables']['trades'], 1000)
        self.assertTrue(status['kafka']['status'])
        self.assertEqual(len(status['kafka']['topics']), 3)
        self.assertTrue(status['recording']['running'])
        self.assertEqual(status['recording']['pid'], 12345)

    @patch('monitor.views.redis.Redis')
    @patch('monitor.views.clickhouse_connect.get_client')
    @patch('monitor.views.KafkaAdminClient')
    def test_get_system_status_services_down(self, mock_kafka, mock_ch, mock_redis):
        """Test system status when services are down."""
        # Mock Redis failure
        mock_redis.side_effect = Exception("Connection refused")
        
        # Mock ClickHouse failure
        mock_ch.side_effect = Exception("Connection failed")
        
        # Mock Kafka failure
        mock_kafka.side_effect = Exception("No brokers available")
        
        from monitor.views import get_system_status
        status = get_system_status()
        
        self.assertFalse(status['redis']['status'])
        self.assertFalse(status['clickhouse']['status'])
        self.assertFalse(status['kafka']['status'])
        self.assertFalse(status['recording']['running'])

    def test_api_status_endpoint(self):
        """Test API status endpoint returns JSON."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {'test': 'status'}
            
            response = self.client.get(reverse('api_status'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'test': 'status'})

    @patch('monitor.views.subprocess.Popen')
    def test_api_recording_start(self, mock_popen):
        """Test starting recording process via API."""
        response = self.client.post(
            reverse('api_recording'),
            data=json.dumps({'action': 'start'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'started'})
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        self.assertIn('start_495_stock_recording.py', call_args)

    @patch('monitor.views.psutil.process_iter')
    def test_api_recording_stop(self, mock_psutil):
        """Test stopping recording process via API."""
        # Mock recording process
        mock_proc = MagicMock()
        mock_proc.info = {'pid': 12345, 'name': 'python', 'cmdline': ['python', 'start_495_stock_recording.py']}
        mock_proc.terminate.return_value = None
        mock_psutil.return_value = [mock_proc]
        
        response = self.client.post(
            reverse('api_recording'),
            data=json.dumps({'action': 'stop'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'stopped'})
        mock_proc.terminate.assert_called_once()

    @patch('monitor.views.subprocess.Popen')
    def test_api_simulation_synthetic(self, mock_popen):
        """Test starting synthetic data simulation."""
        response = self.client.post(
            reverse('api_simulation'),
            data=json.dumps({'action': 'start', 'type': 'synthetic'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'started', 'type': 'synthetic'})
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        self.assertIn('simple_synthetic_test.py', call_args)
        self.assertIn('--topic', call_args)
        self.assertIn('simulation', call_args)

    @patch('monitor.views.subprocess.Popen')
    def test_api_simulation_replay(self, mock_popen):
        """Test starting historical replay simulation."""
        response = self.client.post(
            reverse('api_simulation'),
            data=json.dumps({'action': 'start', 'type': 'replay'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'started', 'type': 'replay'})
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        self.assertIn('production_replay_example.py', call_args)

    @patch('monitor.views.KafkaConsumer')
    def test_api_kafka_check_success(self, mock_consumer):
        """Test Kafka check when topics exist."""
        consumer_instance = MagicMock()
        consumer_instance.partitions_for_topic.side_effect = lambda t: {0, 1} if t in ['trades', 'quotes'] else None
        consumer_instance.position.return_value = 1000
        mock_consumer.return_value = consumer_instance
        
        response = self.client.get(reverse('api_kafka_check'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('trades', data['topics'])
        self.assertEqual(data['topics']['trades']['partitions'], 2)

    @patch('monitor.views.KafkaConsumer')
    def test_api_kafka_check_failure(self, mock_consumer):
        """Test Kafka check when connection fails."""
        mock_consumer.side_effect = Exception("Connection failed")
        
        response = self.client.get(reverse('api_kafka_check'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('error', data)

    @patch('monitor.views.clickhouse_connect.get_client')
    def test_api_lag_stats_success(self, mock_ch):
        """Test lag statistics API."""
        ch_instance = MagicMock()
        ch_instance.query.return_value = MagicMock(result_rows=[
            ['2025-07-31 10:00:00', 10.5, 5.2, 15.7, 25.3, 1000],
            ['2025-07-31 10:01:00', 11.2, 4.8, 16.0, 22.1, 1200],
        ])
        mock_ch.return_value = ch_instance
        
        response = self.client.get(reverse('api_lag_stats'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['data']), 2)
        self.assertEqual(data['data'][0]['network_lag'], 10.5)
        self.assertEqual(data['data'][0]['messages'], 1000)

    @patch('monitor.views.clickhouse_connect.get_client')
    def test_api_lag_stats_failure(self, mock_ch):
        """Test lag statistics API when ClickHouse fails."""
        mock_ch.side_effect = Exception("Query failed")
        
        response = self.client.get(reverse('api_lag_stats'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('error', data)

    def test_invalid_api_recording_request(self):
        """Test invalid recording API request."""
        response = self.client.get(reverse('api_recording'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'error': 'Invalid request'})

    def test_invalid_api_simulation_request(self):
        """Test invalid simulation API request."""
        response = self.client.get(reverse('api_simulation'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'error': 'Invalid request'})