#!/usr/bin/env python3
"""
Process NASDAQ screener CSV to extract stocks in $1-$20 range.
Outputs a clean list of 495 stocks for recording.
"""

import pandas as pd
import sys
from pathlib import Path

def process_universe_csv(input_path: str, output_path: str = None):
    """Process universe CSV and filter stocks by price range."""
    print(f"📂 Loading universe from {input_path}")
    
    # Load CSV
    df = pd.read_csv(input_path)
    print(f"   Total stocks in CSV: {len(df)}")
    
    # Clean Last Sale column - remove $ and convert to float
    df['Last Sale'] = df['Last Sale'].str.replace('$', '', regex=False)
    df['Last Sale'] = pd.to_numeric(df['Last Sale'], errors='coerce')
    
    # Filter by price range ($1 - $20)
    filtered = df[(df['Last Sale'] >= 1.0) & (df['Last Sale'] <= 20.0)].copy()
    print(f"   Stocks in $1-$20 range: {len(filtered)}")
    
    # Sort by market cap (descending) and volume (descending)
    # Handle market cap cleaning
    if 'Market Cap' in filtered.columns:
        filtered['Market Cap'] = pd.to_numeric(filtered['Market Cap'], errors='coerce').fillna(0)
    
    if 'Volume' in filtered.columns:
        filtered['Volume'] = pd.to_numeric(filtered['Volume'], errors='coerce').fillna(0)
        filtered = filtered.sort_values(['Market Cap', 'Volume'], ascending=False)
    
    # Take top 495 stocks
    final_stocks = filtered.head(495)
    
    # Clean up - remove any rows with NaN symbols
    final_stocks = final_stocks.dropna(subset=['Symbol'])
    
    # Create output
    if output_path:
        # Save detailed CSV
        final_stocks.to_csv(output_path, index=False)
        print(f"✅ Saved {len(final_stocks)} stocks to {output_path}")
        
        # Also save simple symbol list
        symbol_list_path = Path(output_path).parent / "symbols_495.txt"
        with open(symbol_list_path, 'w') as f:
            symbols = [str(s) for s in final_stocks['Symbol'].tolist() if pd.notna(s)]
            f.write('\n'.join(symbols))
        print(f"✅ Saved symbol list to {symbol_list_path}")
    
    # Print summary
    print("\n📊 Summary:")
    print(f"   Total filtered stocks: {len(final_stocks)}")
    print(f"   Price range: ${final_stocks['Last Sale'].min():.2f} - ${final_stocks['Last Sale'].max():.2f}")
    if 'Sector' in final_stocks.columns:
        print(f"   Unique sectors: {final_stocks['Sector'].nunique()}")
    
    # Show sample
    print("\n📋 Sample stocks:")
    print(final_stocks[['Symbol', 'Name', 'Last Sale', 'Market Cap', 'Volume']].head(10).to_string(index=False))
    
    return final_stocks

if __name__ == "__main__":
    # Default paths
    input_csv = "data/universe/nasdaq_screener_1753296263842.csv"
    output_csv = "data/universe/universe_495_filtered.csv"
    
    # Allow command line override
    if len(sys.argv) > 1:
        input_csv = sys.argv[1]
    if len(sys.argv) > 2:
        output_csv = sys.argv[2]
    
    # Process
    process_universe_csv(input_csv, output_csv)