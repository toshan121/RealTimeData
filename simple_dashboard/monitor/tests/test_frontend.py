"""
Tests for frontend JavaScript functionality
"""
from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch


class FrontendTests(TestCase):
    """Test frontend rendering and JavaScript integration."""
    
    def setUp(self):
        self.client = Client()

    def test_canvas_element_present(self):
        """Test lag chart canvas element is present."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            self.assertContains(response, '<canvas id="lag-chart"')
            self.assertContains(response, 'width="1000"')
            self.assertContains(response, 'height="300"')

    def test_javascript_functions_defined(self):
        """Test all required JavaScript functions are defined."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            
            # Check AJAX helper functions
            self.assertContains(response, 'function post(url, data, callback)')
            self.assertContains(response, 'function get(url, callback)')
            
            # Check control functions
            self.assertContains(response, 'function controlRecording(action)')
            self.assertContains(response, 'function startSimulation(type)')
            self.assertContains(response, 'function stopSimulation()')
            self.assertContains(response, 'function checkKafka()')
            
            # Check chart functions
            self.assertContains(response, 'function drawLagChart(data)')
            self.assertContains(response, 'function updateLagChart()')
            
            # Check auto-refresh
            self.assertContains(response, 'function startAutoRefresh()')

    def test_button_states(self):
        """Test button enabled/disabled states based on recording status."""
        # Test when recording is stopped
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False, 'pid': None},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Start button should be enabled, stop button disabled
            self.assertContains(response, 'onclick="controlRecording(\'start\')"')
            self.assertContains(response, 'onclick="controlRecording(\'stop\')" disabled')
        
        # Test when recording is running
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': True, 'pid': 12345},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Start button should be disabled, stop button enabled
            self.assertContains(response, 'onclick="controlRecording(\'start\')" disabled')
            self.assertContains(response, 'onclick="controlRecording(\'stop\')"')

    def test_status_indicators(self):
        """Test status indicators show correct colors."""
        # Test all services up
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True, 'info': {}},
                'clickhouse': {'status': True, 'tables': {}},
                'kafka': {'status': True, 'topics': []},
                'recording': {'running': True, 'pid': 12345},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Should show green status
            self.assertContains(response, 'status-ok')
            self.assertContains(response, '✅ Connected')
            self.assertContains(response, '✅ Running')
        
        # Test services down
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': False, 'info': {}},
                'clickhouse': {'status': False, 'tables': {}},
                'kafka': {'status': False, 'topics': []},
                'recording': {'running': False, 'pid': None},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Should show red status
            self.assertContains(response, 'status-error')
            self.assertContains(response, '❌ Disconnected')
            self.assertContains(response, '⏹️ Stopped')

    def test_auto_refresh_checkbox(self):
        """Test auto-refresh checkbox is present and checked by default."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            self.assertContains(response, '<input type="checkbox" id="auto-refresh" checked>')
            self.assertContains(response, 'Auto-refresh (5s)')

    def test_lag_chart_legend(self):
        """Test lag chart legend is present with correct colors."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Check legend elements
            self.assertContains(response, 'style="color: blue;">— Network Lag</span>')
            self.assertContains(response, 'style="color: green;">— Processing Lag</span>')
            self.assertContains(response, 'style="color: red;">— Total Lag</span>')
            self.assertContains(response, 'style="color: orange;">— Max Lag</span>')

    def test_api_endpoints_in_javascript(self):
        """Test JavaScript contains correct API endpoints."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Check API endpoints
            self.assertContains(response, "'/api/recording/'")
            self.assertContains(response, "'/api/simulation/'")
            self.assertContains(response, "'/api/kafka-check/'")
            self.assertContains(response, "'/api/lag-stats/'")

    def test_error_handling_in_javascript(self):
        """Test JavaScript error handling is present."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Check error handling
            self.assertContains(response, '.catch(err =>')
            self.assertContains(response, 'alert(\'Error:')
            self.assertContains(response, 'console.error(\'Error:')

    def test_responsive_styles(self):
        """Test responsive CSS styles are present."""
        with patch('monitor.views.get_system_status') as mock_status:
            mock_status.return_value = {
                'redis': {'status': True},
                'clickhouse': {'status': True},
                'kafka': {'status': True},
                'recording': {'running': False},
                'timestamp': '2025-07-31T10:00:00'
            }
            
            response = self.client.get(reverse('dashboard'))
            # Check responsive styles
            self.assertContains(response, 'max-width: 1200px')
            self.assertContains(response, 'flex-wrap: wrap')
            self.assertContains(response, 'min-width: 300px')
            self.assertContains(response, 'width: 100%')