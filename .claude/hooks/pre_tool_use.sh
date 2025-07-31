#!/bin/bash
# PreToolUse Hook - Validates tool usage and blocks dangerous operations

# Read JSON input from stdin
input=$(cat)

# Extract tool information
tool_name=$(echo "$input" | jq -r '.tool_name // ""')
tool_input=$(echo "$input" | jq -r '.tool_input // {}')
session_id=$(echo "$input" | jq -r '.session_id // "unknown"')

# Log tool usage
LOG_DIR="$HOME/.claude-logs"
mkdir -p "$LOG_DIR"
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$timestamp] Session: $session_id - Tool: $tool_name" >> "$LOG_DIR/tool-usage.log"

# Check for dangerous bash commands
if [ "$tool_name" = "Bash" ]; then
    command=$(echo "$tool_input" | jq -r '.command // ""')
    
    # List of dangerous patterns
    dangerous_patterns=(
        "rm -rf /"
        "rm -rf /*"
        ":(){ :|:& };:"  # Fork bomb
        "dd if=/dev/zero"
        "mkfs."
        "> /dev/sda"
        "chmod -R 777 /"
    )
    
    # Check for dangerous patterns
    for pattern in "${dangerous_patterns[@]}"; do
        if [[ "$command" == *"$pattern"* ]]; then
            echo "BLOCKED: Dangerous command detected: $pattern" >&2
            echo "This command could cause serious damage to your system." >&2
            exit 1
        fi
    done
    
    # Check for operations on sensitive files
    sensitive_paths=(
        ".env"
        ".ssh/id_rsa"
        ".ssh/id_ed25519"
        ".aws/credentials"
        ".config/gh/hosts.yml"
        "private.key"
        "secret"
    )
    
    for path in "${sensitive_paths[@]}"; do
        if [[ "$command" == *"$path"* ]] && [[ "$command" == *"cat"* || "$command" == *"less"* || "$command" == *"more"* ]]; then
            echo "BLOCKED: Attempt to read sensitive file: $path" >&2
            echo "Access to sensitive files is restricted for security." >&2
            exit 1
        fi
    done
fi

# Check for dangerous file operations
if [[ "$tool_name" == "Write" || "$tool_name" == "Edit" ]]; then
    file_path=$(echo "$tool_input" | jq -r '.file_path // ""')
    
    # Block writing to sensitive files
    sensitive_files=(
        "/.bashrc"
        "/.zshrc"
        "/.bash_profile"
        "/etc/passwd"
        "/etc/shadow"
        "/.ssh/authorized_keys"
    )
    
    for sensitive in "${sensitive_files[@]}"; do
        if [[ "$file_path" == *"$sensitive" ]]; then
            echo "BLOCKED: Cannot modify sensitive file: $sensitive" >&2
            exit 1
        fi
    done
fi

# Log detailed tool input for debugging
echo "$input" | jq -c . >> "$LOG_DIR/pre-tool-use-full.log"

# Send event to UI server for persistence
echo "$input" | "$(dirname "$0")/send_to_ui_server.sh" "pre_tool_use" &

# Tool usage is allowed - exit successfully
exit 0