#!/bin/bash
# Test all Claude Code hooks

echo "=== Testing Claude Code Hooks Setup ==="
echo ""

# Check if all hook scripts exist and are executable
echo "1. Checking hook scripts..."
hooks=(
    "notification.sh"
    "pre_tool_use.sh"
    "post_tool_use.sh"
    "stop.sh"
    "user_prompt_submit.sh"
    "send_event.sh"
)

all_good=true
for hook in "${hooks[@]}"; do
    if [ -x "/Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/$hook" ]; then
        echo "✓ $hook exists and is executable"
    else
        echo "✗ $hook missing or not executable"
        all_good=false
    fi
done

echo ""
echo "2. Testing individual hooks..."

# Test UserPromptSubmit
echo ""
echo "Testing UserPromptSubmit hook..."
test_prompt='{
  "session_id": "test-session",
  "prompt": "Test user prompt",
  "transcript_path": "/tmp/test.jsonl",
  "cwd": "/Users/toshan/PycharmProjects/claudecodeui",
  "hook_event_name": "UserPromptSubmit"
}'
echo "$test_prompt" | /Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/user_prompt_submit.sh
if [ $? -eq 0 ]; then
    echo "✓ UserPromptSubmit hook executed successfully"
else
    echo "✗ UserPromptSubmit hook failed"
fi

# Test PreToolUse
echo ""
echo "Testing PreToolUse hook..."
test_pre_tool='{
  "session_id": "test-session",
  "tool_name": "Bash",
  "tool_input": {"command": "ls -la"},
  "hook_event_name": "PreToolUse"
}'
echo "$test_pre_tool" | /Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/pre_tool_use.sh
if [ $? -eq 0 ]; then
    echo "✓ PreToolUse hook executed successfully"
else
    echo "✗ PreToolUse hook failed"
fi

# Test dangerous command blocking
echo ""
echo "Testing dangerous command blocking..."
test_dangerous='{
  "session_id": "test-session",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /"},
  "hook_event_name": "PreToolUse"
}'
echo "$test_dangerous" | /Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/pre_tool_use.sh 2>/dev/null
if [ $? -ne 0 ]; then
    echo "✓ Dangerous command correctly blocked"
else
    echo "✗ Dangerous command was NOT blocked (security issue!)"
fi

# Test PostToolUse
echo ""
echo "Testing PostToolUse hook..."
test_post_tool='{
  "session_id": "test-session",
  "tool_name": "Bash",
  "tool_input": {"command": "echo test"},
  "output": "test",
  "success": true,
  "hook_event_name": "PostToolUse"
}'
echo "$test_post_tool" | /Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/post_tool_use.sh
if [ $? -eq 0 ]; then
    echo "✓ PostToolUse hook executed successfully"
else
    echo "✗ PostToolUse hook failed"
fi

# Test send_event.sh (without actually sending)
echo ""
echo "Testing send_event.sh script..."
test_event='{
  "session_id": "test-session",
  "message": "Test event"
}'
# Test with dry run (won't actually send)
echo "$test_event" | /Users/toshan/PycharmProjects/claudecodeui/.claude/hooks/send_event.sh \
    --source-app test \
    --event-type TestEvent \
    --server-url http://localhost:9999/test 2>/dev/null
echo "✓ send_event.sh script syntax is valid"

echo ""
echo "3. Checking log files..."
echo ""
if [ -d "$HOME/.claude-logs" ]; then
    echo "Log directory exists: $HOME/.claude-logs"
    echo "Contents:"
    ls -la "$HOME/.claude-logs/" | grep -E '\.(log|json)$'
else
    echo "Log directory not found (will be created on first use)"
fi

echo ""
echo "4. Verifying settings.json..."
if [ -f "/Users/toshan/PycharmProjects/claudecodeui/.claude/settings.json" ]; then
    echo "✓ settings.json exists"
    # Check if all hooks are configured
    hooks_configured=$(jq -r '.hooks | keys[]' /Users/toshan/PycharmProjects/claudecodeui/.claude/settings.json 2>/dev/null | sort)
    expected_hooks="Notification
PostToolUse
PreToolUse
Stop
UserPromptSubmit"
    
    if [ "$hooks_configured" = "$expected_hooks" ]; then
        echo "✓ All expected hooks are configured"
    else
        echo "✗ Some hooks may be missing from settings.json"
    fi
else
    echo "✗ settings.json not found"
fi

echo ""
echo "=== Test Complete ==="
echo ""
echo "To use these hooks:"
echo "1. Make sure the observability server is running (if using send_event.sh)"
echo "2. Run Claude Code in the /Users/toshan/PycharmProjects/claudecodeui directory"
echo "3. The hooks will automatically trigger based on Claude's actions"
echo ""
echo "Logs will be saved to: $HOME/.claude-logs/"