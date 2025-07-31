#!/usr/bin/env python
"""
Test runner script for the Simple Dashboard
Runs all tests and generates coverage report
"""
import os
import sys
import subprocess


def main():
    """Run tests with coverage."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
    
    # Commands to run
    commands = [
        # Run tests with coverage
        [
            'coverage', 'run', '--source=.', 
            'manage.py', 'test', 'monitor.tests', '-v', '2'
        ],
        
        # Generate coverage report
        ['coverage', 'report', '-m'],
        
        # Generate HTML coverage report
        ['coverage', 'html'],
    ]
    
    print("Running Django Dashboard Tests with Coverage...")
    print("=" * 60)
    
    for cmd in commands:
        print(f"\nRunning: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=False, text=True)
        
        if result.returncode != 0:
            print(f"Command failed with return code {result.returncode}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ All tests completed successfully!")
    print("📊 Coverage report available in htmlcov/index.html")
    print("\nTo view coverage report:")
    print("  open htmlcov/index.html")
    print("\nTo run specific test modules:")
    print("  python manage.py test monitor.tests.test_views")
    print("  python manage.py test monitor.tests.test_integration")
    print("  python manage.py test monitor.tests.test_frontend")


if __name__ == '__main__':
    main()