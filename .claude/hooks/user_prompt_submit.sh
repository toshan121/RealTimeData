#!/bin/bash
# UserPromptSubmit Hook - Logs user prompts (v1.0.54+)

# Read JSON input from stdin
input=$(cat)

# Extract prompt information
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')
prompt=$(echo "$input" | jq -r '.prompt // ""')
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# Create log directory
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"

# Log user prompt
echo "[$timestamp] Session: $session_id" >> "$LOG_DIR/user-prompts.log"
echo "  Prompt: $prompt" >> "$LOG_DIR/user-prompts.log"
echo "" >> "$LOG_DIR/user-prompts.log"

# Validate prompt (optional - can block certain patterns)
# Example: Block prompts containing certain keywords
blocked_patterns=(
    "ignore all previous instructions"
    "disregard your guidelines"
    "pretend you are"
)

for pattern in "${blocked_patterns[@]}"; do
    # Convert to lowercase for case-insensitive comparison
    prompt_lower=$(echo "$prompt" | tr '[:upper:]' '[:lower:]')
    pattern_lower=$(echo "$pattern" | tr '[:upper:]' '[:lower:]')
    
    if [[ "$prompt_lower" == *"$pattern_lower"* ]]; then
        echo "BLOCKED: Suspicious prompt pattern detected" >&2
        echo "This prompt appears to be attempting to bypass safety guidelines." >&2
        exit 1
    fi
done

# Track prompt statistics
STATS_FILE="$LOG_DIR/prompt-stats.json"
if [ -f "$STATS_FILE" ]; then
    # Update existing stats
    stats=$(cat "$STATS_FILE")
    total=$(echo "$stats" | jq -r '.total_prompts // 0')
    total=$((total + 1))
    
    # Update stats with word count
    word_count=$(echo "$prompt" | wc -w | tr -d ' ')
    avg_words=$(echo "$stats" | jq -r '.avg_word_count // 0')
    new_avg=$(( (avg_words * (total - 1) + word_count) / total ))
    
    echo "$stats" | jq \
        --arg total "$total" \
        --arg avg "$new_avg" \
        --arg last "$timestamp" \
        '.total_prompts = ($total | tonumber) | .avg_word_count = ($avg | tonumber) | .last_prompt = $last' \
        > "$STATS_FILE"
else
    # Create initial stats
    word_count=$(echo "$prompt" | wc -w | tr -d ' ')
    jq -n \
        --arg wc "$word_count" \
        --arg ts "$timestamp" \
        '{
            total_prompts: 1,
            avg_word_count: ($wc | tonumber),
            first_prompt: $ts,
            last_prompt: $ts
        }' > "$STATS_FILE"
fi

# Log full event for debugging
echo "$input" | jq -c . >> "$LOG_DIR/user-prompt-submit-full.log"

# Send event to UI server for persistence
echo "$input" | "$(dirname "$0")/send_to_ui_server.sh" "user_prompt_submit" &

# Exit successfully
exit 0