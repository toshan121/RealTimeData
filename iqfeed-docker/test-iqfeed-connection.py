#!/usr/bin/env python3
"""
Test IQFeed connectivity from Docker container
"""
import socket
import time
import sys


def test_port(host, port, service_name):
    """Test if a port is open and responding."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"✓ {service_name:15} Port {port:5} - OPEN")
            return True
        else:
            print(f"✗ {service_name:15} Port {port:5} - CLOSED")
            return False
    except Exception as e:
        print(f"✗ {service_name:15} Port {port:5} - ERROR: {e}")
        return False


def test_iqfeed_protocol(host, port):
    """Test IQFeed protocol on admin port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        
        # IQFeed admin port should respond to S,STATS command
        sock.send(b"S,STATS\r\n")
        time.sleep(0.5)
        response = sock.recv(1024).decode('utf-8', errors='ignore')
        sock.close()
        
        if response:
            print(f"\n✓ IQFeed Protocol Test - SUCCESS")
            print(f"  Response: {response[:100]}...")
            return True
        else:
            print(f"\n✗ IQFeed Protocol Test - NO RESPONSE")
            return False
            
    except Exception as e:
        print(f"\n✗ IQFeed Protocol Test - ERROR: {e}")
        return False


def main():
    """Main test function."""
    print("IQFeed Docker Connection Test")
    print("=" * 50)
    
    # Test from different perspectives
    test_configs = [
        ("localhost", "Local connection"),
        ("0.0.0.0", "All interfaces"),
        ("host.docker.internal", "Docker host (if running from container)"),
    ]
    
    services = [
        (5009, "Admin"),
        (9100, "Level 1"),
        (9200, "Level 2/Lookup"),
        (9300, "History"),
        (9400, "News"),
        (8088, "HTTP API"),
    ]
    
    # Get LAN IP if available
    try:
        import subprocess
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        if result.returncode == 0:
            lan_ip = result.stdout.strip().split()[0]
            test_configs.append((lan_ip, "LAN IP"))
    except:
        pass
    
    all_passed = True
    
    for host, desc in test_configs:
        print(f"\nTesting from {desc} ({host}):")
        print("-" * 40)
        
        host_passed = True
        for port, service in services:
            if not test_port(host, port, service):
                host_passed = False
                all_passed = False
        
        # Extra protocol test on admin port
        if host == "localhost" and host_passed:
            test_iqfeed_protocol(host, 5009)
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All tests PASSED - IQFeed is accessible!")
    else:
        print("✗ Some tests FAILED - Check Docker logs")
        print("\nTroubleshooting:")
        print("1. Check if container is running: docker ps")
        print("2. View logs: docker-compose logs iqfeed")
        print("3. Check firewall settings for ports")
        print("4. Verify credentials in docker-compose.yml")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())