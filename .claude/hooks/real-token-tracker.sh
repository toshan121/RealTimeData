#!/bin/bash

# Real Token Usage Tracker for Claude Code
# Reads actual token counts from JSONL transcript files

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"

# Initialize SQLite database
init_database() {
    sqlite3 "$DB_PATH" <<EOF
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
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON token_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_session ON token_usage(session_id);
EOF
}

# Calculate cost estimate (Claude Sonnet 4 pricing)
calculate_cost() {
    local input_tokens="$1"
    local output_tokens="$2"
    
    # Current Claude Sonnet 4 pricing (per 1K tokens)
    local input_cost_per_1k=0.015   # $0.015 per 1K input tokens
    local output_cost_per_1k=0.075  # $0.075 per 1K output tokens
    
    local input_cost=$(echo "scale=6; $input_tokens * $input_cost_per_1k / 1000" | bc -l)
    local output_cost=$(echo "scale=6; $output_tokens * $output_cost_per_1k / 1000" | bc -l)
    local total_cost=$(echo "scale=6; $input_cost + $output_cost" | bc -l)
    
    echo "$total_cost"
}

# Parse JSONL transcript file to extract real token counts
parse_transcript() {
    local transcript_path="$1"
    local session_id="$2"
    local hook_trigger="$3"
    
    if [[ ! -f "$transcript_path" ]]; then
        # Fallback: create minimal record
        store_token_data "$session_id" 0 0 0 0.0 "$hook_trigger" "no_transcript"
        return 0
    fi
    
    local total_input_tokens=0
    local total_output_tokens=0
    local conversation_turn=0
    local model_name="claude-sonnet-4"
    
    # Read JSONL file line by line and extract token usage
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            conversation_turn=$((conversation_turn + 1))
            
            # Extract model name from message.model or top level model
            local line_model=$(echo "$line" | jq -r '.message.model // .model // "claude-sonnet-4"' 2>/dev/null || echo "claude-sonnet-4")
            if [[ "$line_model" != "null" && "$line_model" != "claude-sonnet-4" ]]; then
                model_name="$line_model"
            fi
            
            # Extract input tokens from message.usage structure (including cache tokens)
            local input_tokens=$(echo "$line" | jq '(.message.usage.input_tokens // 0) + (.message.usage.cache_creation_input_tokens // 0) + (.message.usage.cache_read_input_tokens // 0)' 2>/dev/null || echo "0")
            
            # Extract output tokens from message.usage structure
            local output_tokens=$(echo "$line" | jq '.message.usage.output_tokens // 0' 2>/dev/null || echo "0")
            
            # Accumulate totals
            total_input_tokens=$((total_input_tokens + input_tokens))
            total_output_tokens=$((total_output_tokens + output_tokens))
        fi
    done < "$transcript_path"
    
    local total_tokens=$((total_input_tokens + total_output_tokens))
    local estimated_cost=$(calculate_cost "$total_input_tokens" "$total_output_tokens")
    
    # Store the real token data
    store_token_data "$session_id" "$total_input_tokens" "$total_output_tokens" "$total_tokens" "$estimated_cost" "$hook_trigger" "turns:$conversation_turn,model:$model_name"
}

# Store token data with robust error handling
store_token_data() {
    local session_id="$1"
    local input_tokens="$2"
    local output_tokens="$3"
    local total_tokens="$4"
    local estimated_cost="$5"
    local hook_trigger="$6"
    local metadata="$7"
    
    # Check if this session already exists to avoid duplicates
    local existing_count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM token_usage WHERE session_id = '$session_id' AND hook_trigger = '$hook_trigger';" 2>/dev/null || echo "0")
    
    if [[ "$existing_count" -gt 0 ]]; then
        # Update existing record instead of creating duplicate
        sqlite3 "$DB_PATH" "UPDATE token_usage SET 
            input_tokens = $input_tokens,
            output_tokens = $output_tokens,
            total_tokens = $total_tokens,
            estimated_cost_usd = $estimated_cost,
            metadata = '$metadata',
            timestamp = CURRENT_TIMESTAMP
            WHERE session_id = '$session_id' AND hook_trigger = '$hook_trigger';" 2>/dev/null || true
    else
        # Insert new record
        sqlite3 "$DB_PATH" "INSERT INTO token_usage (
            session_id, conversation_turn, input_tokens, output_tokens, 
            total_tokens, estimated_cost_usd, hook_trigger, metadata
        ) VALUES (
            '$session_id', 1, $input_tokens, $output_tokens,
            $total_tokens, $estimated_cost, '$hook_trigger', '$metadata'
        );" 2>/dev/null || true
    fi
}

# Main function - processes hook JSON input from stdin
main() {
    # Initialize database silently
    init_database 2>/dev/null || return 0
    
    # Read JSON input from stdin (hook payload)
    local json_input=""
    if [[ ! -t 0 ]]; then
        json_input=$(cat)
    fi
    
    # Extract hook data
    local session_id=""
    local transcript_path=""
    local hook_trigger=""
    
    if [[ -n "$json_input" ]]; then
        session_id=$(echo "$json_input" | jq -r '.session_id // ""' 2>/dev/null || echo "")
        transcript_path=$(echo "$json_input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
        hook_trigger=$(echo "$json_input" | jq -r '.hook_event_name // "manual"' 2>/dev/null || echo "manual")
    fi
    
    # Fallback if no JSON input (manual execution)
    if [[ -z "$session_id" ]]; then
        session_id="manual_$(date +%Y%m%d_%H%M%S)"
        hook_trigger="${1:-manual}"
    fi
    
    # Expand tilde in transcript path
    if [[ "$transcript_path" =~ ^~ ]]; then
        transcript_path="${transcript_path/#\~/$HOME}"
    fi
    
    # Parse the actual transcript file
    if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
        parse_transcript "$transcript_path" "$session_id" "$hook_trigger"
    else
        # No transcript available, create minimal record
        store_token_data "$session_id" 0 0 0 0.0 "$hook_trigger" "no_transcript"
    fi
    
    return 0
}

# Check dependencies
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # Silently skip if jq not available
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
    exit 0  # Silently skip if sqlite3 not available
fi

if ! command -v bc >/dev/null 2>&1; then
    exit 0  # Silently skip if bc not available
fi

# Run main function
main "$@" || exit 0