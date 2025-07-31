#!/bin/bash
# Claude Code Notification Hook with Autopilot support
# This script runs when Claude needs user input or sends a notification

# Read JSON input from stdin
input=$(cat)

# Check if autopilot should handle this first
AUTOPILOT_SCRIPT="$(dirname "$0")/autopilot.sh"
if [ -x "$AUTOPILOT_SCRIPT" ]; then
    # Try autopilot - if it outputs something, that's the response
    AUTOPILOT_RESPONSE=$(echo "$input" | "$AUTOPILOT_SCRIPT" 2>/dev/null)
    if [ -n "$AUTOPILOT_RESPONSE" ]; then
        # Autopilot handled it - exit early
        exit 0
    fi
fi

# Extract key information from the JSON
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
message=$(echo "$input" | jq -r '.message // "No message"')
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# Create logs directory if it doesn't exist
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"

# Log the notification
echo "[$timestamp] Session: $session_id - Message: $message" >> "$LOG_DIR/notifications.log"

# Log full JSON for debugging (optional)
echo "$input" >> "$LOG_DIR/notifications-full.log"

# macOS notification (if on macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # Check if terminal-notifier is installed
    if command -v terminal-notifier &> /dev/null; then
        terminal-notifier -title "Claude Code" -message "$message" -sound default
    else
        # Use built-in osascript as fallback
        osascript -e "display notification \"$message\" with title \"Claude Code\""
    fi
fi

# Linux notification (if on Linux with notify-send)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if command -v notify-send &> /dev/null; then
        notify-send "Claude Code" "$message"
    fi
fi

# Audio notification using built-in system sound (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # Play a system sound
    afplay /System/Library/Sounds/Glass.aiff 2>/dev/null &
fi

# Exit successfully
exit 0