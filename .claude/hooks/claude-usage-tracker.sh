#!/bin/bash

# Claude Usage Tracker - Standalone Utility (NOT a hook)
# Run this manually or via cron to update token usage across ALL projects

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="$PROJECT_ROOT/.claude/token_usage.db"
CLAUDE_PROJECTS_DIR="$HOME/.claude/projects"

# For current project only - FAST hook-compatible mode
CURRENT_PROJECT_DIR="$HOME/.claude/projects/-Users-toshan-PycharmProjects-stk-v5"

# Initialize database
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

# Quick mode: Track ONLY current project conversations (for hooks)
track_current_project() {
    echo "⚡ Quick mode: Tracking current project only..."
    
    if [[ ! -d "$CURRENT_PROJECT_DIR" ]]; then
        echo "Current project directory not found: $CURRENT_PROJECT_DIR"
        return 1
    fi
    
    local processed=0
    
    # Find most recent transcripts (last 24 hours)
    find "$CURRENT_PROJECT_DIR" -name "*.jsonl" -mtime -1 | while read -r transcript; do
        if [[ -f "$transcript" ]]; then
            local session_id=$(basename "$transcript" .jsonl)
            echo "Processing current project: $session_id"
            # Call simplified parser here
            processed=$((processed + 1))
        fi
    done
    
    echo "✅ Processed $processed current project conversations"
}

# Generate usage report
generate_report() {
    local days="${1:-7}"
    
    echo "=== Claude Code Token Usage Report (Last $days days) ==="
    echo
    
    # Check if database exists
    if [[ ! -f "$DB_PATH" ]]; then
        echo "No usage data found. Run the tracker first."
        return 1
    fi
    
    sqlite3 "$DB_PATH" <<EOF
.headers on
.mode column
.width 12 10 12 12 12 8
SELECT 
    DATE(timestamp) as date,
    COUNT(*) as sessions,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    SUM(total_tokens) as total_tokens,
    ROUND(SUM(estimated_cost_usd), 2) as cost_usd
FROM token_usage 
WHERE timestamp >= datetime('now', '-$days days')
GROUP BY DATE(timestamp)
ORDER BY date DESC;
EOF
    
    echo
    echo "=== Summary (Last $days days) ==="
    sqlite3 "$DB_PATH" <<EOF
SELECT 
    'Total Sessions: ' || COUNT(*)
FROM token_usage 
WHERE timestamp >= datetime('now', '-$days days')
UNION ALL
SELECT 
    'Total Tokens: ' || printf('%,d', SUM(total_tokens))
FROM token_usage 
WHERE timestamp >= datetime('now', '-$days days')
UNION ALL
SELECT 
    'Total Cost: $' || ROUND(SUM(estimated_cost_usd), 2)
FROM token_usage 
WHERE timestamp >= datetime('now', '-$days days');
EOF

    echo
    echo "=== Top Projects by Usage ==="
    sqlite3 "$DB_PATH" <<EOF
.headers on
.mode column
SELECT 
    SUBSTR(metadata, INSTR(metadata, 'project:') + 8, 
           CASE WHEN INSTR(SUBSTR(metadata, INSTR(metadata, 'project:') + 8), ',') > 0 
                THEN INSTR(SUBSTR(metadata, INSTR(metadata, 'project:') + 8), ',') - 1
                ELSE LENGTH(SUBSTR(metadata, INSTR(metadata, 'project:') + 8))
           END) as project,
    COUNT(*) as sessions,
    SUM(total_tokens) as total_tokens,
    ROUND(SUM(estimated_cost_usd), 2) as cost_usd
FROM token_usage 
WHERE timestamp >= datetime('now', '-$days days')
  AND metadata LIKE '%project:%'
GROUP BY project
ORDER BY total_tokens DESC
LIMIT 10;
EOF
}

# Show current session details
show_current_session() {
    # Find most recent transcript
    local recent_transcript=$(find "$CURRENT_PROJECT_DIR" -name "*.jsonl" -mtime -1 | head -1)
    
    if [[ -n "$recent_transcript" ]]; then
        local session_id=$(basename "$recent_transcript" .jsonl)
        echo "Current session: $session_id"
        
        sqlite3 "$DB_PATH" <<EOF
.headers on
.mode column
SELECT 
    session_id,
    input_tokens,
    output_tokens, 
    total_tokens,
    estimated_cost_usd,
    timestamp
FROM token_usage 
WHERE session_id = '$session_id'
ORDER BY timestamp DESC
LIMIT 1;
EOF
    else
        echo "No recent sessions found"
    fi
}

# Main function
main() {
    local action="${1:-help}"
    
    init_database 2>/dev/null
    
    case "$action" in
        "quick")
            track_current_project
            ;;
        "report")
            generate_report "${2:-7}"
            ;;
        "current")
            show_current_session
            ;;
        "help"|*)
            echo "Claude Usage Tracker - Standalone Utility"
            echo
            echo "Usage: $0 <command> [options]"
            echo
            echo "Commands:"
            echo "  quick           - Track current project only (FAST, hook-friendly)"
            echo "  report [days]   - Generate usage report (default: 7 days)"
            echo "  current         - Show current session details"
            echo "  help            - Show this help"
            echo
            echo "Examples:"
            echo "  $0 quick         # Quick update for hooks"
            echo "  $0 report 30     # 30-day usage report"
            echo "  $0 current       # Current session info"
            ;;
    esac
}

# Run main function
main "$@"