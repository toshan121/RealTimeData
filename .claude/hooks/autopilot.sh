#!/bin/bash
# Autopilot script - Uses Gemini to respond to trivial Claude questions

# Get input from stdin
input=$(cat)

# Extract key information
message=$(echo "$input" | jq -r '.message // ""')
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
transcript_path=$(echo "$input" | jq -r '.transcript_path // ""')

# Check if GEMINI_API_KEY is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo "❌ GEMINI_API_KEY not set - autopilot disabled" >&2
    exit 0
fi

# Check if autopilot is enabled (via environment variable or flag file)
AUTOPILOT_ENABLED=${AUTOPILOT_ENABLED:-false}
if [ -f "$HOME/.claude-autopilot-enabled" ]; then
    AUTOPILOT_ENABLED=true
fi

if [ "$AUTOPILOT_ENABLED" != "true" ]; then
    echo "🔕 Autopilot is disabled" >&2
    exit 0
fi

# Skip autopilot for certain messages
if [[ "$message" == "Claude is waiting for your input" ]]; then
    echo "⏭️  Skipping generic waiting message" >&2
    exit 0
fi

echo "🤖 Autopilot analyzing: $message" >&2

# Build conversation context from recent tool usage and prompts
CONTEXT=""

# Get last few user prompts
if [ -f "$HOME/.claude-logs/user-prompts.log" ]; then
    RECENT_PROMPTS=$(tail -n 10 "$HOME/.claude-logs/user-prompts.log" | grep -E "Prompt:" | tail -n 3)
    CONTEXT="Recent user requests:\n$RECENT_PROMPTS\n\n"
fi

# Get recent tool usage
if [ -f "$HOME/.claude-logs/tool-usage.log" ]; then
    RECENT_TOOLS=$(tail -n 10 "$HOME/.claude-logs/tool-usage.log" | tail -n 5)
    CONTEXT="${CONTEXT}Recent tool usage:\n$RECENT_TOOLS\n\n"
fi

# Get recent tool results
if [ -f "$HOME/.claude-logs/tool-results.log" ]; then
    RECENT_RESULTS=$(tail -n 10 "$HOME/.claude-logs/tool-results.log" | tail -n 3)
    CONTEXT="${CONTEXT}Recent results:\n$RECENT_RESULTS\n\n"
fi

# System prompt for Gemini
SYSTEM_PROMPT="You are an AI assistant helping to guide Claude Code. You should only respond to trivial questions or confirmations. 

For trivial questions like 'Should I continue?', 'Is this correct?', 'Proceed?', respond with simple affirmatives like 'Yes, proceed', 'Continue', 'That looks good'.

For questions about tool permissions like 'Claude needs your permission to use Bash', respond with 'Yes, you can use that tool' or 'Approved'.

For complex questions requiring human judgment, analysis, or preferences, respond with 'HUMAN_NEEDED'.

Be very brief - ideally 1-5 words for simple confirmations."

# Prepare the prompt for Gemini
GEMINI_PROMPT="${SYSTEM_PROMPT}

Context of recent activity:
${CONTEXT}

Claude is asking: \"${message}\"

Should I respond automatically? If yes, what should I say?

Provide your response in JSON format:
{
  \"shouldRespond\": boolean,
  \"response\": \"your response if shouldRespond is true, or HUMAN_NEEDED if complex\",
  \"confidence\": number between 0 and 1,
  \"reasoning\": \"brief explanation\"
}"

# Escape the prompt for JSON
ESCAPED_PROMPT=$(echo "$GEMINI_PROMPT" | jq -Rs .)

# Call Gemini API
GEMINI_URL="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key=${GEMINI_API_KEY}"

GEMINI_RESPONSE=$(curl -s -X POST "$GEMINI_URL" \
    -H "Content-Type: application/json" \
    -d "{
        \"contents\": [{
            \"parts\": [{
                \"text\": $ESCAPED_PROMPT
            }]
        }],
        \"generationConfig\": {
            \"temperature\": 0.1,
            \"maxOutputTokens\": 200,
            \"responseMimeType\": \"application/json\"
        }
    }")

# Extract the response
if [ $? -eq 0 ] && [ -n "$GEMINI_RESPONSE" ]; then
    # Extract the text from Gemini response
    RESPONSE_TEXT=$(echo "$GEMINI_RESPONSE" | jq -r '.candidates[0].content.parts[0].text // ""')
    
    if [ -n "$RESPONSE_TEXT" ]; then
        # Parse the JSON response
        SHOULD_RESPOND=$(echo "$RESPONSE_TEXT" | jq -r '.shouldRespond // false')
        AUTOPILOT_RESPONSE=$(echo "$RESPONSE_TEXT" | jq -r '.response // ""')
        CONFIDENCE=$(echo "$RESPONSE_TEXT" | jq -r '.confidence // 0')
        REASONING=$(echo "$RESPONSE_TEXT" | jq -r '.reasoning // ""')
        
        echo "📊 Autopilot decision: shouldRespond=$SHOULD_RESPOND, confidence=$CONFIDENCE" >&2
        echo "💭 Reasoning: $REASONING" >&2
        
        if [ "$SHOULD_RESPOND" = "true" ] && [ "$AUTOPILOT_RESPONSE" != "HUMAN_NEEDED" ] && [ -n "$AUTOPILOT_RESPONSE" ]; then
            # Log the autopilot response
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Autopilot responded to: $message" >> "$HOME/.claude-logs/autopilot.log"
            echo "  Response: $AUTOPILOT_RESPONSE" >> "$HOME/.claude-logs/autopilot.log"
            echo "  Confidence: $CONFIDENCE" >> "$HOME/.claude-logs/autopilot.log"
            echo "" >> "$HOME/.claude-logs/autopilot.log"
            
            # Send the response to Claude's stdin
            echo "🤖 Autopilot responding: $AUTOPILOT_RESPONSE" >&2
            echo "$AUTOPILOT_RESPONSE"
            
            # Also show notification for transparency
            if [[ "$OSTYPE" == "darwin"* ]]; then
                osascript -e "display notification \"Autopilot: $AUTOPILOT_RESPONSE\" with title \"Claude Code Autopilot\""
            fi
        else
            echo "👤 Human input needed for: $message" >&2
            # Let the normal notification flow continue
            exit 0
        fi
    else
        echo "⚠️  Failed to parse Gemini response" >&2
        exit 0
    fi
else
    echo "⚠️  Failed to contact Gemini API" >&2
    exit 0
fi