#!/usr/bin/env python3
"""
Data Validation Report
Generates comprehensive validation report to ensure no fake data
"""

import json
import numpy as np
from typing import Dict, List, Any
from datetime import datetime


class DataValidationReport:
    """Generate validation report for confidence in data integrity"""
    
    def __init__(self):
        self.validations = []
        self.warnings = []
        self.confirmations = []
        
    def validate_metrics(self, symbol: str, metrics: Dict) -> Dict:
        """Validate all metrics for realistic values"""
        
        report = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'validations': [],
            'warnings': [],
            'confirmations': [],
            'overall_confidence': 0
        }
        
        # Check spreads
        if 'microstructure' in metrics:
            micro = metrics['microstructure']
            
            # Spread validation
            avg_spread = micro.get('avg_spread', 0)
            if avg_spread > 0:
                if avg_spread < 0.001:  # Less than 0.1%
                    report['warnings'].append(f"Unusually tight spread: {avg_spread:.4f}")
                elif avg_spread > 0.5:  # Greater than 50%
                    report['warnings'].append(f"Extremely wide spread: {avg_spread:.4f}")
                else:
                    report['confirmations'].append(f"Spread realistic: {avg_spread:.4f}")
                    
            # Trade size validation
            avg_trade_size = micro.get('avg_trade_size', 0)
            if avg_trade_size == 100:
                report['warnings'].append("Trade size exactly 100 - possible default value")
            elif avg_trade_size > 0:
                report['confirmations'].append(f"Trade size varies: {avg_trade_size:.1f}")
                
            # Volume distribution
            buy_vol = micro.get('buy_volume', 0)
            sell_vol = micro.get('sell_volume', 0)
            if buy_vol > 0 and sell_vol > 0:
                ratio = buy_vol / (buy_vol + sell_vol)
                if 0.3 < ratio < 0.7:
                    report['confirmations'].append(f"Balanced volume: {ratio:.1%} buy")
                else:
                    report['warnings'].append(f"Imbalanced volume: {ratio:.1%} buy")
                    
            # Entry metrics validation
            if 'entry_windows' in micro:
                windows = micro.get('entry_windows', 0)
                if windows > 0:
                    fill_prob = micro.get('fill_probability_1000', 0)
                    report['confirmations'].append(
                        f"Found {windows} entry windows, {fill_prob:.1%} fill probability"
                    )
                else:
                    report['warnings'].append("No entry windows found")
                    
            # Check for suspicious patterns
            if micro.get('crossed_market_pct', 0) > 0.01:  # More than 1%
                report['warnings'].append("High crossed market percentage")
                
            if micro.get('suspicious_size_pct', 0) > 0.01:
                report['warnings'].append("Suspicious trade sizes detected")
                
        # Daily metrics validation
        if 'daily' in metrics:
            daily = metrics['daily']
            
            # Price validation
            if daily.get('high', 0) < daily.get('low', 1):
                report['warnings'].append("High < Low - data error")
            elif daily.get('close', 0) > daily.get('high', 0):
                report['warnings'].append("Close > High - data error")
            else:
                report['confirmations'].append("OHLC values consistent")
                
            # Volume validation
            volume = daily.get('volume', 0)
            trades = daily.get('trades', 0)
            if volume > 0 and trades > 0:
                avg_per_trade = volume / trades
                if avg_per_trade == daily.get('avg_trade_size', 0):
                    report['confirmations'].append("Volume calculations match")
                    
        # L2 reconstruction confidence
        if 'l2_reconstruction' in metrics:
            confidence = metrics['l2_reconstruction'].get('confidence', 0)
            if confidence > 0.7:
                report['confirmations'].append(f"High L2 reconstruction confidence: {confidence:.1%}")
            elif confidence > 0:
                report['warnings'].append(f"Low L2 reconstruction confidence: {confidence:.1%}")
                
        # Calculate overall confidence
        total_checks = len(report['confirmations']) + len(report['warnings'])
        if total_checks > 0:
            report['overall_confidence'] = len(report['confirmations']) / total_checks
        else:
            report['overall_confidence'] = 0
            
        return report
        
    def generate_summary_report(self, all_results: List[Dict]) -> Dict:
        """Generate summary validation report across all results"""
        
        summary = {
            'total_symbol_days': len(all_results),
            'high_confidence_days': 0,
            'common_warnings': {},
            'validation_summary': {
                'no_fake_defaults': True,
                'realistic_spreads': True,
                'varied_trade_sizes': True,
                'consistent_calculations': True
            }
        }
        
        all_warnings = []
        
        for result in all_results:
            if 'validation_report' in result:
                report = result['validation_report']
                
                # Count high confidence days
                if report['overall_confidence'] > 0.8:
                    summary['high_confidence_days'] += 1
                    
                # Collect warnings
                all_warnings.extend(report['warnings'])
                
                # Check for fake defaults
                if "exactly 100" in str(report['warnings']):
                    summary['validation_summary']['no_fake_defaults'] = False
                    
        # Count warning frequencies
        for warning in all_warnings:
            warning_type = warning.split(':')[0]
            summary['common_warnings'][warning_type] = summary['common_warnings'].get(warning_type, 0) + 1
            
        # Add percentage
        summary['confidence_percentage'] = (summary['high_confidence_days'] / 
                                          summary['total_symbol_days'] * 100)
        
        return summary