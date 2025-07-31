#!/bin/bash
# Notification Webhook - Sends notifications to UI server for autopilot handling

# Read JSON input from stdin
input=$(cat)

# Extract key information
message=$(echo "$input" | jq -r '.message // ""')
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
transcript_path=$(echo "$input" | jq -r '.transcript_path // ""')
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# UI server URL (configurable via environment variable)
UI_SERVER_URL=${UI_SERVER_URL:-"http://localhost:3008"}
WEBHOOK_ENDPOINT="$UI_SERVER_URL/api/claude-notification"

# Log the notification
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"
echo "[$timestamp] Sending notification to UI: $message" >> "$LOG_DIR/notification-webhook.log"

# Prepare webhook payload with full context
WEBHOOK_PAYLOAD=$(jq -n \
    --arg session_id "$session_id" \
    --arg message "$message" \
    --arg transcript_path "$transcript_path" \
    --argjson original_input "$input" \
    --arg timestamp "$timestamp" \
    '{
        session_id: $session_id,
        message: $message,
        transcript_path: $transcript_path,
        timestamp: $timestamp,
        hook_data: $original_input,
        context: {
            recent_prompts: [],
            recent_tools: [],
            recent_results: []
        }
    }')

# Add context from logs
if [ -f "$LOG_DIR/user-prompts.log" ]; then
    RECENT_PROMPTS=$(tail -n 20 "$LOG_DIR/user-prompts.log" | grep -A1 "Session: $session_id" | grep "Prompt:" | tail -n 3 | sed 's/^[ \t]*//')
    if [ -n "$RECENT_PROMPTS" ]; then
        PROMPTS_JSON=$(echo "$RECENT_PROMPTS" | jq -R . | jq -s .)
        WEBHOOK_PAYLOAD=$(echo "$WEBHOOK_PAYLOAD" | jq --argjson prompts "$PROMPTS_JSON" '.context.recent_prompts = $prompts')
    fi
fi

if [ -f "$LOG_DIR/tool-usage.log" ]; then
    RECENT_TOOLS=$(tail -n 20 "$LOG_DIR/tool-usage.log" | grep "Session: $session_id" | tail -n 5)
    if [ -n "$RECENT_TOOLS" ]; then
        TOOLS_JSON=$(echo "$RECENT_TOOLS" | jq -R . | jq -s .)
        WEBHOOK_PAYLOAD=$(echo "$WEBHOOK_PAYLOAD" | jq --argjson tools "$TOOLS_JSON" '.context.recent_tools = $tools')
    fi
fi

if [ -f "$LOG_DIR/tool-results.log" ]; then
    RECENT_RESULTS=$(tail -n 20 "$LOG_DIR/tool-results.log" | grep "Session: $session_id" | tail -n 5)
    if [ -n "$RECENT_RESULTS" ]; then
        RESULTS_JSON=$(echo "$RECENT_RESULTS" | jq -R . | jq -s .)
        WEBHOOK_PAYLOAD=$(echo "$WEBHOOK_PAYLOAD" | jq --argjson results "$RESULTS_JSON" '.context.recent_results = $results')
    fi
fi

# Send to UI server
echo "Sending notification to UI server..." >&2
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_ENDPOINT" \
    -H "Content-Type: application/json" \
    -H "X-Session-ID: $session_id" \
    -d "$WEBHOOK_PAYLOAD" \
    --connect-timeout 5 \
    --max-time 30)

# Extract HTTP status code (last line)
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$RESPONSE" | sed '$d')

echo "UI server response code: $HTTP_CODE" >&2

# Check if we got an autopilot response
if [ "$HTTP_CODE" = "200" ] && [ -n "$RESPONSE_BODY" ]; then
    # Check if response contains autopilot action
    AUTOPILOT_RESPONSE=$(echo "$RESPONSE_BODY" | jq -r '.autopilot_response // ""')
    SHOULD_RESPOND=$(echo "$RESPONSE_BODY" | jq -r '.should_respond // false')
    
    if [ "$SHOULD_RESPOND" = "true" ] && [ -n "$AUTOPILOT_RESPONSE" ]; then
        echo "🤖 UI Autopilot responded: $AUTOPILOT_RESPONSE" >&2
        echo "[$timestamp] UI Autopilot: $AUTOPILOT_RESPONSE" >> "$LOG_DIR/notification-webhook.log"
        
        # The UI server should handle sending the response to Claude
        # We just need to suppress the normal notification
        exit 0
    fi
fi

# If no autopilot response or error, continue with normal notification flow
echo "No autopilot response from UI, continuing with normal notification..." >&2

# Fallback to local notification
source "$(dirname "$0")/notification.sh"