#!/usr/bin/env python3
"""Direct IQFeed connection test."""

import socket
import time

def test_direct_connection():
    """Test direct connection to IQFeed."""
    host = "192.168.0.48"
    port = 9200
    
    print(f"Connecting to IQFeed at {host}:{port}")
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        print("✓ Connected")
        
        # Try to receive any data
        print("\nWaiting for data (5 seconds)...")
        sock.settimeout(5.0)
        try:
            data = sock.recv(4096)
            if data:
                print(f"Received: {data}")
            else:
                print("No data received")
        except socket.timeout:
            print("Timeout - no data received")
            
        # Try sending a simple command
        print("\nSending test command...")
        sock.send(b"S,REQUEST ALL UPDATE FIELDNAMES\r\n")
        
        # Wait for response
        print("Waiting for response...")
        try:
            response = sock.recv(4096)
            if response:
                print(f"Response: {response}")
            else:
                print("No response")
        except socket.timeout:
            print("Timeout - no response")
            
        sock.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_direct_connection()