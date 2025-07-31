#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "sqlite3",
# ]
# ///

import json
import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

def init_database(db_path):
    """Initialize SQLite database with token usage table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            conversation_turn INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            estimated_cost_usd REAL,
            model_name TEXT DEFAULT 'claude-sonnet-4',
            hook_trigger TEXT,
            metadata TEXT
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON token_usage(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session ON token_usage(session_id)")
    
    conn.commit()
    conn.close()

def calculate_cost(input_tokens, output_tokens):
    """Calculate cost estimate based on Claude Sonnet 4 pricing."""
    # Current Claude Sonnet 4 pricing (per 1K tokens)
    input_cost_per_1k = 0.015   # $0.015 per 1K input tokens
    output_cost_per_1k = 0.075  # $0.075 per 1K output tokens
    
    input_cost = (input_tokens * input_cost_per_1k) / 1000
    output_cost = (output_tokens * output_cost_per_1k) / 1000
    
    return input_cost + output_cost

def parse_transcript(transcript_path):
    """Parse JSONL transcript file to extract real token counts."""
    if not transcript_path or not os.path.exists(transcript_path):
        return {
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'conversation_turns': 0,
            'model_name': 'claude-sonnet-4'
        }
    
    total_input_tokens = 0
    total_output_tokens = 0
    conversation_turns = 0
    model_name = 'claude-sonnet-4'
    
    try:
        with open(transcript_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    conversation_turns += 1
                    
                    # Extract model name if available
                    if 'model' in data and data['model']:
                        model_name = data['model']
                    
                    # Extract token usage from the data structure
                    usage = data.get('usage', {})
                    if usage:
                        input_tokens = usage.get('input_tokens', 0)
                        output_tokens = usage.get('output_tokens', 0)
                        
                        total_input_tokens += input_tokens
                        total_output_tokens += output_tokens
                    
                except json.JSONDecodeError:
                    continue  # Skip malformed lines
                    
    except Exception:
        pass  # Fail silently
    
    return {
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'conversation_turns': conversation_turns,
        'model_name': model_name
    }

def store_token_data(db_path, session_id, token_data, hook_trigger):
    """Store token usage data in SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if record already exists for this session/trigger
        cursor.execute("""
            SELECT COUNT(*) FROM token_usage 
            WHERE session_id = ? AND hook_trigger = ?
        """, (session_id, hook_trigger))
        
        existing_count = cursor.fetchone()[0]
        
        total_tokens = token_data['total_input_tokens'] + token_data['total_output_tokens']
        estimated_cost = calculate_cost(token_data['total_input_tokens'], token_data['total_output_tokens'])
        metadata = f"turns:{token_data['conversation_turns']},model:{token_data['model_name']}"
        
        if existing_count > 0:
            # Update existing record
            cursor.execute("""
                UPDATE token_usage SET
                    input_tokens = ?,
                    output_tokens = ?,
                    total_tokens = ?,
                    estimated_cost_usd = ?,
                    metadata = ?,
                    timestamp = CURRENT_TIMESTAMP
                WHERE session_id = ? AND hook_trigger = ?
            """, (
                token_data['total_input_tokens'],
                token_data['total_output_tokens'],
                total_tokens,
                estimated_cost,
                metadata,
                session_id,
                hook_trigger
            ))
        else:
            # Insert new record
            cursor.execute("""
                INSERT INTO token_usage (
                    session_id, conversation_turn, input_tokens, output_tokens,
                    total_tokens, estimated_cost_usd, model_name, hook_trigger, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                token_data['conversation_turns'],
                token_data['total_input_tokens'],
                token_data['total_output_tokens'],
                total_tokens,
                estimated_cost,
                token_data['model_name'],
                hook_trigger,
                metadata
            ))
        
        conn.commit()
        conn.close()
        
    except Exception:
        pass  # Fail silently - never break the main flow

def main():
    try:
        # Read JSON input from stdin (hook payload)
        input_data = json.load(sys.stdin)
        
        # Extract hook data
        session_id = input_data.get('session_id', f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        transcript_path = input_data.get('transcript_path', '')
        hook_trigger = input_data.get('hook_event_name', 'manual')
        
        # Expand tilde in transcript path
        if transcript_path.startswith('~'):
            transcript_path = os.path.expanduser(transcript_path)
        
        # Set up database path
        project_root = Path.cwd()
        db_path = project_root / '.claude' / 'token_usage.db'
        
        # Ensure .claude directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        init_database(str(db_path))
        
        # Parse transcript for real token data
        token_data = parse_transcript(transcript_path)
        
        # Store the data
        store_token_data(str(db_path), session_id, token_data, hook_trigger)
        
        sys.exit(0)
        
    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Exit cleanly on any other error
        sys.exit(0)

if __name__ == '__main__':
    main()