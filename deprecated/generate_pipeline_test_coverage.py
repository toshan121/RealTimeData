#!/usr/bin/env python3
"""
Pipeline Test Coverage Analysis and Report Generator

This script analyzes the comprehensive test coverage of the end-to-end data pipeline
management system and generates detailed coverage reports.

The analysis covers:
1. Pipeline orchestration test coverage
2. Component integration test coverage  
3. Data flow integrity test coverage
4. Error handling and recovery test coverage
5. Performance monitoring test coverage
6. Production operations test coverage

This generates both code coverage metrics and functional coverage analysis
to ensure the pipeline is thoroughly validated for production readiness.
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Any, Tuple
from pathlib import Path
import coverage
import pytest

# Test framework setup
sys.path.append(str(Path(__file__).parent))

def run_coverage_analysis() -> Dict[str, Any]:
    """Run comprehensive coverage analysis of pipeline tests."""
    
    print("🔍 Running comprehensive pipeline test coverage analysis...")
    
    # Initialize coverage
    cov = coverage.Coverage(
        source=['pipeline_orchestrator', 'pipeline_health_monitor', 'ingestion', 'processing', 'storage'],
        omit=[
            'tests/*',
            'test_*.py',
            '*/__pycache__/*',
            '*/venv/*',
            '*/env/*'
        ]
    )
    
    # Start coverage collection
    cov.start()
    
    try:
        # Run the comprehensive validation test
        result = pytest.main([
            'test_end_to_end_pipeline_validation.py',
            '-v',
            '--tb=short',
            '-x',  # Stop on first failure
            '--timeout=300'  # 5 minute timeout
        ])
        
        # Stop coverage collection
        cov.stop()
        cov.save()
        
        # Generate coverage report
        coverage_data = {}
        
        # Get coverage statistics
        total_coverage = cov.report(show_missing=False, skip_covered=False)
        
        # Generate detailed coverage data
        analysis = cov.analysis2('pipeline_orchestrator.py')
        if analysis:
            _, executable, excluded, missing, missing_formatted = analysis
            coverage_data['pipeline_orchestrator'] = {
                'executable_lines': len(executable),
                'missing_lines': len(missing),
                'coverage_percent': ((len(executable) - len(missing)) / len(executable)) * 100 if executable else 0,
                'missing_line_numbers': missing
            }
        
        # Generate HTML coverage report
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_dir = f'htmlcov_pipeline_validation_{timestamp}'
        cov.html_report(directory=html_dir)
        
        return {
            'test_result': result,
            'total_coverage_percent': total_coverage,
            'detailed_coverage': coverage_data,
            'html_report_dir': html_dir,
            'timestamp': timestamp
        }
        
    except Exception as e:
        print(f"❌ Coverage analysis failed: {e}")
        return {
            'test_result': 1,
            'error': str(e),
            'timestamp': datetime.now().strftime('%Y%m%d_%H%M%S')
        }
    
    finally:
        # Cleanup
        try:
            cov.stop()
        except:
            pass


def analyze_functional_coverage() -> Dict[str, Any]:
    """Analyze functional test coverage of pipeline features."""
    
    print("📊 Analyzing functional test coverage...")
    
    # Define the functional areas that should be tested
    functional_areas = {
        'pipeline_orchestration': {
            'description': 'Pipeline startup, shutdown, and state management',
            'test_patterns': [
                'test_orchestrator_initialization',
                'test_orchestrator_startup_sequence', 
                'test_orchestrator_shutdown_sequence',
                'test_orchestrator_state_management',
                'test_orchestrator_component_coordination'
            ]
        },
        'component_integration': {
            'description': 'Integration between pipeline components',
            'test_patterns': [
                'test_kafka_integration',
                'test_redis_integration',
                'test_clickhouse_integration',
                'test_order_book_integration',
                'test_feature_calculation_integration'
            ]
        },
        'data_flow_integrity': {
            'description': 'End-to-end data flow and integrity validation',
            'test_patterns': [
                'test_end_to_end_message_flow',
                'test_message_ordering_preservation',
                'test_data_transformation_accuracy',
                'test_message_tracing_completeness',
                'test_data_consistency_across_stages'
            ]
        },
        'error_handling': {
            'description': 'Error handling and recovery mechanisms',
            'test_patterns': [
                'test_component_failure_handling',
                'test_invalid_data_handling',
                'test_error_propagation',
                'test_circuit_breaker',
                'test_automatic_recovery',
                'test_graceful_degradation',
                'test_backpressure_handling'
            ]
        },
        'performance_monitoring': {
            'description': 'Performance monitoring and bottleneck detection',
            'test_patterns': [
                'test_health_monitoring',
                'test_alert_generation',
                'test_metrics_collection',
                'test_bottleneck_detection',
                'test_performance_benchmarks'
            ]
        },
        'production_operations': {
            'description': 'Production deployment and operational scenarios',
            'test_patterns': [
                'test_multi_symbol_processing',
                'test_high_load_scenarios',
                'test_shutdown_with_active_processing',
                'test_signal_handling',
                'test_resource_utilization'
            ]
        }
    }
    
    # Analyze test file to determine which tests are implemented
    test_file = 'test_end_to_end_pipeline_validation.py'
    
    coverage_analysis = {}
    
    try:
        with open(test_file, 'r') as f:
            test_content = f.read()
        
        for area, details in functional_areas.items():
            implemented_tests = []
            missing_tests = []
            
            for test_pattern in details['test_patterns']:
                if f'def _test_{test_pattern.replace("test_", "")}(' in test_content or \
                   f'def {test_pattern}(' in test_content:
                    implemented_tests.append(test_pattern)
                else:
                    missing_tests.append(test_pattern)
            
            coverage_percent = (len(implemented_tests) / len(details['test_patterns'])) * 100
            
            coverage_analysis[area] = {
                'description': details['description'],
                'total_tests': len(details['test_patterns']),
                'implemented_tests': len(implemented_tests),
                'missing_tests': len(missing_tests),
                'coverage_percent': coverage_percent,
                'implemented_test_list': implemented_tests,
                'missing_test_list': missing_tests
            }
    
    except Exception as e:
        print(f"❌ Functional coverage analysis failed: {e}")
        return {'error': str(e)}
    
    return coverage_analysis


def generate_comprehensive_report(coverage_results: Dict[str, Any], functional_coverage: Dict[str, Any]) -> str:
    """Generate comprehensive test coverage report."""
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_lines = [
        "COMPREHENSIVE PIPELINE TEST COVERAGE REPORT",
        "=" * 60,
        f"Generated: {timestamp}",
        f"System: End-to-End Data Pipeline Management",
        "",
        "EXECUTIVE SUMMARY",
        "-" * 20
    ]
    
    # Test execution summary
    if coverage_results.get('test_result') == 0:
        report_lines.append("✅ Pipeline validation tests: PASSED")
    else:
        report_lines.append("❌ Pipeline validation tests: FAILED")
    
    if 'total_coverage_percent' in coverage_results:
        report_lines.append(f"📊 Code coverage: {coverage_results['total_coverage_percent']:.1f}%")
    
    report_lines.extend(["", "FUNCTIONAL COVERAGE ANALYSIS", "-" * 30])
    
    total_functional_tests = 0
    implemented_functional_tests = 0
    
    for area, analysis in functional_coverage.items():
        if 'error' not in analysis:
            total_functional_tests += analysis['total_tests']
            implemented_functional_tests += analysis['implemented_tests']
            
            status = "✅" if analysis['coverage_percent'] >= 80 else "⚠️" if analysis['coverage_percent'] >= 60 else "❌"
            
            report_lines.extend([
                f"{status} {area.replace('_', ' ').title()}:",
                f"   Description: {analysis['description']}",
                f"   Coverage: {analysis['coverage_percent']:.1f}% ({analysis['implemented_tests']}/{analysis['total_tests']} tests)",
                ""
            ])
    
    overall_functional_coverage = (implemented_functional_tests / total_functional_tests) * 100 if total_functional_tests > 0 else 0
    
    report_lines.extend([
        f"Overall Functional Coverage: {overall_functional_coverage:.1f}%",
        f"Total Functional Tests: {implemented_functional_tests}/{total_functional_tests}",
        ""
    ])
    
    # Detailed coverage breakdown
    report_lines.extend(["DETAILED COVERAGE BREAKDOWN", "-" * 30])
    
    for area, analysis in functional_coverage.items():
        if 'error' not in analysis and analysis['missing_tests']:
            report_lines.extend([
                f"Missing tests in {area.replace('_', ' ').title()}:",
                *[f"  - {test}" for test in analysis['missing_test_list']],
                ""
            ])
    
    # Code coverage details
    if 'detailed_coverage' in coverage_results:
        report_lines.extend(["CODE COVERAGE DETAILS", "-" * 25])
        
        for module, details in coverage_results['detailed_coverage'].items():
            report_lines.extend([
                f"{module}:",
                f"  Lines of code: {details['executable_lines']}",
                f"  Coverage: {details['coverage_percent']:.1f}%",
                f"  Missing lines: {len(details['missing_line_numbers'])}",
                ""
            ])
    
    # Recommendations
    report_lines.extend(["RECOMMENDATIONS", "-" * 15])
    
    recommendations = []
    
    if overall_functional_coverage < 80:
        recommendations.append("Implement missing functional tests to achieve 80%+ coverage")
    
    if coverage_results.get('total_coverage_percent', 0) < 70:
        recommendations.append("Improve code coverage to at least 70%")
    
    if coverage_results.get('test_result', 1) != 0:
        recommendations.append("Fix failing tests before production deployment")
    
    # Add area-specific recommendations
    for area, analysis in functional_coverage.items():
        if 'error' not in analysis and analysis['coverage_percent'] < 70:
            recommendations.append(f"Priority: Implement missing tests in {area.replace('_', ' ')}")
    
    if not recommendations:
        recommendations.append("✅ Test coverage meets production standards")
    
    report_lines.extend([f"• {rec}" for rec in recommendations])
    
    # Production readiness assessment
    report_lines.extend(["", "PRODUCTION READINESS ASSESSMENT", "-" * 35])
    
    readiness_criteria = [
        ("Functional coverage >= 80%", overall_functional_coverage >= 80),
        ("Code coverage >= 70%", coverage_results.get('total_coverage_percent', 0) >= 70),
        ("All tests passing", coverage_results.get('test_result') == 0),
        ("All critical areas covered", all(
            analysis.get('coverage_percent', 0) >= 60 
            for analysis in functional_coverage.values() 
            if 'error' not in analysis
        ))
    ]
    
    for criterion, met in readiness_criteria:
        status = "✅" if met else "❌"
        report_lines.append(f"{status} {criterion}")
    
    production_ready = all(met for _, met in readiness_criteria)
    
    report_lines.extend([
        "",
        f"OVERALL ASSESSMENT: {'✅ PRODUCTION READY' if production_ready else '❌ NOT PRODUCTION READY'}",
        ""
    ])
    
    if coverage_results.get('html_report_dir'):
        report_lines.append(f"📊 Detailed HTML coverage report: {coverage_results['html_report_dir']}/index.html")
    
    return "\n".join(report_lines)


def save_coverage_report(report_content: str, coverage_results: Dict[str, Any]) -> str:
    """Save coverage report to file."""
    
    timestamp = coverage_results.get('timestamp', datetime.now().strftime('%Y%m%d_%H%M%S'))
    
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    # Save text report
    report_file = f'logs/pipeline_test_coverage_report_{timestamp}.txt'
    with open(report_file, 'w') as f:
        f.write(report_content)
    
    # Save JSON data
    json_file = f'logs/pipeline_test_coverage_data_{timestamp}.json'
    with open(json_file, 'w') as f:
        json.dump({
            'coverage_results': coverage_results,
            'report_content': report_content,
            'generation_time': datetime.now().isoformat()
        }, f, indent=2, default=str)
    
    return report_file


def main():
    """Main entry point for coverage analysis."""
    
    print("🚀 Starting comprehensive pipeline test coverage analysis")
    print("=" * 70)
    
    start_time = time.time()
    
    try:
        # Step 1: Run coverage analysis
        print("📊 Step 1: Running code coverage analysis...")
        coverage_results = run_coverage_analysis()
        
        # Step 2: Analyze functional coverage
        print("🔍 Step 2: Analyzing functional test coverage...")
        functional_coverage = analyze_functional_coverage()
        
        # Step 3: Generate comprehensive report
        print("📋 Step 3: Generating comprehensive coverage report...")
        report_content = generate_comprehensive_report(coverage_results, functional_coverage)
        
        # Step 4: Save report
        print("💾 Step 4: Saving coverage report...")
        report_file = save_coverage_report(report_content, coverage_results)
        
        # Display summary
        execution_time = time.time() - start_time
        
        print("\n" + "=" * 70)
        print("COVERAGE ANALYSIS SUMMARY")
        print("=" * 70)
        print(report_content)
        print("=" * 70)
        print(f"📁 Report saved to: {report_file}")
        print(f"⏱️  Analysis completed in {execution_time:.1f} seconds")
        
        # Exit code based on test results
        if coverage_results.get('test_result') == 0:
            print("✅ Coverage analysis completed successfully")
            return 0
        else:
            print("❌ Coverage analysis completed with test failures")
            return 1
            
    except KeyboardInterrupt:
        print("\n⚠️  Coverage analysis interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Coverage analysis failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)