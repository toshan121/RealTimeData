#!/bin/bash

# Smart Transcript Monitor for Claude Code
# Only processes NEW or RECENTLY MODIFIED transcripts for efficiency

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"
CLAUDE_PROJECTS_DIR="$HOME/.claude/projects"
LAST_RUN_FILE="$PROJECT_ROOT/.claude/last_monitor_run"

# Token estimation constants
CHARS_PER_TOKEN=3.5
WORDS_TO_TOKENS_RATIO=1.3

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

# Custom token counting function
count_tokens() {
    local text="$1"
    
    if [[ -z "$text" ]]; then
        echo "0"
        return
    fi
    
    # Remove quotes and normalize
    text=$(echo "$text" | sed 's/^"//; s/"$//')
    
    local char_count=${#text}
    local word_count=$(echo "$text" | wc -w | tr -d ' ')
    
    # Two estimation methods
    local char_based_tokens=$(echo "scale=0; ($char_count / $CHARS_PER_TOKEN) + 0.5" | bc -l | cut -d. -f1)
    local word_based_tokens=$(echo "scale=0; ($word_count * $WORDS_TO_TOKENS_RATIO) + 0.5" | bc -l | cut -d. -f1)
    
    # Use higher estimate
    if [[ "$char_based_tokens" -gt "$word_based_tokens" ]]; then
        echo "$char_based_tokens"
    else
        echo "$word_based_tokens"
    fi
}

# Check if session already exists in database
session_exists() {
    local session_id="$1"
    local count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM token_usage WHERE session_id = '$session_id' AND hook_trigger = 'transcript_monitor';" 2>/dev/null || echo "0")
    [[ "$count" -gt 0 ]]
}

# Parse single transcript file and update database
parse_transcript() {
    local transcript_path="$1"
    local session_id=$(basename "$transcript_path" .jsonl)
    local project_name=$(basename "$(dirname "$transcript_path")")
    
    if [[ ! -f "$transcript_path" ]]; then
        return 0
    fi
    
    local total_input_tokens=0
    local total_output_tokens=0
    local conversation_turn=0
    local model_name="claude-sonnet-4"
    
    # Parse the transcript file
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            # Skip summary entries
            local entry_type=$(echo "$line" | jq -r '.type // ""' 2>/dev/null)
            if [[ "$entry_type" != "assistant" && "$entry_type" != "user" ]]; then
                continue
            fi
            
            conversation_turn=$((conversation_turn + 1))
            
            # Extract model name
            local line_model=$(echo "$line" | jq -r '.message.model // "claude-sonnet-4"' 2>/dev/null || echo "claude-sonnet-4")
            if [[ "$line_model" != "null" && "$line_model" != "claude-sonnet-4" ]]; then
                model_name="$line_model"
            fi
            
            # Extract role and content
            local role=$(echo "$line" | jq -r '.message.role // ""' 2>/dev/null)
            local content=""
            
            if [[ "$role" == "user" ]]; then
                content=$(echo "$line" | jq -r '.message.content // ""' 2>/dev/null)
                local tokens=$(count_tokens "$content")
                total_input_tokens=$((total_input_tokens + tokens))
            elif [[ "$role" == "assistant" ]]; then
                content=$(echo "$line" | jq -r '.message.content[0].text // ""' 2>/dev/null)
                local tokens=$(count_tokens "$content")
                total_output_tokens=$((total_output_tokens + tokens))
            fi
        fi
    done < "$transcript_path"
    
    local total_tokens=$((total_input_tokens + total_output_tokens))
    local estimated_cost=$(calculate_cost "$total_input_tokens" "$total_output_tokens")
    
    # Update or insert record for this session
    update_session_record "$session_id" "$total_input_tokens" "$total_output_tokens" "$total_tokens" "$estimated_cost" "transcript_monitor" "project:$project_name,turns:$conversation_turn,model:$model_name"
}

# Update database record for a session
update_session_record() {
    local session_id="$1"
    local input_tokens="$2"
    local output_tokens="$3"
    local total_tokens="$4"
    local estimated_cost="$5"
    local hook_trigger="$6"
    local metadata="$7"
    
    # Check if session exists
    local existing_count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM token_usage WHERE session_id = '$session_id' AND hook_trigger = '$hook_trigger';" 2>/dev/null || echo "0")
    
    if [[ "$existing_count" -gt 0 ]]; then
        # Update existing record
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

# Smart monitoring: only process NEW or MODIFIED files
monitor_transcripts_smart() {
    if [[ ! -d "$CLAUDE_PROJECTS_DIR" ]]; then
        echo "Claude projects directory not found: $CLAUDE_PROJECTS_DIR"
        return 1
    fi
    
    # Get timestamp of last run (default to 1 hour ago if no previous run)
    local last_run_timestamp
    if [[ -f "$LAST_RUN_FILE" ]]; then
        last_run_timestamp=$(cat "$LAST_RUN_FILE")
    else
        last_run_timestamp=$(date -d "1 hour ago" +%s 2>/dev/null || date -v-1H +%s)
    fi
    
    echo "🔍 Scanning for NEW/MODIFIED Claude conversations since last run..."
    
    local total_found=0
    local processed=0
    local skipped=0
    
    # Find transcript files modified since last run
    while IFS= read -r -d '' transcript; do
        if [[ -f "$transcript" ]]; then
            local file_mod_time=$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript" 2>/dev/null)
            local session_id=$(basename "$transcript" .jsonl)
            local project_name=$(basename "$(dirname "$transcript")")
            
            total_found=$((total_found + 1))
            
            # Process if file is newer than last run OR not in database
            if [[ "$file_mod_time" -gt "$last_run_timestamp" ]] || ! session_exists "$session_id"; then
                echo "[$processed] Processing: $project_name/$session_id"
                parse_transcript "$transcript"
                processed=$((processed + 1))
            else
                skipped=$((skipped + 1))
            fi
        fi
    done < <(find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" -type f -print0)
    
    # Record this run timestamp
    date +%s > "$LAST_RUN_FILE"
    
    echo "✅ Smart scan complete!"
    echo "📊 Found: $total_found total conversations"
    echo "📈 Processed: $processed new/modified conversations"
    echo "⚡ Skipped: $skipped unchanged conversations"
}

# Monitor recent conversations (last N hours)
monitor_recent() {
    local hours="${1:-2}"  # Default: last 2 hours
    
    echo "🕐 Scanning conversations from last $hours hours..."
    
    local processed=0
    local cutoff_time=$(date -d "$hours hours ago" +%s 2>/dev/null || date -v-${hours}H +%s)
    
    while IFS= read -r -d '' transcript; do
        if [[ -f "$transcript" ]]; then
            local file_mod_time=$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript" 2>/dev/null)
            
            if [[ "$file_mod_time" -gt "$cutoff_time" ]]; then
                local session_id=$(basename "$transcript" .jsonl)
                local project_name=$(basename "$(dirname "$transcript")")
                echo "Processing recent: $project_name/$session_id"
                parse_transcript "$transcript"
                processed=$((processed + 1))
            fi
        fi
    done < <(find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" -type f -print0)
    
    echo "✅ Processed $processed recent conversations"
}

# Main function
main() {
    local action="${1:-smart}"
    
    # Initialize database
    init_database 2>/dev/null || return 0
    
    case "$action" in
        "smart")
            monitor_transcripts_smart
            ;;
        "recent")
            monitor_recent "${2:-2}"
            ;;
        "single")
            if [[ -n "${2:-}" ]]; then
                parse_transcript "$2"
            else
                echo "Usage: $0 single <transcript_path>"
                return 1
            fi
            ;;
        *)
            echo "Usage: $0 {smart|recent [hours]|single <path>}"
            echo "  smart     - Only process NEW/MODIFIED transcripts (FAST)"
            echo "  recent    - Process transcripts from last N hours (default: 2)"
            echo "  single    - Process specific transcript file"
            return 1
            ;;
    esac
}

# Check dependencies
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required but not installed"
    exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "Error: sqlite3 is required but not installed"
    exit 1
fi

if ! command -v bc >/dev/null 2>&1; then
    echo "Error: bc is required but not installed"
    exit 1
fi

# Run main function
main "$@"