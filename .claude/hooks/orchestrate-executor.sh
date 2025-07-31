#!/usr/bin/env bash
# orchestrate-executor.sh - Execute cc_executor with proper environment setup

set -euo pipefail

# Configuration
LOG_FILE="$HOME/.claude/logs/orchestrate-executor.log"
PROJECT_ROOT="/Users/toshan/PycharmProjects/stk_v5"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "🎭 Starting orchestrate-executor hook"

# Read cc-executor command from file (written by /orchestrate command)
command_file="$PROJECT_ROOT/tasks/orchestrate_command.txt"

if [[ ! -f "$command_file" ]]; then
    log "ERROR: No orchestrate command file found at: $command_file"
    log "The /orchestrate command should create this file"
    exit 1
fi

cc_executor_command=$(cat "$command_file")
log "Read cc-executor command from file: ${cc_executor_command:0:100}..."

# Clean up the command file after reading
rm -f "$command_file"

# Change to project directory
cd "$PROJECT_ROOT"
log "Working directory: $(pwd)"

# Set up environment variables for cc_executor
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

# Activate virtual environment if it exists
# Check for common venv locations in order of preference
if [[ -d "venv" && -f "venv/bin/activate" ]]; then
    source venv/bin/activate
    log "✅ Activated venv virtual environment: $(which python)"
elif [[ -d ".venv" && -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
    log "✅ Activated .venv virtual environment: $(which python)"
elif [[ -d "env" && -f "env/bin/activate" ]]; then
    source env/bin/activate
    log "✅ Activated env virtual environment: $(which python)"
else
    log "⚠️ No virtual environment found - using system Python: $(which python)"
fi

# Verify Python environment
log "🐍 Python version: $(python --version)"
log "📍 Python location: $(which python)"
log "📦 Pip location: $(which pip)"

# Set up cc_executor Python path
if [[ -d "lib/cc_executor/src" ]]; then
    export PYTHONPATH="${PROJECT_ROOT}/lib/cc_executor/src:${PYTHONPATH}"
    log "✅ Added cc_executor to PYTHONPATH"
    
    # Test if we can import cc_executor
    if python -c "import cc_executor" 2>/dev/null; then
        log "✅ cc_executor module is importable"
    else
        log "❌ ERROR: cc_executor module cannot be imported"
        exit 1
    fi
else
    log "❌ ERROR: cc_executor source not found at lib/cc_executor/src"
    exit 1
fi

# Set up additional environment variables that cc_executor might need
export CC_EXECUTOR_PROJECT_ROOT="$PROJECT_ROOT"
export CC_EXECUTOR_LOG_LEVEL="${CC_EXECUTOR_LOG_LEVEL:-INFO}"
export CC_EXECUTOR_TIMEOUT="${CC_EXECUTOR_TIMEOUT:-1800}"  # 30 minutes default

# Handle API keys and credentials
# Check for project-level .env first, then global .env
if [[ -f ".env" ]]; then
    set -a  # Automatically export variables
    source .env
    set +a
    log "✅ Loaded environment variables from project .env"
elif [[ -f "$HOME/.env" ]]; then
    set -a  # Automatically export variables
    source "$HOME/.env"
    set +a
    log "✅ Loaded environment variables from global .env"
else
    log "⚠️ No .env file found (checked project and home directory)"
fi

# Also check for .env.local for local overrides
if [[ -f ".env.local" ]]; then
    set -a
    source .env.local
    set +a
    log "✅ Loaded local environment overrides from .env.local"
fi

# Create timestamp for this execution
timestamp=$(date '+%Y%m%d_%H%M%S')
output_dir="tmp/orchestrate_results_${timestamp}"
mkdir -p "$output_dir"

log "📁 Results will be saved to: $output_dir"

# Execute cc-executor command
log "🚀 Executing cc-executor command..."

# Extract the ORCHESTRATE content from the cc-executor command
# Expected format: cc-executor run "claude -p 'ORCHESTRATE this workflow: ...'"
if [[ "$cc_executor_command" =~ cc-executor\ run\ \"claude\ -p\ \'(.*)\'\" ]]; then
    orchestrate_content="${BASH_REMATCH[1]}"
    log "✅ Extracted ORCHESTRATE content: ${orchestrate_content:0:100}..."
else
    log "❌ ERROR: Invalid cc-executor command format"
    log "Expected: cc-executor run \"claude -p 'ORCHESTRATE this workflow: ...'\""
    log "Received: $cc_executor_command"
    exit 1
fi

# Create a temporary Python script to execute the orchestrate command
temp_script="/tmp/cc_executor_orchestrate_${timestamp}.py"

# Write the orchestrate content to a temporary file to avoid shell escaping issues
orchestrate_file="/tmp/orchestrate_command_${timestamp}.txt"
printf '%s' "$orchestrate_content" > "$orchestrate_file"

cat > "$temp_script" << EOF
#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, "${PROJECT_ROOT}/lib/cc_executor/src")

from cc_executor.prompts.cc_execute_utils import execute_task_via_websocket

# Read the orchestrate content from file
with open("${orchestrate_file}", "r") as f:
    orchestrate_content = f.read()

print("🎭 Executing ORCHESTRATE command via cc_executor...")
print("="*80)
print(f"Command length: {len(orchestrate_content)} characters")
print("Command preview:", orchestrate_content[:200], "...")

try:
    result = execute_task_via_websocket(
        task=orchestrate_content,
        timeout=${CC_EXECUTOR_TIMEOUT},
        tools=["Read", "Write", "Edit", "Bash", "TodoWrite", "Grep", "Glob"]
    )
    
    print("✅ CC_Executor completed successfully")
    print(f"Success: {result.get('success', False)}")
    
    # Save results
    import json
    output_file = "${output_dir}/execution_result.json"
    os.makedirs("${output_dir}", exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"📊 Results saved to: {output_file}")
    
    if not result.get('success', False):
        sys.exit(1)
        
except Exception as e:
    print(f"❌ CC_Executor failed with exception: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

# Execute the Python script
exec_result=0
python "$temp_script" 2>&1 | tee -a "$LOG_FILE" || exec_result=$?

# Clean up temporary files
rm -f "$temp_script" "$orchestrate_file"

if [[ $exec_result -eq 0 ]]; then
    log "✅ CC_Executor completed successfully"
    log "📊 Results saved to: $output_dir"
    
    # Create a summary file
    summary_file="$output_dir/execution_summary.md"
    cat > "$summary_file" << EOF
# Orchestration Execution Summary

**Timestamp**: $(date)
**CC-Executor Command**: $cc_executor_command
**ORCHESTRATE Content**: $orchestrate_content
**Status**: SUCCESS
**Output Directory**: $output_dir
**Log File**: $LOG_FILE

## Environment
- Working Directory: $PROJECT_ROOT
- Python Path: $PYTHONPATH
- Virtual Environment: $(which python)
- CC_Executor Version: $(cc_executor --version 2>/dev/null || echo "Unknown")

## Results
Check the files in this directory for detailed execution results.
EOF
    
    log "📝 Summary saved to: $summary_file"
else
    log "❌ CC_Executor failed with exit code: $exec_result"
    log "📋 Check the log file for details: $LOG_FILE"
    exit $exec_result
fi

log "🎭 Orchestrate-executor hook completed"