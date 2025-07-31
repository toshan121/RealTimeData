#!/bin/bash

# Current Conversation Tracker
# FAST tracker that only processes the current session/conversation
# Designed for hook usage - lightweight and quick

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"

# Token estimation constants
CHARS_PER_TOKEN=3.5
WORDS_TO_TOKENS_RATIO=1.3

# Initialize SQLite database (lightweight)
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

# Calculate cost estimate
calculate_cost() {
    local input_tokens="$1"
    local output_tokens="$2"
    
    local input_cost_per_1k=0.003   # $3.00 per 1M tokens = $0.003 per 1K tokens
    local output_cost_per_1k=0.015  # $15.00 per 1M tokens = $0.015 per 1K tokens
    
    local input_cost=$(echo "scale=6; $input_tokens * $input_cost_per_1k / 1000" | bc -l)
    local output_cost=$(echo "scale=6; $output_tokens * $output_cost_per_1k / 1000" | bc -l)
    local total_cost=$(echo "scale=6; $input_cost + $output_cost" | bc -l)
    
    echo "$total_cost"
}

# Fast token counting function
count_tokens_fast() {
    local text="$1"
    
    if [[ -z "$text" ]]; then
        echo "0"
        return
    fi
    
    # Remove quotes and get word count (fastest method)
    local word_count=$(echo "$text" | sed 's/^"//; s/"$//' | wc -w | tr -d ' ')
    
    # Simple estimation: words * 1.3
    local tokens=$(echo "scale=0; ($word_count * $WORDS_TO_TOKENS_RATIO) + 0.5" | bc -l | cut -d. -f1)
    
    echo "$tokens"
}

# Fast parser for CURRENT conversation only
parse_current_conversation() {
    local transcript_path="$1"
    local session_id="$2"
    
    if [[ ! -f "$transcript_path" ]]; then
        return 0
    fi
    
    local total_input_tokens=0
    local total_output_tokens=0
    local conversation_turn=0
    local model_name="claude-sonnet-4"
    
    # Fast parsing - only read last 50 lines for speed (recent activity)
    tail -50 "$transcript_path" | while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            # Quick check for message entries
            if echo "$line" | grep -q '"type":"assistant"\|"type":"user"'; then
                conversation_turn=$((conversation_turn + 1))
                
                # Extract role quickly
                if echo "$line" | grep -q '"role":"user"'; then
                    # User message
                    local content=$(echo "$line" | jq -r '.message.content // ""' 2>/dev/null)
                    if [[ -n "$content" && "$content" != "null" ]]; then
                        local tokens=$(count_tokens_fast "$content")
                        total_input_tokens=$((total_input_tokens + tokens))
                    fi
                elif echo "$line" | grep -q '"role":"assistant"'; then
                    # Assistant message
                    local content=$(echo "$line" | jq -r '.message.content[0].text // ""' 2>/dev/null)
                    if [[ -n "$content" && "$content" != "null" ]]; then
                        local tokens=$(count_tokens_fast "$content")
                        total_output_tokens=$((total_output_tokens + tokens))
                    fi
                    
                    # Extract model name
                    local line_model=$(echo "$line" | jq -r '.message.model // ""' 2>/dev/null)
                    if [[ -n "$line_model" && "$line_model" != "null" && "$line_model" != "claude-sonnet-4" ]]; then
                        model_name="$line_model"
                    fi
                fi
            fi
        fi
    done
    
    # For efficiency, we'll re-parse the whole file if this is a significant conversation
    # But only if we detected activity in the tail
    if [[ "$conversation_turn" -gt 10 ]]; then
        # Reset and do full parse
        total_input_tokens=0
        total_output_tokens=0
        conversation_turn=0
        
        while IFS= read -r line; do
            if [[ -n "$line" ]]; then
                if echo "$line" | grep -q '"type":"assistant"\|"type":"user"'; then
                    conversation_turn=$((conversation_turn + 1))
                    
                    if echo "$line" | grep -q '"role":"user"'; then
                        local content=$(echo "$line" | jq -r '.message.content // ""' 2>/dev/null)
                        if [[ -n "$content" && "$content" != "null" ]]; then
                            local tokens=$(count_tokens_fast "$content")
                            total_input_tokens=$((total_input_tokens + tokens))
                        fi
                    elif echo "$line" | grep -q '"role":"assistant"'; then
                        local content=$(echo "$line" | jq -r '.message.content[0].text // ""' 2>/dev/null)
                        if [[ -n "$content" && "$content" != "null" ]]; then
                            local tokens=$(count_tokens_fast "$content")
                            total_output_tokens=$((total_output_tokens + tokens))
                        fi
                    fi
                fi
            fi
        done < "$transcript_path"
    fi
    
    local total_tokens=$((total_input_tokens + total_output_tokens))
    local estimated_cost=$(calculate_cost "$total_input_tokens" "$total_output_tokens")
    
    # Update database record
    update_current_session "$session_id" "$total_input_tokens" "$total_output_tokens" "$total_tokens" "$estimated_cost" "$conversation_turn" "$model_name"
}

# Update database for current session
update_current_session() {
    local session_id="$1"
    local input_tokens="$2"
    local output_tokens="$3"
    local total_tokens="$4"
    local estimated_cost="$5"
    local conversation_turn="$6"
    local model_name="$7"
    
    # Check if session exists
    local existing_count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM token_usage WHERE session_id = '$session_id' AND hook_trigger = 'current_conversation';" 2>/dev/null || echo "0")
    
    if [[ "$existing_count" -gt 0 ]]; then
        # Update existing record
        sqlite3 "$DB_PATH" "UPDATE token_usage SET 
            input_tokens = $input_tokens,
            output_tokens = $output_tokens,
            total_tokens = $total_tokens,
            estimated_cost_usd = $estimated_cost,
            conversation_turn = $conversation_turn,
            model_name = '$model_name',
            metadata = 'turns:$conversation_turn,model:$model_name,source:current_hook',
            timestamp = CURRENT_TIMESTAMP
            WHERE session_id = '$session_id' AND hook_trigger = 'current_conversation';" 2>/dev/null || true
    else
        # Insert new record
        sqlite3 "$DB_PATH" "INSERT INTO token_usage (
            session_id, conversation_turn, input_tokens, output_tokens, 
            total_tokens, estimated_cost_usd, model_name, hook_trigger, metadata
        ) VALUES (
            '$session_id', $conversation_turn, $input_tokens, $output_tokens,
            $total_tokens, $estimated_cost, '$model_name', 'current_conversation', 
            'turns:$conversation_turn,model:$model_name,source:current_hook'
        );" 2>/dev/null || true
    fi
}

# Main function - designed for hook usage
main() {
    # Initialize database silently and quickly
    init_database 2>/dev/null || return 0
    
    # Read JSON input from stdin (hook payload)
    local json_input=""
    if [[ ! -t 0 ]]; then
        json_input=$(cat)
    fi
    
    # Extract session info
    local session_id=""
    local transcript_path=""
    
    if [[ -n "$json_input" ]]; then
        session_id=$(echo "$json_input" | jq -r '.session_id // ""' 2>/dev/null || echo "")
        transcript_path=$(echo "$json_input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
    fi
    
    # Skip if no valid session data
    if [[ -z "$session_id" || -z "$transcript_path" ]]; then
        return 0
    fi
    
    # Expand tilde in transcript path
    if [[ "$transcript_path" =~ ^~ ]]; then
        transcript_path="${transcript_path/#\~/$HOME}"
    fi
    
    # Parse current conversation only
    if [[ -f "$transcript_path" ]]; then
        parse_current_conversation "$transcript_path" "$session_id"
    fi
    
    return 0
}

# Check dependencies (minimal check for speed)
if ! command -v jq >/dev/null 2>&1 || ! command -v sqlite3 >/dev/null 2>&1 || ! command -v bc >/dev/null 2>&1; then
    exit 0
fi

# Run main function - always succeed for hook compatibility
main "$@" || exit 0