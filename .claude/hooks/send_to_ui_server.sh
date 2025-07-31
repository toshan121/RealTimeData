#!/bin/bash
# Send hook events to UI server for persistence and observability

# Read JSON input from stdin
input=$(cat)

# Extract key information
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
hook_type="$1"  # Hook type passed as first argument

# UI server URL (configurable via environment variable)
UI_SERVER_URL=${UI_SERVER_URL:-"http://localhost:3008"}
EVENT_ENDPOINT="$UI_SERVER_URL/api/events"

# Log the event
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$timestamp] Sending $hook_type event to UI server for session: $session_id" >> "$LOG_DIR/ui-server-events.log"

# Build event payload
event_payload=$(jq -n \
    --arg source_app "claude-code-ui" \
    --arg session_id "$session_id" \
    --arg hook_event_type "$hook_type" \
    --argjson payload "$input" \
    --arg timestamp "$(date +%s)000" \
    '{
        source_app: $source_app,
        session_id: $session_id,
        hook_event_type: $hook_event_type,
        payload: $payload,
        timestamp: ($timestamp | tonumber)
    }')

# Send to UI server
response=$(curl -s -w "\n%{http_code}" -X POST "$EVENT_ENDPOINT" \
    -H "Content-Type: application/json" \
    -H "X-Session-ID: $session_id" \
    -d "$event_payload" \
    --connect-timeout 2 \
    --max-time 5)

# Extract HTTP status code (last line)
http_code=$(echo "$response" | tail -n1)

# Log result
if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
    echo "[$timestamp] Successfully sent $hook_type event to UI server" >> "$LOG_DIR/ui-server-events.log"
else
    echo "[$timestamp] Failed to send $hook_type event. HTTP status: $http_code" >> "$LOG_DIR/ui-server-events.log"
fi

# Don't block on failures - exit successfully
exit 0