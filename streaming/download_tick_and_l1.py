#!/usr/bin/env python3
"""
Download tick and L1 data in the correct format for full_trading_simulator
Saves both CSV (for process_symbol_date) and JSON (for temporal_sync_loader)
"""

import socket
import time
import json
import csv
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IQFeedDownloader:
    """Download tick and L1 data from IQFeed"""
    
    def __init__(self):
        self.base_dir = "/home/tcr1n15/PycharmProjects/L2"
        
        # Output directories
        self.tick_csv_dir = os.path.join(self.base_dir, "data/raw_ticks")
        self.l1_csv_dir = os.path.join(self.base_dir, "data/raw_l1")
        self.tick_json_dir = os.path.join(self.base_dir, "simulation/data/real_ticks")
        self.l1_json_dir = os.path.join(self.base_dir, "simulation/data/l1_historical")
        
        # Create all directories
        for dir_path in [self.tick_csv_dir, self.l1_csv_dir, self.tick_json_dir, self.l1_json_dir]:
            os.makedirs(dir_path, exist_ok=True)
    
    def download_data(self, symbol: str, date: str) -> bool:
        """Download tick and L1 data for a symbol on a specific date"""
        logger.info(f"\nDownloading data for {symbol} on {date}")
        
        # Convert date format
        dt = datetime.strptime(date, '%Y%m%d')
        
        # Download tick data
        ticks = self._download_ticks(symbol, dt)
        if not ticks:
            logger.warning(f"No tick data downloaded for {symbol} on {date}")
            return False
            
        # Generate L1 data from ticks
        l1_data = self._generate_l1_from_ticks(ticks)
        
        # Save in both formats
        self._save_tick_data(symbol, date, ticks)
        self._save_l1_data(symbol, date, l1_data)
        
        logger.info(f"✓ Successfully downloaded {len(ticks)} ticks for {symbol} on {date}")
        return True
    
    def _download_ticks(self, symbol: str, date: datetime) -> List[Dict]:
        """Download tick data for a symbol on a specific date"""
        logger.info(f"Downloading tick data for {symbol} on {date.strftime('%Y%m%d')}")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60)  # Increased timeout

        try:
            logger.info("Connecting to IQFeed...")
            sock.connect(("127.0.0.1", 9100))
            
            # Set protocol version
            sock.send(b"S,SET PROTOCOL,6.2\r\n")
            sock.recv(1024)  # Consume protocol response

            # Format date and time for market hours (9:30 AM to 4:00 PM)
            formatted_date = date.strftime('%Y%m%d')
            begin_time = f"{formatted_date} 093000"  # 9:30 AM
            end_time = f"{formatted_date} 160000"    # 4:00 PM
            
            # Use HTT command for time-based tick data (working format from trial test)
            # HTT,Symbol,BeginDateTime,EndDateTime,MaxDatapoints,BeginFilterTime,EndFilterTime,DataDirection,RequestID,DatapointsPerSend
            command = f"HTT,{symbol},{begin_time},{end_time},0,,,0,REQ_{symbol[:4]},100\r\n"
            logger.info(f"Sending HTT Command: {command.strip()}")
            sock.send(command.encode())

            # Collect response
            ticks = []
            buffer = b""
            start_time = time.time()
            
            while time.time() - start_time < 45:  # 45 second timeout
                try:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    
                    buffer += chunk
                    
                    # Check for end marker
                    if b'!ENDMSG!' in chunk:
                        break
                        
                except socket.timeout:
                    logger.warning("Socket timed out waiting for data")
                    break
                except Exception as e:
                    logger.error(f"Error receiving data: {e}")
                    break
            
            # Decode and parse response
            response_str = buffer.decode('utf-8', errors='ignore')
            lines = response_str.split('\r\n')
            
            error_found = False
            data_count = 0
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith('E,'):
                    logger.error(f"IQFeed Error: {line}")
                    error_found = True
                    continue
                    
                if line.startswith('S,') or '!ENDMSG!' in line:
                    continue
                
                # Parse tick data line
                # Actual format: REQ_ID,MSG_TYPE,TIMESTAMP,LAST,LAST_SIZE,TOTAL_VOLUME,BID,ASK,TICK_ID,BASIS,MARKET,CONDITIONS,...
                try:
                    parts = line.split(',')
                    if len(parts) >= 8 and not line.startswith('E,'):
                        # Skip request ID and message type
                        timestamp_str = parts[2]
                        price = float(parts[3])
                        size = int(parts[4])
                        bid = float(parts[6]) if parts[6] else 0
                        ask = float(parts[7]) if parts[7] else 0
                        conditions = parts[11] if len(parts) > 11 else ""
                        
                        # Validate timestamp format
                        if len(timestamp_str) >= 19:  # YYYY-MM-DD HH:MM:SS format
                            tick = {
                                'timestamp': timestamp_str,
                                'price': price,
                                'size': size,
                                'conditions': conditions,
                                'bid': bid,
                                'ask': ask
                            }
                            ticks.append(tick)
                            data_count += 1
                        else:
                            continue  # Skip malformed timestamps
                        
                except (ValueError, IndexError) as e:
                    logger.debug(f"Skipping malformed line: {line[:100]} - {e}")
                    continue
            
            if error_found and data_count == 0:
                logger.error("IQFeed returned errors and no data")
                return []
            
            logger.info(f"Successfully downloaded {len(ticks)} ticks for {symbol}")
            return ticks

        except Exception as e:
            logger.error(f"Error downloading tick data: {e}")
            return []
        finally:
            sock.close()
    
    def _generate_l1_from_ticks(self, ticks: List[Dict]) -> List[Dict]:
        """Generate L1 quotes from tick data"""
        l1_data = []
        
        # Simple approach: create synthetic quotes around each trade
        for tick in ticks:
            price = tick['price']
            
            # Estimate spread based on price level
            if price < 1:
                spread = 0.01  # 1 cent for penny stocks
            elif price < 10:
                spread = 0.02  # 2 cents
            else:
                spread = 0.05  # 5 cents
                
            # Create synthetic quote
            l1_quote = {
                'timestamp': tick['timestamp'],
                'bid': round(price - spread/2, 2),
                'ask': round(price + spread/2, 2),
                'bid_size': 100,  # Default sizes
                'ask_size': 100
            }
            l1_data.append(l1_quote)
            
        return l1_data
    
    def _save_tick_data(self, symbol: str, date: str, ticks: List[Dict]):
        """Save tick data in both CSV and JSON formats"""
        
        # Create symbol directories
        os.makedirs(f"{self.tick_csv_dir}/{symbol}", exist_ok=True)
        
        # Save CSV
        csv_file = f"{self.tick_csv_dir}/{symbol}/{symbol}_ticks_{date}.csv"
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'price', 'size', 'conditions'])
            for tick in ticks:
                writer.writerow([
                    tick['timestamp'],
                    tick['price'],
                    tick['size'],
                    tick.get('conditions', '')
                ])
        
        # Save JSON
        json_file = f"{self.tick_json_dir}/{symbol}_{date}.json"
        with open(json_file, 'w') as f:
            json.dump(ticks, f, indent=2)
    
    def _save_l1_data(self, symbol: str, date: str, l1_data: List[Dict]):
        """Save L1 data in both CSV and JSON formats"""
        
        # Create symbol directories
        os.makedirs(f"{self.l1_csv_dir}/{symbol}", exist_ok=True)
        
        # Save CSV
        csv_file = f"{self.l1_csv_dir}/{symbol}/{symbol}_l1_{date}.csv"
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'bid', 'ask', 'bid_size', 'ask_size'])
            for quote in l1_data:
                writer.writerow([
                    quote['timestamp'],
                    quote['bid'],
                    quote['ask'],
                    quote['bid_size'],
                    quote['ask_size']
                ])
        
        # Save JSON (in expected format)
        json_file = f"{self.l1_json_dir}/{symbol}_{date}_l1.json"
        json_data = {
            'summary': {
                'symbol': symbol,
                'date': date,
                'tick_count': len(l1_data)
            },
            'ticks': l1_data
        }
        with open(json_file, 'w') as f:
            json.dump(json_data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Download tick and L1 data from IQFeed')
    parser.add_argument('--symbol', required=True, help='Stock symbol')
    parser.add_argument('--date', required=True, help='Date in YYYYMMDD format')
    
    args = parser.parse_args()
    
    downloader = IQFeedDownloader()
    success = downloader.download_data(args.symbol, args.date)
    
    if success:
        logger.info(f"\n✓ Download complete for {args.symbol} on {args.date}")
    else:
        logger.error(f"\n✗ Download failed for {args.symbol} on {args.date}")
        

if __name__ == "__main__":
    main()