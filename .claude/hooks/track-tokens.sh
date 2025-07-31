#!/usr/bin/env bash

# track-tokens.sh - Automatic token usage tracking for Claude Code
# This hook runs after other hooks to capture token usage for the conversation

set -euo pipefail

# Get script directory and load common helpers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common-helpers.sh"

# Load project configuration
load_project_config

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
    # Only track tokens if explicitly enabled
    if [[ "${CLAUDE_HOOKS_TRACK_TOKENS:-0}" != "1" ]]; then
        return 0  # Silent skip
    fi
    
    # Run the token tracker in background - never block main flow
    local trigger_type="${CLAUDE_HOOK_TYPE:-generic}"
    
    # Fork to background and discard all output to avoid blocking
    {
        "$SCRIPT_DIR/token-tracker.sh" track "$trigger_type" >/dev/null 2>&1
    } &
    
    # Always return success immediately
    return 0
}

# Only run if called directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi