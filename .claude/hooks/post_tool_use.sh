#!/bin/bash
# PostToolUse Hook - Logs tool execution results

# Read JSON input from stdin
input=$(cat)

# Extract tool information
tool_name=$(echo "$input" | jq -r '.tool_name // ""')
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
success=$(echo "$input" | jq -r '.success // false')
error=$(echo "$input" | jq -r '.error // ""')

# Create log directory
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# Log tool result
if [ "$success" = "true" ]; then
    status="SUCCESS"
else
    status="FAILED"
fi

echo "[$timestamp] Session: $session_id - Tool: $tool_name - Status: $status" >> "$LOG_DIR/tool-results.log"

# If there was an error, log it
if [ -n "$error" ] && [ "$error" != "null" ]; then
    echo "  Error: $error" >> "$LOG_DIR/tool-results.log"
fi

# Log full details for debugging
echo "$input" | jq -c . >> "$LOG_DIR/post-tool-use-full.log"

# Special handling for certain tools
case "$tool_name" in
    "Bash")
        # Extract command and output for bash commands
        command=$(echo "$input" | jq -r '.tool_input.command // ""')
        output=$(echo "$input" | jq -r '.output // ""' | head -n 20)  # First 20 lines
        
        echo "  Command: $command" >> "$LOG_DIR/bash-commands.log"
        if [ -n "$output" ] && [ "$output" != "null" ]; then
            echo "  Output preview: $output" >> "$LOG_DIR/bash-commands.log"
        fi
        ;;
        
    "Write"|"Edit"|"MultiEdit")
        # Track file modifications
        file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
        if [ -n "$file_path" ] && [ "$file_path" != "null" ]; then
            echo "[$timestamp] Modified: $file_path" >> "$LOG_DIR/file-modifications.log"
        fi
        ;;
        
    "Read")
        # Track file reads
        file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
        if [ -n "$file_path" ] && [ "$file_path" != "null" ]; then
            echo "[$timestamp] Read: $file_path" >> "$LOG_DIR/file-reads.log"
        fi
        ;;
esac

# Send event to UI server for persistence
echo "$input" | "$(dirname "$0")/send_to_ui_server.sh" "post_tool_use" &

# Exit successfully
exit 0