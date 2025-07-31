#!/usr/bin/env bash
# auto-commit.sh - Automatic git commit with proper staging

set -euo pipefail

# Configuration
PROJECT_ROOT="/Users/toshan/PycharmProjects/stk_v5"
LOG_FILE="$HOME/.claude/logs/auto-commit.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Read commit message from command line argument or stdin
commit_message="${1:-}"
if [[ -z "$commit_message" && ! -t 0 ]]; then
    commit_message=$(cat)
fi

if [[ -z "$commit_message" ]]; then
    log "ERROR: No commit message provided"
    exit 1
fi

log "💾 Starting auto-commit hook"
log "Message: $commit_message"

# Change to project directory
cd "$PROJECT_ROOT"

# Check if we're in a git repository
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    log "ERROR: Not in a git repository"
    exit 1
fi

# Check git status
git_status_output=$(git status --porcelain)
if [[ -z "$git_status_output" ]]; then
    log "ℹ️ No changes to commit"
    exit 0
fi

log "📋 Changes detected:"
echo "$git_status_output" | while read -r line; do
    log "  $line"
done

# Stage all changes
log "📦 Staging all changes..."
git add .

# Check for any staged changes
staged_changes=$(git diff --cached --name-only)
if [[ -z "$staged_changes" ]]; then
    log "ℹ️ No staged changes after git add"
    exit 0
fi

log "✅ Staged files:"
echo "$staged_changes" | while read -r file; do
    log "  $file"
done

# Create the commit
log "💾 Creating commit..."
if git commit -m "$commit_message"; then
    commit_hash=$(git rev-parse HEAD)
    log "✅ Commit created successfully: $commit_hash"
    log "📝 Message: $commit_message"
else
    log "❌ Commit failed"
    exit 1
fi

log "💾 Auto-commit hook completed"