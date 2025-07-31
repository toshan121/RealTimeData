# IQFeed Docker Setup

This directory contains the Docker setup for running IQFeed in a container with LAN accessibility.

## Quick Start

1. **Start IQFeed:**
   ```bash
   cd iqfeed-docker
   ./start-iqfeed.sh
   ```

2. **Test Connection:**
   ```bash
   python3 test-iqfeed-connection.py
   ```

3. **View Logs:**
   ```bash
   docker-compose logs -f iqfeed
   ```

4. **Stop IQFeed:**
   ```bash
   docker-compose down
   ```

## Configuration

IQFeed credentials are configured in `docker-compose.yml`:
- Login: 523093
- Password: 40997223
- Product ID: IQFEED_DIAGNOSTICS

## Network Access

All ports are bound to `0.0.0.0` for LAN accessibility:

| Service | Port | Description |
|---------|------|-------------|
| Admin | 5009 | Administrative commands |
| Level 1 | 9100 | Real-time quotes |
| Level 2 | 9200 | Market depth data |
| History | 9300 | Historical data |
| News | 9400 | News feed |
| HTTP API | 8088 | HTTP proxy interface |
| VNC | 5901 | Remote desktop (debugging) |

## Accessing from Other Machines

From other machines on your LAN, use your host machine's IP address:
```python
# Example: Connect from another machine
iqfeed_host = "192.168.1.100"  # Replace with your host IP
iqfeed_port = 9200
```

## Firewall Configuration

If you have a firewall enabled, allow these ports:
```bash
# Ubuntu/Debian
sudo ufw allow 5009/tcp
sudo ufw allow 9100/tcp
sudo ufw allow 9200/tcp
sudo ufw allow 9300/tcp
sudo ufw allow 9400/tcp
sudo ufw allow 8088/tcp
```

## Troubleshooting

1. **Container won't start:**
   - Check Docker is running: `docker info`
   - Check logs: `docker-compose logs iqfeed`

2. **Can't connect from LAN:**
   - Check firewall settings
   - Verify host IP: `hostname -I`
   - Test with telnet: `telnet <host-ip> 9200`

3. **Authentication errors:**
   - Verify credentials in docker-compose.yml
   - Check IQFeed account is active

## Integration with Recording System

Update your recording scripts to use the Docker IQFeed:
```python
# In your Python scripts
IQFEED_HOST = "localhost"  # or your LAN IP
IQFEED_PORT = 9200
```

## VNC Access

For debugging, connect to VNC on port 5901:
- VNC Viewer: `<host-ip>:5901`
- No password required