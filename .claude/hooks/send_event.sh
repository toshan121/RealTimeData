#!/bin/bash
# Send Claude Code hook events to observability server with optional AI summarization

# Parse command line arguments
SOURCE_APP=""
EVENT_TYPE=""
SERVER_URL="http://localhost:4000/events"
ADD_CHAT=false
SUMMARIZE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --source-app)
            SOURCE_APP="$2"
            shift 2
            ;;
        --event-type)
            EVENT_TYPE="$2"
            shift 2
            ;;
        --server-url)
            SERVER_URL="$2"
            shift 2
            ;;
        --add-chat)
            ADD_CHAT=true
            shift
            ;;
        --summarize)
            SUMMARIZE=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Check required arguments
if [ -z "$SOURCE_APP" ] || [ -z "$EVENT_TYPE" ]; then
    echo "Error: --source-app and --event-type are required" >&2
    exit 1
fi

# Read JSON input from stdin
input=$(cat)

# Extract key fields from input
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
timestamp=$(date +%s%3N)  # Millisecond timestamp

# Build event data
event_data=$(jq -n \
    --arg source_app "$SOURCE_APP" \
    --arg session_id "$session_id" \
    --arg hook_event_type "$EVENT_TYPE" \
    --argjson payload "$input" \
    --arg timestamp "$timestamp" \
    '{
        source_app: $source_app,
        session_id: $session_id,
        hook_event_type: $hook_event_type,
        payload: $payload,
        timestamp: ($timestamp | tonumber)
    }')

# Add chat transcript if requested
if [ "$ADD_CHAT" = true ]; then
    transcript_path=$(echo "$input" | jq -r '.transcript_path // ""')
    if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
        # Convert JSONL to JSON array
        chat_data="[]"
        while IFS= read -r line; do
            if [ -n "$line" ]; then
                chat_data=$(echo "$chat_data" | jq ". + [$line]")
            fi
        done < "$transcript_path"
        
        # Add chat to event data
        event_data=$(echo "$event_data" | jq --argjson chat "$chat_data" '. + {chat: $chat}')
    fi
fi

# Generate summary if requested
if [ "$SUMMARIZE" = true ] && [ -n "$ANTHROPIC_API_KEY" ]; then
    # Prepare summary prompt
    payload_preview=$(echo "$input" | jq -c . | head -c 1000)
    
    summary_prompt="Generate a one-sentence summary of this Claude Code hook event payload for an engineer monitoring the system.

Event Type: $EVENT_TYPE
Payload: $payload_preview

Requirements:
- ONE sentence only (no period at the end)
- Focus on the key action or information
- Be specific and technical
- Keep under 15 words
- Use present tense
- Return ONLY the summary text"

    # Call Claude API for summary
    summary_response=$(curl -s -X POST https://api.anthropic.com/v1/messages \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "$(jq -n \
            --arg prompt "$summary_prompt" \
            '{
                model: "claude-3-haiku-20240307",
                max_tokens: 50,
                messages: [{role: "user", content: $prompt}]
            }')")
    
    # Extract summary from response
    if [ $? -eq 0 ]; then
        summary=$(echo "$summary_response" | jq -r '.content[0].text // ""' | tr -d '\n' | cut -c1-100)
        if [ -n "$summary" ]; then
            event_data=$(echo "$event_data" | jq --arg summary "$summary" '. + {summary: $summary}')
        fi
    fi
fi

# Send to server
response=$(curl -s -w "\n%{http_code}" -X POST "$SERVER_URL" \
    -H "Content-Type: application/json" \
    -H "User-Agent: Claude-Code-Hook/1.0" \
    -d "$event_data" \
    --connect-timeout 5 \
    --max-time 10)

# Extract HTTP status code (last line)
http_code=$(echo "$response" | tail -n1)

# Check if request was successful
if [ "$http_code" = "200" ]; then
    # Success - exit silently
    exit 0
else
    # Log error but don't block Claude Code
    echo "Failed to send event. HTTP status: $http_code" >&2
    exit 0
fi