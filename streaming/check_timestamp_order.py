#!/usr/bin/env python3
"""
Check if timestamps are in reverse order
"""

import json

# Check PAPL timestamps
symbols = ['PAPL', 'ANEB', 'ABVX']
for symbol in symbols:
    print(f"\n{symbol} Timestamp Check:")
    print("="*50)
    
    for date in ['20250721', '20250722']:
        try:
            with open(f'../simulation/data/real_ticks/{symbol}_{date}.json', 'r') as f:
                ticks = json.load(f)
            
            if not ticks:
                continue
                
            print(f"\n{date}:")
            print(f"Total ticks: {len(ticks)}")
            
            # Show first and last timestamps with prices
            print(f"\nFirst 3 ticks:")
            for i in range(min(3, len(ticks))):
                t = ticks[i]
                print(f"  {t['timestamp']} - ${t['price']:.2f} ({t['size']} shares)")
            
            print(f"\nLast 3 ticks:")
            for i in range(max(0, len(ticks)-3), len(ticks)):
                t = ticks[i]
                print(f"  {t['timestamp']} - ${t['price']:.2f} ({t['size']} shares)")
            
            # Check if sorted
            timestamps = [t['timestamp'] for t in ticks]
            is_sorted = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))
            print(f"\nTimestamps in chronological order: {is_sorted}")
            
        except Exception as e:
            print(f"Error reading {symbol} {date}: {e}")