# Intelligent Session Naming for Claude Code Compact

## Overview
The `compact-new-session.sh` hook now includes intelligent session naming that generates descriptive names based on the conversation context.

## Features
- **Automatic Context Analysis**: Extracts recent conversation from transcript
- **AI-Generated Names**: Uses Claude Code CLI to generate 3-4 word descriptive names
- **Fallback to Timestamp**: If CLI unavailable or no context, uses timestamp
- **Descriptive File Names**: Summary files also use the generated names

## Setup

No additional setup required! The hook uses the existing Claude Code CLI installation.

## How It Works

When you run `/compact`:
1. Hook extracts last 10 messages from conversation
2. Uses Claude Code CLI to generate a descriptive name
3. Claude generates a descriptive kebab-case name
4. New session and files use this name

## Examples

### Before (Timestamp-based)
- Session: `claude-20250112_155030`
- File: `summary_20250112_155030.md`

### After (Context-based)
- Session: `claude-gap-detection-fixes`
- File: `claude-gap-detection-fixes_summary.md`

### More Examples
- `claude-test-validation-work`
- `claude-database-schema-update`
- `claude-api-endpoint-creation`
- `claude-hook-configuration-setup`

## Troubleshooting

### Claude CLI Not Found
If `claude` command is not available, falls back to timestamp naming.

### Empty Context
If no meaningful conversation extracted, uses timestamp.

### Invalid Response
If CLI returns invalid format, uses timestamp.

## Technical Details
- Uses Claude Code CLI with `--no-interactive` flag
- Max tokens: 50 (enough for 3-4 words)
- Context: Last 10 messages (max 500 chars)
- Validation: Only allows `a-z`, `0-9`, and `-`
- Minimum length: 6 characters for valid name