#!/usr/bin/env bash
# compact-new-session.sh - Start new Claude Code session with compact summary
#
# SYNOPSIS
#   compact-new-session.sh
#
# DESCRIPTION
#   Triggered by PreCompact hook when /compact command is used.
#   Extracts conversation summary and starts a new Claude Code session
#   with that summary as the initial context.
#
# PAYLOAD
#   Receives JSON payload with session_id, transcript_path, trigger type
#
# BEHAVIOR
#   1. Extracts conversation summary from current session
#   2. Saves summary to temporary file
#   3. Starts new Claude Code session with summary
#   4. Allows current session to compact normally

set -euo pipefail

# Configuration
CLAUDE_SESSIONS_DIR="$HOME/.claude/sessions"
COMPACT_SUMMARIES_DIR="$HOME/.claude/compact-summaries"
LOG_FILE="$HOME/.claude/logs/compact-session.log"

# Ensure directories exist
mkdir -p "$CLAUDE_SESSIONS_DIR" "$COMPACT_SUMMARIES_DIR" "$(dirname "$LOG_FILE")"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Read hook payload from stdin
if [ -t 0 ]; then
    log "WARNING: No payload data available"
    hook_data="{}"
else
    hook_data=$(cat)
fi

# Parse payload using jq if available
if command -v jq >/dev/null 2>&1; then
    session_id=$(echo "$hook_data" | jq -r '.session_id // ""')
    trigger=$(echo "$hook_data" | jq -r '.trigger // ""')
    transcript_path=$(echo "$hook_data" | jq -r '.transcript_path // ""')
    custom_instructions=$(echo "$hook_data" | jq -r '.custom_instructions // ""')
else
    log "WARNING: jq not found, cannot parse hook payload properly"
    session_id=""
    trigger="manual"
    transcript_path=""
    custom_instructions=""
fi

log "PreCompact hook triggered:"
log "  Session ID: $session_id"
log "  Trigger: $trigger"
log "  Transcript: $transcript_path"

# Only proceed for manual compacts (user-initiated /compact)
if [[ "$trigger" != "manual" ]]; then
    log "Skipping new session creation for non-manual compact (trigger: $trigger)"
    exit 0
fi

# Generate timestamp for session naming
timestamp=$(date '+%Y%m%d_%H%M%S')
session_name_base="claude"  # Default base name

# Function to generate descriptive session name using Claude Code CLI
generate_session_name() {
    local transcript="$1"
    
    # Check if claude CLI is available
    if ! command -v claude >/dev/null 2>&1; then
        log "WARNING: claude CLI not found, using timestamp-based name"
        echo "claude-${timestamp}"
        return
    fi
    
    # Check if transcript exists and has content
    if [[ ! -f "$transcript" ]] || [[ ! -s "$transcript" ]]; then
        log "WARNING: No transcript available for session naming"
        echo "claude-${timestamp}"
        return
    fi
    
    # Extract last few meaningful messages from transcript
    local context=""
    if command -v jq >/dev/null 2>&1; then
        context=$(jq -r '
            select(.type == "assistant_message" or .type == "user_message") |
            select(.content != null and .content != "") |
            select(.content | type == "string") |
            .content
        ' "$transcript" 2>/dev/null | tail -10 | head -500) || context=""
    fi
    
    # If no context extracted, use timestamp
    if [[ -z "$context" ]]; then
        log "WARNING: Could not extract context from transcript"
        echo "claude-${timestamp}"
        return
    fi
    
    # Create prompt for session naming
    local prompt="Based on this conversation context, generate a descriptive 3-4 word kebab-case name for a coding session. Examples: 'test-validation-fixes', 'database-schema-update', 'api-endpoint-creation'. Return ONLY the kebab-case name, nothing else.

Context:
${context}"
    
    # Call Claude Code CLI to generate session name
    local session_suffix
    session_suffix=$(echo "$prompt" | claude code --no-interactive --max-tokens 50 2>/dev/null | tail -1 | tr -d '\n' | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]//g') || session_suffix=""
    
    # Validate and return session name
    if [[ -n "$session_suffix" ]] && [[ "$session_suffix" =~ ^[a-z0-9-]+$ ]] && [[ ${#session_suffix} -gt 5 ]]; then
        echo "claude-${session_suffix}"
        log "Generated session name: claude-${session_suffix}"
    else
        echo "claude-${timestamp}"
        log "Failed to generate descriptive name, using timestamp"
    fi
}

# Function to extract summary from transcript
extract_summary() {
    local transcript="$1"
    local summary_file="$2"
    
    if [[ ! -f "$transcript" ]]; then
        log "WARNING: Transcript file not found: $transcript"
        echo "# Conversation Summary (${timestamp})" > "$summary_file"
        echo "" >> "$summary_file"
        echo "**Note**: Original transcript was not accessible during compaction." >> "$summary_file"
        echo "" >> "$summary_file"
        echo "This session was started after a /compact command was issued." >> "$summary_file"
        return
    fi

    # Create summary file with header
    cat > "$summary_file" << EOF
# Conversation Summary (${timestamp})

**Previous Session**: ${session_id}
**Compacted**: $(date '+%Y-%m-%d %H:%M:%S')
**Working Directory**: $(pwd)

## Context
This session continues from a previous conversation that was compacted.

## Previous Conversation Summary
EOF

    # Try to extract meaningful content from transcript
    if command -v jq >/dev/null 2>&1; then
        # Extract the last few meaningful exchanges
        log "Extracting conversation context from transcript..."
        
        # Get last 5 assistant responses that aren't just tool calls
        jq -r '
            select(.type == "assistant_message") |
            select(.content != null and .content != "") |
            select(.content | type == "string") |
            select(.content | length > 50) |
            .content
        ' "$transcript" | tail -5 >> "$summary_file" 2>/dev/null || {
            echo "Recent conversation content was not extractable from transcript." >> "$summary_file"
        }
    else
        echo "jq not available - cannot extract detailed summary from transcript." >> "$summary_file"
    fi

    # Add footer
    cat >> "$summary_file" << EOF

## Current Status
- **Project**: $(basename "$(pwd)")
- **Git Branch**: $(git branch --show-current 2>/dev/null || echo "unknown")
- **Last Modified Files**: $(git status --porcelain 2>/dev/null | head -3 | cut -c4- | tr '\n' ', ' | sed 's/,$//' || echo "none detected")

---
*Session continues from this point with fresh context window...*
EOF
}

# Generate descriptive session name
session_name="claude-${timestamp}"  # Default
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    log "Generating descriptive session name from transcript..."
    session_name=$(generate_session_name "$transcript_path")
fi

# Use descriptive name for summary file too
if [[ "$session_name" != "claude-${timestamp}" ]]; then
    summary_file="$COMPACT_SUMMARIES_DIR/${session_name}_summary.md"
else
    summary_file="$COMPACT_SUMMARIES_DIR/summary_${timestamp}.md"
fi

# Extract summary if transcript is available
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    log "Extracting summary from transcript: $transcript_path"
    extract_summary "$transcript_path" "$summary_file"
else
    log "Creating basic summary without transcript access"
    extract_summary "" "$summary_file"
fi

log "Summary saved to: $summary_file"
log "Session name: $session_name"

# Function to start new Claude Code session
start_new_session() {
    local summary_file="$1"
    
    # Check if we're in tmux and can create a new window
    if [[ -n "${TMUX:-}" ]] && command -v tmux >/dev/null 2>&1; then
        log "Starting new Claude session in tmux window"
        
        # Create new tmux window with Claude Code
        tmux new-window -n "$session_name" -c "$(pwd)" \
            "claude code --resume --message-file='$summary_file'"
        
        log "New tmux window '$session_name' started with summary"
        
    elif [[ "${TERM_PROGRAM:-}" == "kitty" ]] && command -v kitty >/dev/null 2>&1; then
        log "Starting new Claude session in kitty tab"
        
        # Create new kitty tab
        kitty @ new-tab --tab-title "$session_name" --cwd "$(pwd)" \
            bash -c "claude code --resume --message-file='$summary_file'"
        
        log "New kitty tab started with summary"
        
    elif [[ "$(uname)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
        # macOS: Try to open new terminal window/tab
        if [[ "${TERM_PROGRAM:-}" == "iTerm.app" ]]; then
            log "Starting new Claude session in iTerm2 tab"
            
            osascript << EOF
tell application "iTerm2"
    tell current window
        create tab with default profile
        tell current session
            write text "cd '$(pwd)'"
            write text "claude code --resume --message-file='$summary_file'"
        end tell
    end tell
end tell
EOF
            log "New iTerm2 tab started with summary"
            
        elif [[ "${TERM_PROGRAM:-}" == "Apple_Terminal" ]]; then
            log "Starting new Claude session in Terminal.app tab"
            
            osascript << EOF
tell application "Terminal"
    tell front window
        do script "cd '$(pwd)'; claude code --resume --message-file='$summary_file'"
    end tell
end tell
EOF
            log "New Terminal.app tab started with summary"
        else
            log "macOS detected but unknown terminal program: ${TERM_PROGRAM:-unknown}"
            create_instruction_file
        fi
    else
        # Fallback: Create instruction file for manual execution
        create_instruction_file
    fi
}

# Function to create instruction file for manual session start
create_instruction_file() {
    local instruction_file="$COMPACT_SUMMARIES_DIR/start_session_${timestamp}.sh"
    
    cat > "$instruction_file" << EOF
#!/bin/bash
# Instructions to start new Claude session with summary
# Generated: $(date)

echo "Starting new Claude Code session with conversation summary..."
echo "Summary file: $summary_file"
echo ""

cd "$(pwd)"
claude code --resume --message-file="$summary_file"
EOF
    
    chmod +x "$instruction_file"
    
    log "Created instruction file: $instruction_file"
    log "To start new session manually, run: $instruction_file"
    
    # Also output to user
    echo ""
    echo "📝 Compact summary saved to: $summary_file"
    echo "🚀 To start new session with summary:"
    echo "   $instruction_file"
    echo ""
}

# Start new session with summary
start_new_session "$summary_file"

# Record session transition
session_log="$COMPACT_SUMMARIES_DIR/session_history.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') | $session_id | $trigger | $summary_file" >> "$session_log"

log "PreCompact hook completed successfully"
log "Current session will now compact normally"

# Exit 0 to allow the compact operation to proceed
exit 0