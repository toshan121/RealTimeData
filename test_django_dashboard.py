#!/usr/bin/env python
"""
Comprehensive test suite for Django Dashboard
Run from project root: python test_django_dashboard.py
"""
import os
import sys
import subprocess
import time
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run a command and return success status."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Command failed: {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        return False
    
    print(f"✅ Command succeeded")
    return True


def main():
    """Run comprehensive Django dashboard tests."""
    project_root = Path(__file__).parent
    dashboard_dir = project_root / 'simple_dashboard'
    
    if not dashboard_dir.exists():
        print(f"❌ Dashboard directory not found: {dashboard_dir}")
        return 1
    
    print("🧪 Django Dashboard Test Suite")
    print("=" * 60)
    
    # Change to dashboard directory
    os.chdir(dashboard_dir)
    
    # Test categories
    test_suites = [
        {
            'name': 'Unit Tests - Views',
            'cmd': ['python', 'manage.py', 'test', 'monitor.tests.test_views', '-v', '2']
        },
        {
            'name': 'Integration Tests',
            'cmd': ['python', 'manage.py', 'test', 'monitor.tests.test_integration', '-v', '2']
        },
        {
            'name': 'Frontend Tests',
            'cmd': ['python', 'manage.py', 'test', 'monitor.tests.test_frontend', '-v', '2']
        },
        {
            'name': 'All Tests with Coverage',
            'cmd': ['coverage', 'run', '--source=.', 'manage.py', 'test', 'monitor.tests', '-v', '2']
        }
    ]
    
    failed_tests = []
    
    for suite in test_suites:
        print(f"\n{'='*60}")
        print(f"Running: {suite['name']}")
        print(f"{'='*60}")
        
        if not run_command(suite['cmd']):
            failed_tests.append(suite['name'])
    
    # Generate coverage report
    print("\n" + "="*60)
    print("Generating Coverage Report")
    print("="*60)
    
    if run_command(['coverage', 'report', '-m']):
        run_command(['coverage', 'html'])
        print("\n📊 HTML coverage report generated in simple_dashboard/htmlcov/")
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    if failed_tests:
        print(f"❌ {len(failed_tests)} test suite(s) failed:")
        for test in failed_tests:
            print(f"  - {test}")
        return 1
    else:
        print("✅ All test suites passed!")
        
        # Additional test commands
        print("\n📝 Additional test commands you can run:")
        print("  # Run with pytest:")
        print("  cd simple_dashboard && pytest")
        print("")
        print("  # Run specific test class:")
        print("  python manage.py test monitor.tests.test_views.DashboardViewTests")
        print("")
        print("  # Run with pattern matching:")
        print("  python manage.py test monitor.tests -k 'kafka'")
        print("")
        print("  # Run tests in parallel (if django-parallel-test installed):")
        print("  python manage.py test --parallel")
        
        return 0


if __name__ == '__main__':
    sys.exit(main())