#!/usr/bin/env python3
"""
Comprehensive test runner - run everything locally
"""
import subprocess
import sys
import time
from pathlib import Path


def run_command(cmd, description, timeout=60):
    """Run command with proper output handling."""
    print(f"\n{'='*60}")
    print(f"🧪 {description}")
    print(f"{'='*60}")
    print(f"Command: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(cmd, timeout=timeout, text=True)
        if result.returncode == 0:
            print(f"✅ {description} - PASSED")
            return True
        else:
            print(f"❌ {description} - FAILED (exit code: {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏰ {description} - TIMEOUT after {timeout}s")
        return False
    except Exception as e:
        print(f"💥 {description} - ERROR: {e}")
        return False


def check_prerequisites():
    """Check that required services are running."""
    print("🔍 Checking prerequisites...")
    
    # Check if infrastructure services are running
    try:
        result = subprocess.run(['docker', 'ps'], capture_output=True, text=True)
        if 'l2_redis' in result.stdout and 'l2_clickhouse' in result.stdout:
            print("✅ Infrastructure services are running")
            return True
        else:
            print("❌ Infrastructure services not running")
            print("Please start them with: cd infrastructure && docker-compose up -d")
            return False
    except:
        print("❌ Docker not available or services not running")
        return False


def main():
    """Run comprehensive test suite."""
    print("🚀 Market Data System - Comprehensive Test Suite")
    print("=" * 60)
    
    # Check prerequisites
    if not check_prerequisites():
        return 1
    
    # Wait for services to be ready
    print("⏳ Waiting for services to stabilize...")
    time.sleep(5)
    
    # Test suite
    tests = [
        # Core TUI functionality
        (['python', 'monitor.py', 'test'], "TUI Service Tests"),
        (['python', 'monitor.py', 'status'], "TUI Status Check"),
        
        # Unit tests
        (['python', '-m', 'pytest', 'test_monitor.py', '-v'], "Core TUI Unit Tests"),
        (['python', '-m', 'pytest', 'test_monitor_comprehensive.py', '-v'], "Comprehensive TUI Tests"),
        (['python', '-m', 'pytest', 'test_system_integration.py', '-v'], "System Integration Tests"),
        
        # Critical validation
        (['python', '-m', 'pytest', 'tests/test_critical_validation.py', '-v'], "Critical System Validation", 120),
        
        # Coverage report
        (['coverage', 'run', '--source=monitor.py', '-m', 'pytest', 'test_monitor.py', '-q'], "Coverage Collection"),
        (['coverage', 'report', '-m', '--include=monitor.py'], "Coverage Report"),
    ]
    
    results = []
    for i, test_info in enumerate(tests, 1):
        cmd = test_info[0]
        desc = test_info[1]
        timeout = test_info[2] if len(test_info) > 2 else 60
        
        print(f"\n[{i}/{len(tests)}] ", end="")
        success = run_command(cmd, desc, timeout)
        results.append((desc, success))
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for desc, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status:8} {desc}")
    
    print(f"\n📈 Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All tests passed! System is ready for deployment.")
        return 0
    else:
        print("💥 Some tests failed. Check output above for details.")
        return 1


if __name__ == '__main__':
    sys.exit(main())