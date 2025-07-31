#!/bin/bash

# Custom Token Usage Tracker for Claude Code
# Uses our own token counting instead of Claude's broken reporting

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"

# Token estimation constants (based on GPT/Claude tokenization patterns)
# These are more accurate than Claude's broken usage reporting
CHARS_PER_TOKEN=3.5   # More aggressive than 4, accounts for punctuation
WORDS_TO_TOKENS_RATIO=1.3  # 1.3 tokens per word average

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

# Custom token counting function
count_tokens() {
    local text="$1"
    
    if [[ -z "$text" ]]; then
        echo "0"
        return
    fi
    
    # Remove the text from quotes and normalize
    text=$(echo "$text" | sed 's/^"//; s/"$//')
    
    # Count characters and words
    local char_count=${#text}
    local word_count=$(echo "$text" | wc -w | tr -d ' ')
    
    # Two estimation methods (ensure integer results)
    local char_based_tokens=$(echo "scale=0; ($char_count / $CHARS_PER_TOKEN) + 0.5" | bc -l | cut -d. -f1)
    local word_based_tokens=$(echo "scale=0; ($word_count * $WORDS_TO_TOKENS_RATIO) + 0.5" | bc -l | cut -d. -f1)
    
    # Use the higher estimate for safety (tokens tend to be under-estimated)
    if [[ "$char_based_tokens" -gt "$word_based_tokens" ]]; then
        echo "$char_based_tokens"
    else
        echo "$word_based_tokens"
    fi
}

# Parse JSONL transcript file to extract content and count tokens ourselves
parse_transcript_custom() {
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
    
    # Read JSONL file line by line and count tokens from actual content
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            # Skip summary entries, only process message entries
            local entry_type=$(echo "$line" | jq -r '.type // ""' 2>/dev/null)
            if [[ "$entry_type" != "assistant" && "$entry_type" != "user" ]]; then
                continue
            fi
            
            conversation_turn=$((conversation_turn + 1))
            
            # Extract model name from message.model
            local line_model=$(echo "$line" | jq -r '.message.model // "claude-sonnet-4"' 2>/dev/null || echo "claude-sonnet-4")
            if [[ "$line_model" != "null" && "$line_model" != "claude-sonnet-4" ]]; then
                model_name="$line_model"
            fi
            
            # Extract role to determine if input or output
            local role=$(echo "$line" | jq -r '.message.role // ""' 2>/dev/null)
            
            # Extract content based on role
            local content=""
            if [[ "$role" == "user" ]]; then
                # User messages: content is a string
                content=$(echo "$line" | jq -r '.message.content // ""' 2>/dev/null)
                local tokens=$(count_tokens "$content")
                total_input_tokens=$((total_input_tokens + tokens))
            elif [[ "$role" == "assistant" ]]; then
                # Assistant messages: content is array, get first text element
                content=$(echo "$line" | jq -r '.message.content[0].text // ""' 2>/dev/null)
                local tokens=$(count_tokens "$content")
                total_output_tokens=$((total_output_tokens + tokens))
            fi
        fi
    done < "$transcript_path"
    
    local total_tokens=$((total_input_tokens + total_output_tokens))
    local estimated_cost=$(calculate_cost "$total_input_tokens" "$total_output_tokens")
    
    # Store the custom token data
    store_token_data "$session_id" "$total_input_tokens" "$total_output_tokens" "$total_tokens" "$estimated_cost" "$hook_trigger" "custom_count:turns:$conversation_turn,model:$model_name"
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
    
    # Parse the transcript with custom token counting
    if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
        parse_transcript_custom "$transcript_path" "$session_id" "$hook_trigger"
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