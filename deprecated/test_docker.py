#!/usr/bin/env python3
"""
Test Docker build and functionality
"""
import subprocess
import time
import requests
from pathlib import Path


def run_command(cmd, timeout=30):
    """Run command with timeout."""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"❌ Command failed: {result.stderr}")
            return False
        print(f"✅ Command succeeded")
        return True
    except subprocess.TimeoutExpired:
        print(f"❌ Command timed out after {timeout}s")
        return False


def test_docker_build():
    """Test Docker image builds successfully."""
    print("🔨 Testing Docker build...")
    return run_command(['docker', 'build', '-t', 'market-data-system', '.'], timeout=300)


def test_docker_run():
    """Test Docker container runs and services are accessible."""
    print("🚀 Testing Docker run...")
    
    # Start container in background
    if not run_command(['docker', 'run', '-d', '--name', 'test-market-data', '-p', '8080:8080', 'market-data-system']):
        return False
    
    # Wait for container to be ready
    print("⏳ Waiting for container to start...")
    time.sleep(30)
    
    try:
        # Test web interface
        print("🌐 Testing web interface...")
        response = requests.get('http://localhost:8080', timeout=10)
        if response.status_code == 200:
            print("✅ Web interface accessible")
        else:
            print(f"❌ Web interface returned {response.status_code}")
            return False
        
        # Test TUI functionality via container exec
        print("🖥️ Testing TUI functionality...")
        result = subprocess.run([
            'docker', 'exec', 'test-market-data', 'python', 'monitor.py', 'test'
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode in [0, 1]:  # 0 = all up, 1 = some down (expected)
            print("✅ TUI functionality working")
        else:
            print(f"❌ TUI test failed: {result.stderr}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Container test failed: {e}")
        return False
    finally:
        # Cleanup
        print("🧹 Cleaning up test container...")
        subprocess.run(['docker', 'stop', 'test-market-data'], capture_output=True)
        subprocess.run(['docker', 'rm', 'test-market-data'], capture_output=True)


def test_compose():
    """Test docker-compose setup."""
    print("🐙 Testing Docker Compose...")
    
    # Check if docker-compose.yml exists
    if not Path('docker-compose.yml').exists():
        print("❌ docker-compose.yml not found")
        return False
    
    # Validate compose file
    if not run_command(['docker-compose', 'config']):
        return False
    
    print("✅ Docker Compose configuration valid")
    return True


def main():
    """Run all Docker tests."""
    print("🐳 Docker Testing Suite")
    print("=" * 50)
    
    tests = [
        ("Docker Build", test_docker_build),
        ("Docker Compose Config", test_compose),
        ("Docker Run & Test", test_docker_run),
    ]
    
    passed = 0
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        print("-" * 30)
        if test_func():
            print(f"✅ {test_name} PASSED")
            passed += 1
        else:
            print(f"❌ {test_name} FAILED")
    
    print(f"\n" + "=" * 50)
    print(f"Docker Tests: {passed}/{len(tests)} passed")
    
    if passed == len(tests):
        print("🎉 All Docker tests passed!")
        print("\nTo run the system:")
        print("  docker-compose up -d")
        print("  # Access web TUI at http://localhost:8080")
        return 0
    else:
        print("💥 Some Docker tests failed!")
        return 1


if __name__ == '__main__':
    exit(main())