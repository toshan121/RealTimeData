#!/bin/bash
# Stop Hook - Runs when Claude completes a response

# Read JSON input from stdin
input=$(cat)

# Extract session information
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
transcript_path=$(echo "$input" | jq -r '.transcript_path // ""')
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# Create log directory
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"

# Log session completion
echo "[$timestamp] Session completed: $session_id" >> "$LOG_DIR/sessions.log"

# Create session summary if transcript exists
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    # Count messages in transcript
    message_count=$(wc -l < "$transcript_path" 2>/dev/null || echo "0")
    
    # Extract key metrics from transcript
    tool_uses=0
    user_messages=0
    assistant_messages=0
    
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            role=$(echo "$line" | jq -r '.role // ""' 2>/dev/null)
            case "$role" in
                "user")
                    ((user_messages++))
                    ;;
                "assistant")
                    ((assistant_messages++))
                    # Count tool uses
                    tool_count=$(echo "$line" | jq -r '.content | map(select(.type == "tool_use")) | length' 2>/dev/null || echo "0")
                    tool_uses=$((tool_uses + tool_count))
                    ;;
            esac
        fi
    done < "$transcript_path"
    
    # Log session summary
    echo "  Messages: $message_count (User: $user_messages, Assistant: $assistant_messages)" >> "$LOG_DIR/sessions.log"
    echo "  Tool uses: $tool_uses" >> "$LOG_DIR/sessions.log"
    
    # Save transcript backup
    TRANSCRIPT_DIR="$LOG_DIR/transcripts"
    mkdir -p "$TRANSCRIPT_DIR"
    backup_name="transcript_${session_id}_$(date +%Y%m%d_%H%M%S).jsonl"
    cp "$transcript_path" "$TRANSCRIPT_DIR/$backup_name" 2>/dev/null
fi

# Log full stop event
echo "$input" | jq -c . >> "$LOG_DIR/stop-events-full.log"

# Send event to UI server for persistence
echo "$input" | "$(dirname "$0")/send_to_ui_server.sh" "stop" &

# Exit successfully
exit 0