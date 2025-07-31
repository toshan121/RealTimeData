#!/bin/bash
# Test script for session naming functionality

# Source the timestamp variable
timestamp=$(date '+%Y%m%d_%H%M%S')

# Create a mock transcript with some content
mock_transcript="/tmp/test_transcript_$$.json"
cat > "$mock_transcript" << 'EOF'
{"type": "user_message", "content": "I need help fixing the gap detection algorithm in my trading strategy"}
{"type": "assistant_message", "content": "I'll help you fix the gap detection algorithm. Let me first examine the current implementation."}
{"type": "user_message", "content": "The issue is that it's not properly detecting 30% gaps"}
{"type": "assistant_message", "content": "I see the issue. The gap calculation needs to compare the current open with the previous close, not the previous open."}
EOF

# Source the generate_session_name function from the hook
source /Users/toshan/PycharmProjects/stk_v5/.claude/hooks/compact-new-session.sh

# Test with Claude CLI available
echo "Testing session name generation..."
session_name=$(generate_session_name "$mock_transcript")
echo "Generated session name: $session_name"

# Test with non-existent transcript
echo -e "\nTesting with non-existent transcript..."
session_name=$(generate_session_name "/tmp/nonexistent.json")
echo "Generated session name: $session_name"

# Test CLI availability
echo -e "\nChecking Claude CLI availability..."
if command -v claude >/dev/null 2>&1; then
    echo "✓ Claude CLI is available"
else
    echo "✗ Claude CLI not found - names will use timestamps"
fi

# Cleanup
rm -f "$mock_transcript"

echo -e "\nTest complete!"