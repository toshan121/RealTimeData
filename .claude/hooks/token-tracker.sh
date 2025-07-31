#!/bin/bash

# Token Usage Tracker for Claude Code
# Calculates input/output tokens and stores in SQLite database

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"

# Token estimation constants (rough approximation based on GPT-4 tokenizer)
# These are estimates - Claude's actual tokenizer may differ slightly
AVG_CHARS_PER_TOKEN=4
AVG_WORDS_PER_TOKEN=0.75

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

# Estimate token count from text
estimate_tokens() {
    local text="$1"
    local char_count=${#text}
    local word_count=$(echo "$text" | wc -w | tr -d ' ')
    
    # Use the more conservative estimate between char-based and word-based
    local char_tokens=$((char_count / AVG_CHARS_PER_TOKEN))
    local word_tokens=$((word_count * 100 / 75))  # 0.75 words per token = 75/100
    
    # Return the higher estimate for safety
    if [ "$char_tokens" -gt "$word_tokens" ]; then
        echo "$char_tokens"
    else
        echo "$word_tokens"
    fi
}

# Calculate cost estimate (Claude Sonnet 4 pricing - adjust as needed)
calculate_cost() {
    local input_tokens="$1"
    local output_tokens="$2"
    
    # Estimated pricing (per 1K tokens) - adjust based on actual Claude pricing
    local input_cost_per_1k=0.015   # $0.015 per 1K input tokens
    local output_cost_per_1k=0.075  # $0.075 per 1K output tokens
    
    local input_cost=$(echo "scale=6; $input_tokens * $input_cost_per_1k / 1000" | bc -l)
    local output_cost=$(echo "scale=6; $output_tokens * $output_cost_per_1k / 1000" | bc -l)
    local total_cost=$(echo "scale=6; $input_cost + $output_cost" | bc -l)
    
    echo "$total_cost"
}

# Extract conversation data - purely programmatic, no LLM calls
extract_conversation_data() {
    local hook_trigger="${1:-manual}"
    
    # Count files changed as proxy for conversation complexity
    local files_changed=0
    local total_lines=0
    
    # Count git diff stats (programmatic only)
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        # Count changed files
        files_changed=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
        if [ "$files_changed" -eq 0 ]; then
            files_changed=$(git diff HEAD~1 --name-only 2>/dev/null | wc -l | tr -d ' ')
        fi
        
        # Count total lines changed (adds + deletes)
        total_lines=$(git diff --cached --numstat 2>/dev/null | awk '{sum+=$1+$2} END {print sum+0}')
        if [ "$total_lines" -eq 0 ]; then
            total_lines=$(git diff HEAD~1 --numstat 2>/dev/null | awk '{sum+=$1+$2} END {print sum+0}')
        fi
    fi
    
    # Estimate tokens based on actual file changes (no LLM needed)
    estimate_from_file_changes "$hook_trigger" "$files_changed" "$total_lines"
}

# Estimate tokens from file changes (completely programmatic)
estimate_from_file_changes() {
    local hook_trigger="$1"
    local files_changed="$2"
    local lines_changed="$3"
    local session_id=$(date +%Y%m%d_%H%M%S)
    
    # Simple heuristic: lines changed * 10 tokens per line average
    local base_tokens=$((lines_changed * 10))
    
    # Add complexity factor based on files changed
    local complexity_factor=$((files_changed * 50))
    
    # Estimate input tokens (context + request)
    local input_tokens=$((base_tokens + complexity_factor + 200))  # +200 for base conversation
    
    # Estimate output tokens (typically 20-40% of input for code tasks)
    local output_tokens=$((input_tokens * 25 / 100))
    
    # Cap at reasonable maximums to avoid wild estimates
    if [ "$input_tokens" -gt 50000 ]; then input_tokens=50000; fi
    if [ "$output_tokens" -gt 20000 ]; then output_tokens=20000; fi
    
    local total_tokens=$((input_tokens + output_tokens))
    local estimated_cost=$(calculate_cost "$input_tokens" "$output_tokens")
    
    # Store in database with retries and error handling
    store_token_data "$session_id" "$input_tokens" "$output_tokens" "$total_tokens" "$estimated_cost" "$hook_trigger" "files:$files_changed,lines:$lines_changed"
}

# Store token data with robust error handling - never break main flow
store_token_data() {
    local session_id="$1"
    local input_tokens="$2"
    local output_tokens="$3"
    local total_tokens="$4"
    local estimated_cost="$5"
    local hook_trigger="$6"
    local metadata="$7"
    
    # Retry function with exponential backoff
    local max_retries=3
    local retry_count=0
    local base_delay=1
    
    while [ $retry_count -lt $max_retries ]; do
        if sqlite3 "$DB_PATH" "INSERT INTO token_usage (
            session_id, conversation_turn, input_tokens, output_tokens, 
            total_tokens, estimated_cost_usd, hook_trigger, metadata
        ) VALUES (
            '$session_id', 1, $input_tokens, $output_tokens,
            $total_tokens, $estimated_cost, '$hook_trigger', '$metadata'
        );" 2>/dev/null; then
            # Success - exit quietly
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $max_retries ]; then
            # Wait with exponential backoff, but don't block long
            sleep $((base_delay * retry_count))
        fi
    done
    
    # Final fallback - try to recreate database and store
    if ! init_database 2>/dev/null; then
        # If all fails, silently continue - don't break main flow
        return 0
    fi
    
    # One last attempt
    sqlite3 "$DB_PATH" "INSERT INTO token_usage (
        session_id, conversation_turn, input_tokens, output_tokens, 
        total_tokens, estimated_cost_usd, hook_trigger, metadata
    ) VALUES (
        '$session_id', 1, $input_tokens, $output_tokens,
        $total_tokens, $estimated_cost, '$hook_trigger', '$metadata'
    );" 2>/dev/null || true  # Never fail
}

# Parse actual Claude conversation log file
parse_log_file() {
    local log_file="$1"
    local hook_trigger="$2"
    
    # For now, fall back to programmatic estimation
    # Could be enhanced later to parse actual log formats
    estimate_from_file_changes "$hook_trigger" "1" "50"  # Default values
}

# Generate usage report
generate_report() {
    local time_period="${1:-7}"  # days
    
    echo "=== Claude Code Token Usage Report (Last $time_period days) ==="
    echo
    
    sqlite3 "$DB_PATH" <<EOF
.headers on
.mode column
SELECT 
    DATE(timestamp) as date,
    COUNT(*) as sessions,
    SUM(input_tokens) as total_input,
    SUM(output_tokens) as total_output,
    SUM(total_tokens) as total_tokens,
    ROUND(SUM(estimated_cost_usd), 4) as cost_usd
FROM token_usage 
WHERE timestamp >= datetime('now', '-$time_period days')
GROUP BY DATE(timestamp)
ORDER BY date DESC;
EOF
    
    echo
    echo "=== Summary ==="
    sqlite3 "$DB_PATH" <<EOF
SELECT 
    'Total Sessions: ' || COUNT(*) as summary
FROM token_usage 
WHERE timestamp >= datetime('now', '-$time_period days')
UNION ALL
SELECT 
    'Total Tokens: ' || SUM(total_tokens)
FROM token_usage 
WHERE timestamp >= datetime('now', '-$time_period days')
UNION ALL
SELECT 
    'Estimated Cost: $' || ROUND(SUM(estimated_cost_usd), 2)
FROM token_usage 
WHERE timestamp >= datetime('now', '-$time_period days');
EOF
}

# Main function - never fails, always exits 0
main() {
    local action="${1:-track}"
    
    # Silently ensure database exists - don't break if it fails
    init_database 2>/dev/null || return 0
    
    case "$action" in
        "track")
            extract_conversation_data "${2:-hook}" 2>/dev/null || true
            ;;
        "report")
            generate_report "${2:-7}" 2>/dev/null || true
            ;;
        "init")
            if init_database; then
                echo "Database initialized at: $DB_PATH"
            fi
            ;;
        *)
            echo "Usage: $0 {track|report|init} [args]"
            echo "  track [trigger]  - Track current conversation tokens"
            echo "  report [days]    - Generate usage report (default: 7 days)"
            echo "  init            - Initialize database"
            return 0  # Don't exit 1 - just return
            ;;
    esac
    
    return 0  # Always succeed
}

# Check dependencies - fail silently if not available
if ! command -v sqlite3 >/dev/null 2>&1; then
    exit 0  # Silently skip if sqlite3 not available
fi

if ! command -v bc >/dev/null 2>&1; then
    exit 0  # Silently skip if bc not available
fi

# Run main function - always succeed
main "$@" || exit 0