#!/bin/bash

# Debug Logger for Claude Code Hooks
# Saves all raw JSON hook data for debugging

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/.claude/debug_logs"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Main function - logs all hook data
main() {
    # Read JSON input from stdin (hook payload)
    local json_input=""
    if [[ ! -t 0 ]]; then
        json_input=$(cat)
    fi
    
    # Create timestamp
    local timestamp=$(date +"%Y%m%d_%H%M%S_%3N")
    
    # Extract hook event name for filename
    local hook_event="unknown"
    if [[ -n "$json_input" ]]; then
        hook_event=$(echo "$json_input" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
    fi
    
    # Create log filename
    local log_file="$LOG_DIR/${timestamp}_${hook_event}.json"
    
    # Save the raw JSON with pretty formatting
    if [[ -n "$json_input" ]]; then
        echo "$json_input" | jq '.' > "$log_file" 2>/dev/null || echo "$json_input" > "$log_file"
    else
        echo '{"error": "no_json_input", "timestamp": "'$timestamp'"}' > "$log_file"
    fi
    
    # Also create a summary log with key info
    local summary_file="$LOG_DIR/summary.jsonl"
    if [[ -n "$json_input" ]]; then
        local session_id=$(echo "$json_input" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
        local transcript_path=$(echo "$json_input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
        local tool_name=$(echo "$json_input" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
        
        echo "{\"timestamp\":\"$timestamp\",\"hook_event\":\"$hook_event\",\"session_id\":\"$session_id\",\"tool_name\":\"$tool_name\",\"transcript_path\":\"$transcript_path\",\"log_file\":\"$log_file\"}" >> "$summary_file"
    fi
    
    return 0
}

# Check dependencies - fail silently if not available
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# Run main function - always succeed
main "$@" || exit 0