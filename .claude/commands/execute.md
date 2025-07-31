---
allowed-tools: all
description: Execute the generated executor.py file with proper environment activation
---

# ⚡ EXECUTE COMMAND - Run the Generated Executor

This command activates the appropriate virtual environment and executes the generated executor.py file.

## 🚀 YOUR MISSION

Execute the executor.py file that was created by the /plan command, ensuring:
1. Proper virtual environment activation
2. Real-time progress monitoring
3. Error handling and recovery options
4. Clear status reporting

## 📋 EXECUTION WORKFLOW

### Step 0: Create Safety Checkpoint
```bash
/commit with message: "checkpoint(pre-execute): Save state before running executor"
```

### Step 1: Pre-Flight Checks
```bash
# Verify executor.py exists
if [ ! -f "/Users/toshan/PycharmProjects/stk_v5/executor.py" ]; then
    echo "ERROR: No executor.py found. Run /plan first!"
    exit 1
fi

# Check for virtual environment
if [ -d "/Users/toshan/PycharmProjects/stk_v5/venv" ]; then
    VENV_PATH="/Users/toshan/PycharmProjects/stk_v5/venv"
elif [ -d "/Users/toshan/PycharmProjects/stk_v5/.venv" ]; then
    VENV_PATH="/Users/toshan/PycharmProjects/stk_v5/.venv"
else
    echo "WARNING: No virtual environment found. Using system Python."
fi
```

### Step 2: Environment Activation
```bash
# Activate virtual environment if found
if [ -n "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    echo "✅ Activated virtual environment: $VENV_PATH"
fi

# Ensure we're in the correct directory
cd /Users/toshan/PycharmProjects/stk_v5
```

### Step 3: Execute with Monitoring
```bash
# Run the executor with unbuffered output for real-time monitoring
python -u executor.py
```

## 🎯 EXECUTION FEATURES

### Real-Time Progress
- Display output as it happens (unbuffered)
- Show clear [X/Y] progress indicators
- Timestamp each task start/completion

### Error Recovery
- If execution fails, check checkpoint files
- Suggest resume options if available
- Display clear error messages

### Status Reporting
```
============================================================
EXECUTOR STARTED
Requirement: [User's original requirement]
Total Tasks: X
Execution Mode: Sequential
============================================================

[1/X] Starting: Task Name
      Executing: command...
      ✅ SUCCESS - Task Name (X.Xs)

[2/X] Starting: Next Task
      ...
```

## 🔧 ADVANCED OPTIONS

### Resume from Checkpoint
If the executor supports checkpoints:
```bash
python executor.py --resume executor_checkpoint_YYYYMMDD_HHMMSS.json
```

### Custom Requirements
If the executor accepts arguments:
```bash
python executor.py --requirement "specific override"
```

## 📊 POST-EXECUTION

After execution completes:

1. **Check Results**:
   - Look for `executor_report_*.json` files
   - Review log files for detailed output
   - Check checkpoint files for progress

2. **Verify Success**:
   - Confirm all tasks completed
   - Check success rates
   - Review any failed tasks

3. **Commit Results**:
   ```bash
   # If successful
   /commit with message: "fix(tests): Complete executor run - X/Y tasks successful"
   
   # If partially successful
   /commit with message: "wip(executor): Partial executor run - X/Y tasks completed"
   
   # If failed
   /commit with message: "debug(executor): Executor run failed - see logs for details"
   ```

4. **Next Actions**:
   - If failures occurred, suggest fixes
   - If successful, suggest next steps
   - Archive results if needed

## 🚨 ERROR HANDLING

Common issues and solutions:

**No executor.py**:
```
ERROR: No executor.py found. Run /plan first!
Solution: Use /plan "your requirements" to generate executor.py
```

**Import errors**:
```
ERROR: Module not found
Solution: Ensure virtual environment is activated and dependencies installed
```

**Permission errors**:
```
ERROR: Permission denied
Solution: Check file permissions or run with appropriate privileges
```

## 💡 MONITORING TIPS

1. **Watch for Progress**: Look for [X/Y] indicators
2. **Check Timestamps**: Monitor task durations
3. **Review Errors**: Read error messages carefully
4. **Use Checkpoints**: Note checkpoint files for resume capability

## 🎬 EXAMPLE EXECUTION

```bash
$ /execute

============================================================
EXECUTOR STARTED
Requirement: Fix all 29 tests to pass
Total Tasks: 31
Execution Mode: Sequential
============================================================

[1/31] Starting: Discover all test files
       Executing: find tests -name "test_*_real.py" -type f | sort
       Found 29 test files
       ✅ SUCCESS - Discover all test files (0.5s)

[2/31] Starting: Check current test status
       Executing: pytest tests/ -v --tb=no | grep -E "(PASSED|FAILED|ERROR)"
       Current status: 6 passing, 23 failing
       ✅ SUCCESS - Check current test status (3.2s)

[3/31] Starting: Run test_statistical_validation_real.py
       Executing: pytest tests/test_statistical_validation_real.py -xvs
       ✅ Test PASSED (8/8)
       ✅ SUCCESS - Run test_statistical_validation_real.py (5.1s)

... continuing with remaining tasks ...

============================================================
EXECUTION COMPLETE
Duration: 15.3 minutes
Success Rate: 87.1% (27/31 tasks)
Report saved to: executor_report_20250112_143052.json
============================================================
```

## 🔐 COMPLETE SAFETY PROTOCOL

**BEFORE EXECUTION**:
```bash
/commit with message: "checkpoint(pre-execute): Save state before running executor"
```

**AFTER EXECUTION**:
```bash
# Based on results
/commit with appropriate message (see Post-Execution section)
```

**EXECUTE NOW** - Create safety checkpoint, activate environment, and run the executor...