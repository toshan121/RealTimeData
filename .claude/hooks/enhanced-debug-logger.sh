#!/bin/bash

# Enhanced Debug Logger for Claude Code Hooks
# Provides detailed analysis of ALL hook event types with data structure inspection

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/.claude/debug_logs"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Analyze hook data and extract detailed information
analyze_hook_data() {
    local json_input="$1"
    local hook_event="$2"
    
    case "$hook_event" in
        "PreToolUse")
            local tool_name=$(echo "$json_input" | jq -r '.tool_name // "unknown"' 2>/dev/null)
            local tool_input_keys=$(echo "$json_input" | jq -r '.tool_input | keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            local command_preview=""
            if [[ "$tool_name" == "Bash" ]]; then
                command_preview=$(echo "$json_input" | jq -r '.tool_input.command // ""' 2>/dev/null | head -c 50)
            fi
            echo "PreToolUse - Tool: $tool_name, Input keys: [$tool_input_keys], Command: $command_preview"
            ;;
        "PostToolUse")
            local tool_name=$(echo "$json_input" | jq -r '.tool_name // "unknown"' 2>/dev/null)
            local tool_response_keys=$(echo "$json_input" | jq -r '.tool_response | keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            local success=$(echo "$json_input" | jq -r '.tool_response.success // "unknown"' 2>/dev/null)
            local has_error=$(echo "$json_input" | jq -r '.tool_response.error // "none"' 2>/dev/null)
            echo "PostToolUse - Tool: $tool_name, Success: $success, Error: $has_error, Response keys: [$tool_response_keys]"
            ;;
        "Stop")
            local stop_hook_active=$(echo "$json_input" | jq -r '.stop_hook_active // "unknown"' 2>/dev/null)
            local all_keys=$(echo "$json_input" | jq -r 'keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            echo "Stop - Hook active: $stop_hook_active, All keys: [$all_keys]"
            ;;
        "SubagentStop")
            local stop_hook_active=$(echo "$json_input" | jq -r '.stop_hook_active // "unknown"' 2>/dev/null)
            local all_keys=$(echo "$json_input" | jq -r 'keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            echo "SubagentStop - Hook active: $stop_hook_active, All keys: [$all_keys]"
            ;;
        "Notification")
            local message=$(echo "$json_input" | jq -r '.message // "unknown"' 2>/dev/null | head -c 100)
            local title=$(echo "$json_input" | jq -r '.title // "unknown"' 2>/dev/null)
            local all_keys=$(echo "$json_input" | jq -r 'keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            echo "Notification - Title: $title, Message: $message, All keys: [$all_keys]"
            ;;
        *)
            local all_keys=$(echo "$json_input" | jq -r 'keys[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo "none")
            echo "Unknown event: $hook_event, All keys: [$all_keys]"
            ;;
    esac
}

# Extract key statistics from JSON
extract_stats() {
    local json_input="$1"
    
    echo "=== JSON STRUCTURE ANALYSIS ==="
    echo "Total keys: $(echo "$json_input" | jq 'keys | length' 2>/dev/null || echo "0")"
    echo "Session ID present: $(echo "$json_input" | jq 'has("session_id")' 2>/dev/null || echo "false")"
    echo "Transcript path present: $(echo "$json_input" | jq 'has("transcript_path")' 2>/dev/null || echo "false")"
    echo "Tool name present: $(echo "$json_input" | jq 'has("tool_name")' 2>/dev/null || echo "false")"
    echo "Tool input present: $(echo "$json_input" | jq 'has("tool_input")' 2>/dev/null || echo "false")"
    echo "Tool response present: $(echo "$json_input" | jq 'has("tool_response")' 2>/dev/null || echo "false")"
    echo
}

# Main function - comprehensive logging with analysis
main() {
    # Read JSON input from stdin (hook payload)
    local json_input=""
    if [[ ! -t 0 ]]; then
        json_input=$(cat)
    fi
    
    # Create timestamp
    local timestamp=$(date +"%Y%m%d_%H%M%S_%3N")
    
    # Extract hook event name
    local hook_event="unknown"
    if [[ -n "$json_input" ]]; then
        hook_event=$(echo "$json_input" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
    fi
    
    # Create detailed log filename
    local log_file="$LOG_DIR/${timestamp}_${hook_event}_DETAILED.log"
    
    # Create comprehensive log entry
    if [[ -n "$json_input" ]]; then
        {
            echo "=== CLAUDE CODE HOOK DEBUG LOG ==="
            echo "Timestamp: $timestamp"
            echo "Hook Event: $hook_event"
            echo
            
            # Analysis
            echo "=== HOOK ANALYSIS ==="
            analyze_hook_data "$json_input" "$hook_event"
            echo
            
            # Statistics
            extract_stats "$json_input"
            
            # Raw JSON (pretty formatted)
            echo "=== RAW JSON PAYLOAD ==="
            echo "$json_input" | jq '.' 2>/dev/null || echo "$json_input"
            echo
            
            echo "=== END LOG ENTRY ==="
        } > "$log_file"
    else
        {
            echo "=== CLAUDE CODE HOOK DEBUG LOG ==="
            echo "Timestamp: $timestamp"
            echo "Hook Event: $hook_event"
            echo "ERROR: No JSON input received from stdin"
            echo "=== END LOG ENTRY ==="
        } > "$log_file"
    fi
    
    # Update comprehensive summary
    local summary_file="$LOG_DIR/comprehensive_summary.jsonl"
    if [[ -n "$json_input" ]]; then
        local session_id=$(echo "$json_input" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
        local transcript_path=$(echo "$json_input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
        local tool_name=$(echo "$json_input" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
        local analysis=$(analyze_hook_data "$json_input" "$hook_event")
        
        # Store comprehensive metadata
        cat << EOF >> "$summary_file"
{"timestamp":"$timestamp","hook_event":"$hook_event","session_id":"$session_id","tool_name":"$tool_name","transcript_path":"$transcript_path","analysis":"$analysis","log_file":"$log_file","json_size":${#json_input}}
EOF
    fi
    
    return 0
}

# Check dependencies
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # Silently skip if jq not available
fi

# Run main function
main "$@" || exit 0