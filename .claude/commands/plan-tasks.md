---
allowed-tools: all
description: Create intelligent parallel cc_executor task files based on project documentation and user requirements
---

# Plan Tasks Command

Create task execution files based on requirements: $ARGUMENTS

## Analysis Phase

1. Read the provided documentation files to understand current state
2. Perform Five Whys analysis to identify root causes
3. Design tasks that address root causes with precision
4. Identify which tasks can run in parallel safely (max 3 concurrent)

## Output Files

Generate two files in ./tasks/:

### 1. run_example.py
A Python script using cc_executor library with:
- Smart parallel execution (max 3 concurrent)
- Dependency-aware scheduling  
- Mixed execution patterns (direct vs cc_execute)
- Context file references
- Error recovery and validation

### 2. task_list.md (ORCHESTRATE format)
A markdown file containing the cc-executor ORCHESTRATE command that can be run with:
```bash
cc-executor run "claude -p '[ORCHESTRATE content from task_list.md]'"
```

## Key Principles

- Address root causes, not symptoms
- Design for first-time success (cc_executor tasks are expensive)
- Max 3 concurrent tasks to prevent resource conflicts
- Only parallelize truly independent tasks
- Include comprehensive context for each task
- Provide clear success/failure criteria
- Database operations are serialized or use different tables
- API calls are rate-limited appropriately
- Git operations are atomic and non-conflicting

### Phase 4: ULTRATHINK Design Phase
After root cause analysis, say: "Now let me ultrathink about the optimal task execution plan that will succeed on first try..."

Consider:
- What are the TRUE dependencies between tasks (verified, not assumed)?
- What's the precise execution order that addresses root causes correctly?
- Which context files provide the EXACT information each task needs?
- What are ALL potential failure points and how to design around them?
- What specific tools and permissions does each task require?
- How to make each task self-validating and robust?
- What edge cases could break each task and how to handle them?
- Are task instructions detailed enough to succeed without iteration?

### Phase 5: PRECISION Task Design for First-Time Success

**🎯 High-Quality Task Creation Principles:**
- Each task addresses a verified, specific problem with precision
- Include comprehensive context and all information needed
- Design tasks that are robust against common failure modes
- Provide detailed success/failure criteria for each task
- Include specific error handling and edge case management
- Make tasks self-documenting with clear reasoning
- Ensure each task can validate its own success

### Phase 5b: CONTEXT FILE ASSIGNMENT for Each Task

**📚 Documentation Context Selection:**
For EACH task, carefully select relevant .md files that provide necessary context:

**For Testing Tasks:**
- `seeking_alpha_research/STANDALONE_FEATURES_DOCUMENTATION.md` - Current feature status
- `seeking_alpha_research/DATABASE_FIX_UPDATE.md` - Recent fixes and issues
- `tests/conftest.py` documentation (if exists)
- `CLAUDE.md` - Testing philosophy and standards

**For Data Collection Tasks:**
- `specs.md` - API specifications and endpoints
- `seeking_alpha_research/core/data_service.py` documentation
- API-specific documentation files
- `CLAUDE.md` - Integration patterns

**For Analysis Tasks:**
- `specs.md` - Business logic and calculations
- `seeking_alpha_research/analysis/` module documentation
- Statistical methodology documentation
- Previous analysis results

**For Infrastructure Tasks:**
- `CLAUDE.md` - System architecture and patterns
- `seeking_alpha_research/core/` module documentation
- Configuration and setup documentation
- Database schema documentation

**🎯 Context Selection Principles:**
1. **Relevance**: Only include files directly relevant to the task
2. **Completeness**: Include all files needed for understanding
3. **Specificity**: Choose specific sections over entire files when possible
4. **Currency**: Prefer recently updated documentation
5. **Hierarchy**: Include both high-level (CLAUDE.md) and specific docs

### Phase 6: Create run_example.py

Generate a run_example.py following the ADVANCED cc_executor pattern with INTELLIGENT PARALLEL EXECUTION:

```python
#!/usr/bin/env python3
"""
[User's requirement description]
Generated on: [CURRENT DATE]

This demonstrates advanced cc_executor patterns with intelligent parallel execution:
- Smart parallel execution (max 3 concurrent tasks)
- Dependency-aware task scheduling
- Mixed execution patterns (direct vs cc_execute)
- Context file references for better understanding
- Comprehensive execution tracking and summaries
- UUID verification and error recovery
- Branch-safe parallelization
"""

import sys
import os
from pathlib import Path
import json
from datetime import datetime
import time
import asyncio
import concurrent.futures
from typing import List, Dict, Any, Optional, Set
import threading
from dataclasses import dataclass

# Set up working directory (adjust path as needed for your project)
project_root = Path(__file__).resolve().parent.parent
os.chdir(str(project_root))
print(f"Working directory: {os.getcwd()}")

# Add cc_executor to path if it exists locally
cc_executor_local = project_root / 'lib/cc_executor/src'
if cc_executor_local.exists():
    sys.path.insert(0, str(cc_executor_local))

from cc_executor.prompts.cc_execute_utils import execute_task_via_websocket

@dataclass
class TaskResult:
    task_id: str
    task_name: str
    success: bool
    duration: float
    execution_type: str
    verification_status: str
    output_file: Optional[str] = None
    error: Optional[str] = None

class ParallelTaskExecutor:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.results: Dict[str, TaskResult] = {}
        self.completed_tasks: Set[str] = set()
        self.lock = threading.Lock()
    
    def can_execute_task(self, task: dict, dependency_graph: Dict[str, List[str]]) -> bool:
        """Check if all dependencies for a task are completed."""
        task_deps = dependency_graph.get(task['id'], [])
        return all(dep in self.completed_tasks for dep in task_deps)
    
    def mark_task_completed(self, task_id: str):
        """Mark a task as completed in thread-safe manner."""
        with self.lock:
            self.completed_tasks.add(task_id)
    
    def get_ready_tasks(self, tasks: List[dict], dependency_graph: Dict[str, List[str]]) -> List[dict]:
        """Get tasks that are ready to execute (dependencies satisfied)."""
        ready = []
        for task in tasks:
            if (task['id'] not in self.completed_tasks and 
                task['id'] not in [r.task_id for r in self.results.values()] and
                self.can_execute_task(task, dependency_graph)):
                ready.append(task)
        return ready

    async def execute_task(self, task: dict) -> TaskResult:
        """Execute a single task and return result."""
        task_start = time.time()
        task_id = task['id']
        task_name = task['name']
        
        print(f"\n🚀 Starting Task {task_id}: {task_name}")
        print(f"   Execution: {task['execution'].upper()}")
        print(f"   Thread: {threading.current_thread().name}")
        
        try:
            if task['execution'] == 'direct':
                result = execute_direct_task(task['desc'], task.get('timeout', 60))
            else:
                result = execute_task_via_websocket(
                    task=task['desc'],
                    timeout=task.get('timeout', 300),
                    tools=task.get('tools', ["Read", "Write", "Edit", "Bash", "TodoWrite"])
                )
            
            task_duration = time.time() - task_start
            success = result.get('success', False)
            
            # Handle verification status
            verification_status = "N/A"
            if task['execution'] == 'cc_execute' and 'hook_verification' in result:
                verification_passed = result['hook_verification'].get('verification_passed', False)
                verification_status = "🔐 VERIFIED" if verification_passed else "⚠️ NOT VERIFIED"
            
            # Save result to file
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = Path("tmp/responses")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"task_{task_id}_{timestamp}.json"
            
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            
            task_result = TaskResult(
                task_id=task_id,
                task_name=task_name,
                success=success,
                duration=task_duration,
                execution_type=task['execution'],
                verification_status=verification_status,
                output_file=str(output_file),
                error=result.get('error')
            )
            
            status_icon = "✅" if success else "❌"
            print(f"{status_icon} Task {task_id} completed in {task_duration:.1f}s")
            
            if success:
                self.mark_task_completed(task_id)
            
            return task_result
            
        except Exception as e:
            task_duration = time.time() - task_start
            error_msg = f"Task {task_id} failed with exception: {e}"
            print(f"❌ {error_msg}")
            
            return TaskResult(
                task_id=task_id,
                task_name=task_name,
                success=False,
                duration=task_duration,
                execution_type=task['execution'],
                verification_status="ERROR",
                error=str(e)
            )

def execute_direct_task(task_desc: str, timeout: int = 60) -> dict:
    """
    Execute a task directly without cc_execute.
    This is for simple tasks that don't need fresh context.
    """
    print("📡 Executing directly (no cc_execute needed)...")
    
    # For direct tasks, you would implement the logic here
    # This is typically for simple tool calls or quick operations
    
    return {
        'success': True,
        'output_lines': [
            "Direct execution completed successfully",
            "Used for simple operations that don't need fresh context"
        ],
        'direct_execution': True
    }

def analyze_task_dependencies(tasks: List[dict]) -> Dict[str, List[str]]:
    """Analyze task dependencies for intelligent parallelization."""
    dependency_graph = {}
    
    for task in tasks:
        task_id = task['id']
        dependencies = []
        
        # File-based dependencies
        task_files = set(task.get('file_dependencies', []))
        task_resources = set(task.get('resource_dependencies', []))
        
        for other_task in tasks:
            if other_task['id'] == task_id:
                continue
                
            other_files = set(other_task.get('file_dependencies', []))
            other_resources = set(other_task.get('resource_dependencies', []))
            
            # Check for file conflicts (both modify same file)
            if task_files & other_files:
                dependencies.append(other_task['id'])
                continue
            
            # Check for resource conflicts (both use same external resource)
            if task_resources & other_resources:
                # Only sequential if both are write operations
                if (task.get('resource_operation', 'read') == 'write' and 
                    other_task.get('resource_operation', 'read') == 'write'):
                    dependencies.append(other_task['id'])
                    continue
            
            # Check for explicit dependencies
            if other_task['id'] in task.get('depends_on', []):
                dependencies.append(other_task['id'])
        
        dependency_graph[task_id] = dependencies
    
    return dependency_graph

def validate_task_necessity(task: dict, previous_results: list) -> tuple[bool, str]:
    """
    Intelligent validation to check if this task is still necessary.
    Uses root cause analysis results to avoid redundant work.
    Returns (should_execute, reason)
    """
    task_name = task['name']
    addresses_root_cause = task.get('addresses_root_cause')
    validation_check = task.get('validation_check')
    
    print(f"🔍 Validating necessity of: {task_name}")
    
    # Check if root cause already solved by previous tasks
    if addresses_root_cause:
        solved_causes = set(r.get('solved_root_cause') for r in previous_results if r.get('solved_root_cause'))
        if addresses_root_cause in solved_causes:
            return False, f"Root cause '{addresses_root_cause}' already solved by previous task"
    
    # Run specific validation check if provided
    if validation_check:
        print(f"   Running validation: {validation_check}")
        # This would run a specific check - in practice, you'd implement the actual validation
        # For demo purposes, we assume the validation check determines if task is needed
        
    print(f"   → Validation: Task needed - proceeding with execution")
    return True, "Task validation passed - execution necessary"

def check_early_termination(results: list, remaining_tasks: list) -> tuple[bool, str]:
    """
    Check if we can terminate early because the main problem is solved.
    Returns (should_terminate, reason)
    """
    # Get all root causes that have been solved
    solved_causes = set(r.get('solved_root_cause') for r in results if r.get('solved_root_cause'))
    
    if not solved_causes:
        return False, "No root causes solved yet - continue execution"
    
    # Check if remaining tasks only address already-solved root causes
    remaining_critical_tasks = [t for t in remaining_tasks if t.get('critical', False)]
    remaining_unsolved_causes = set()
    
    for task in remaining_tasks:
        task_root_cause = task.get('addresses_root_cause')
        if task_root_cause and task_root_cause not in solved_causes:
            remaining_unsolved_causes.add(task_root_cause)
    
    # If no critical tasks remain and no new root causes to solve, terminate early
    if not remaining_critical_tasks and not remaining_unsolved_causes:
        return True, f"All root causes solved: {solved_causes}. No critical tasks remaining."
    
    return False, f"Still have {len(remaining_unsolved_causes)} unsolved root causes and {len(remaining_critical_tasks)} critical tasks"

def validate_task_before_execution(task: dict) -> tuple[bool, str]:
    """
    Pre-execution validation to ensure task has everything needed to succeed.
    This catches design flaws BEFORE expensive execution.
    Returns (ready_to_execute, validation_message)
    """
    task_name = task['name']
    
    print(f"🔍 Pre-execution validation: {task_name}")
    
    # Check task has clear objectives
    if not task.get('success_criteria'):
        return False, "Task missing success criteria - execution would be ambiguous"
    
    # Check task has sufficient context
    desc = task.get('desc', '')
    if len(desc) < 200:
        return False, "Task description too brief - likely missing critical context"
    
    # Check task addresses a specific problem
    if not task.get('addresses_root_cause'):
        return False, "Task doesn't specify what root cause it addresses - unclear objective"
    
    # Check task has failure mitigation
    if 'edge_cases' not in desc and 'error handling' not in desc.lower():
        return False, "Task missing error handling guidance - likely to fail on edge cases"
    
    print(f"   ✅ Task ready for execution: {task_name}")
    return True, "Pre-execution validation passed - task ready for high-quality execution"

def log_execution_quality_metrics(task: dict, result: dict, duration: float):
    """
    Track execution quality to improve future task design.
    """
    success = result.get('success', False)
    retry_count = result.get('attempts', 1)
    
    print(f"📊 Execution Quality Metrics:")
    print(f"   Task: {task['name']}")
    print(f"   Success: {success}")
    print(f"   Duration: {duration:.1f}s")
    print(f"   Retry count: {retry_count}")
    print(f"   First-try success: {success and retry_count == 1}")
    
    # Quality indicators
    if success and retry_count == 1 and duration < task.get('timeout', 300):
        print(f"   🌟 HIGH QUALITY: Task succeeded on first try within expected time")
    elif success and retry_count > 1:
        print(f"   ⚠️  MEDIUM QUALITY: Task succeeded but required {retry_count} attempts")
    elif not success:
        print(f"   ❌ LOW QUALITY: Task failed - task design may need improvement")
    
    return {
        'quality_score': 100 if (success and retry_count == 1) else 50 if success else 0,
        'first_try_success': success and retry_count == 1,
        'execution_efficiency': min(100, (task.get('timeout', 300) / max(duration, 1)) * 100)
    }

async def execute_parallel_waves(executor: ParallelTaskExecutor, tasks: List[dict], 
                                 dependency_graph: Dict[str, List[str]]) -> Dict[str, TaskResult]:
    """Execute tasks in parallel waves based on dependencies."""
    all_results = {}
    
    while len(executor.completed_tasks) < len(tasks):
        # Get tasks ready for execution
        ready_tasks = executor.get_ready_tasks(tasks, dependency_graph)
        
        if not ready_tasks:
            # Check if we're stuck due to failed dependencies
            remaining_tasks = [t for t in tasks if t['id'] not in executor.completed_tasks]
            if remaining_tasks:
                print(f"\n⚠️ No more tasks can be executed. Remaining tasks may have failed dependencies.")
                for task in remaining_tasks:
                    deps = dependency_graph.get(task['id'], [])
                    failed_deps = [d for d in deps if d not in executor.completed_tasks]
                    if failed_deps:
                        print(f"   Task {task['id']} blocked by: {failed_deps}")
            break
        
        # Limit concurrent tasks
        batch = ready_tasks[:executor.max_concurrent]
        
        if len(batch) == 1:
            print(f"\n🔄 Executing task {batch[0]['id']} (sequential)")
        else:
            task_ids = [t['id'] for t in batch]
            print(f"\n⚡ Executing {len(batch)} tasks in parallel: {', '.join(task_ids)}")
        
        # Execute batch in parallel using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
            future_to_task = {pool.submit(asyncio.run, executor.execute_task(task)): task for task in batch}
            
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    all_results[result.task_id] = result
                    executor.results[result.task_id] = result
                    
                    if not result.success:
                        print(f"\n❌ Task {result.task_id} failed: {result.error}")
                        print("⚠️ Continuing with remaining tasks...")
                        
                except Exception as e:
                    print(f"\n💥 Task {task['id']} crashed with exception: {e}")
        
        # Small delay between waves
        if executor.completed_tasks and len(executor.completed_tasks) < len(tasks):
            await asyncio.sleep(2)
    
    return all_results

def main():
    """Execute the task list for: [USER'S REQUIREMENT] with intelligent parallel execution"""
    print("="*80)
    print("CC Executor - Intelligent Parallel Task Execution")
    print("[USER'S REQUIREMENT]")
    print("="*80)
    print("\nThis execution demonstrates:")
    print("- Smart parallel execution (max 3 concurrent)")
    print("- Dependency-aware task scheduling")
    print("- Root cause analysis and problem validation")
    print("- Intelligent task necessity checking")
    print("- Mixed execution patterns (direct vs cc_execute)")
    print("- Context file references")
    print("- Comprehensive tracking and verification")
    print("- Branch-safe parallelization")
    
    # Configuration
    MAX_CONCURRENT_TASKS = 3  # Max parallel tasks
    MAX_TASK_TIMEOUT = 600   # 10 minutes max per task (safety limit)
    
    # Check for resume capability
    checkpoint_file = Path("tmp/execution_checkpoint.json")
    start_from_task = 1
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, 'r') as f:
                checkpoint = json.load(f)
            last_completed = checkpoint.get('last_completed_task', 0)
            start_from_task = last_completed + 1
            print(f"\n🔄 RESUMING from task {start_from_task} (checkpoint found)")
        except Exception as e:
            print(f"\n⚠️ Checkpoint file corrupted, starting from beginning: {e}")
    
    def save_checkpoint(completed_task_num: int, results: list):
        """Save execution checkpoint for resume capability"""
        checkpoint_data = {
            'timestamp': datetime.now().isoformat(),
            'last_completed_task': completed_task_num,
            'total_tasks': len(tasks),
            'results_summary': [
                {
                    'task': r['task'],
                    'status': r['status'],
                    'success': r['success'],
                    'duration': r['duration']
                } for r in results
            ]
        }
        try:
            checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)
            print(f"   💾 Checkpoint saved at task {completed_task_num}")
        except Exception as e:
            print(f"   ⚠️ Failed to save checkpoint: {e}")
    
    def cleanup_on_exit():
        """Clean up resources and save final state"""
        try:
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                print("   🧹 Execution checkpoint cleaned up")
        except Exception as e:
            print(f"   ⚠️ Cleanup failed: {e}")
    
    # Trap interruptions gracefully
    import signal
    def signal_handler(signum, frame):
        print(f"\n\n🛑 EXECUTION INTERRUPTED (signal {signum})")
        print("Saving current state and exiting gracefully...")
        if 'results' in locals():
            save_checkpoint(len(results), results)
        cleanup_on_exit()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # ROOT CAUSE ANALYSIS RESULTS (from Five Whys)
    print("\n🔍 ROOT CAUSE ANALYSIS:")
    print("Problem: [User's stated problem]")
    print("Root Cause: [Identified root cause from Five Whys analysis]")
    print("Key Insight: [Why this approach will solve the real problem]")
    
    # Define tasks based on ROOT CAUSE analysis with intelligent parallelization
    tasks = [
        {
            'id': 'task_1',  # Unique identifier for dependency tracking
            'name': 'Task Name',
            'execution': 'cc_execute',  # or 'direct'
            'addresses_root_cause': 'root_cause_identifier',  # Links to specific root cause from Five Whys
            'validation_check': 'specific_check_to_see_if_needed',  # How to validate if task is necessary
            'success_criteria': 'Specific measurable criteria that indicate this task succeeded',
            'parallel_group': 'group_a',  # Tasks in same group can run in parallel
            'file_dependencies': ['path/to/file1.py', 'path/to/file2.md'],  # Files this task modifies
            'resource_dependencies': ['database', 'api_service'],  # External resources needed
            'desc': '''[Detailed task description that addresses ROOT CAUSE, not symptoms.

ROOT CAUSE ADDRESSED: [Specific root cause this task solves from Five Whys analysis]

Five Whys Context:
- Problem: [Original symptom/issue]
- Root Cause: [Fundamental cause identified through Five Whys]
- Why This Task: [How this task specifically addresses the root cause]

Context files that help with this task:
- /path/to/relevant/doc1.md - [Why this helps with root cause]
- /path/to/relevant/doc2.md - [Why this helps with root cause]

Task-specific instructions:
1. [Step 1 - focused on root cause, not symptoms]
2. [Step 2 - focused on root cause, not symptoms]  
3. [Step 3 - focused on root cause, not symptoms]

Error handling and edge cases:
- [Common failure mode 1 and how to handle it]
- [Common failure mode 2 and how to handle it]
- [Validation steps to ensure success]

Success criteria: [How we know the root cause is addressed]
Expected output: [What success looks like]
Validation method: [How to verify this task actually solved the problem]''',
            'timeout': 180,  # 3 minutes default
            'context_note': 'Why this task addresses the root cause',
            'expected_files': ['output1.py', 'output2.md'],
            'tools': ["Read", "Write", "Edit", "Bash", "TodoWrite"],
            'critical': True  # Is this task critical for solving the root cause?
        },
        # ... more tasks designed around root causes
    ]
    
    # Create dependency graph for intelligent parallelization
    dependency_graph = analyze_task_dependencies(tasks)
    print(f"\n🧠 DEPENDENCY ANALYSIS:")
    for task_id, deps in dependency_graph.items():
        if deps:
            print(f"   Task {task_id} depends on: {', '.join(deps)}")
        else:
            print(f"   Task {task_id} has no dependencies (can run immediately)")
    
    # Create parallel executor
    executor = ParallelTaskExecutor(max_concurrent=MAX_CONCURRENT_TASKS)
    
    # Track execution
    start_time = time.time()
    
    print(f"\n🚀 Starting intelligent parallel execution (max {MAX_CONCURRENT_TASKS} concurrent tasks)")
    
    # Execute tasks in parallel waves
    try:
        results = asyncio.run(execute_parallel_waves(executor, tasks, dependency_graph))
    except KeyboardInterrupt:
        print(f"\n🛑 Execution interrupted by user")
        print(f"Completed tasks: {list(executor.completed_tasks)}")
        return
    except Exception as e:
        print(f"\n💥 Execution failed with exception: {e}")
        return
        # Skip tasks if resuming from checkpoint
        if task['num'] < start_from_task:
            print(f"⏭️ SKIPPING Task {task['num']} (already completed in previous run)")
            continue
        
        # 🔍 INTELLIGENT VALIDATION: Check if this task is still necessary
        should_execute, validation_reason = validate_task_necessity(task, results)
        
        if not should_execute:
            print(f"\n⏭️ SKIPPING Task {task['num']}: {task['name']}")
            print(f"   Reason: {validation_reason}")
            # Mark as skipped but successful (problem already solved)
            results.append({
                'task': task['name'],
                'execution': 'skipped',
                'status': 'skipped',
                'success': True,
                'verification': 'N/A',
                'duration': 0.0,
                'skip_reason': validation_reason,
                'solved_root_cause': task.get('addresses_root_cause')
            })
            save_checkpoint(task['num'], results)
            continue
        
        # 🎯 EARLY TERMINATION CHECK: Can we stop early?
        remaining_tasks = tasks[i+1:]
        should_terminate, termination_reason = check_early_termination(results, remaining_tasks)
        
        if should_terminate:
            print(f"\n🏁 EARLY TERMINATION: {termination_reason}")
            print(f"   Skipping remaining {len(remaining_tasks)} tasks")
            break
        print(f"\n{'='*80}")
        print(f"Task {task['num']}: {task['name']}")
        print(f"Execution Mode: {task['execution'].upper()}")
        print(f"{'='*80}")
        print(f"Context: {task.get('context_note', 'N/A')}")
        print(f"Timeout: {task['timeout']}s")
        print(f"\nTask description:")
        print(task['desc'][:200] + "..." if len(task['desc']) > 200 else task['desc'])
        
        task_start = time.time()
        
        # Apply timeout safety limit
        safe_timeout = min(task.get('timeout', 300), MAX_TASK_TIMEOUT)
        if safe_timeout != task.get('timeout', 300):
            print(f"   ⚠️ Timeout reduced from {task.get('timeout')}s to {safe_timeout}s (safety limit)")
        
        # Choose execution method with error handling
        try:
            if task['execution'] == 'direct':
                # Direct execution (no cc_execute)
                print(f"\n🚀 Executing directly (simple task, no fresh context needed)...")
                result = execute_direct_task(task['desc'], safe_timeout)
            else:
                # Use cc_execute for complex tasks
                print(f"\n🔄 Executing via cc_execute (complex task, needs fresh context)...")
                print(f"   Timeout: {safe_timeout}s")
                print(f"   Tools: {task.get('tools', ['Read', 'Write', 'Edit', 'Bash', 'TodoWrite'])}")
                result = execute_task_via_websocket(
                    task=task['desc'],
                    timeout=safe_timeout,
                    tools=task.get('tools', ["Read", "Write", "Edit", "Bash", "TodoWrite"])
                )
        except KeyboardInterrupt:
            print(f"\n🛑 Task {task['num']} interrupted by user")
            save_checkpoint(task['num'] - 1, results)  # Save up to previous task
            raise
        except Exception as e:
            print(f"\n❌ Task {task['num']} failed with exception: {e}")
            result = {
                'success': False,
                'error': str(e),
                'output_lines': [f"Task failed with exception: {e}"],
                'exception_type': type(e).__name__
            }
        
        task_duration = time.time() - task_start
        
        # Save result
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path("tmp/responses")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = output_dir / f"task_{task['num']}_{timestamp}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        # Extract status
        success = result.get('success', False)
        status = 'success' if success else 'failed'
        
        # Check for UUID verification (only for cc_execute tasks)
        verification_status = "N/A"
        if task['execution'] == 'cc_execute' and 'hook_verification' in result:
            verification_passed = result['hook_verification'].get('verification_passed', False)
            verification_status = "🔐 VERIFIED" if verification_passed else "⚠️ NOT VERIFIED"
            
            # Show verification details
            print(f"\nUUID Verification: {verification_status}")
            if result['hook_verification'].get('messages'):
                for msg in result['hook_verification']['messages']:
                    print(f"  {msg}")
        
        # Check if expected files were created
        files_created = []
        for expected_file in task.get('expected_files', []):
            if Path(expected_file).exists():
                files_created.append(expected_file)
        
        # Determine if this task solved its root cause
        solved_root_cause = None
        if success and task.get('addresses_root_cause'):
            solved_root_cause = task['addresses_root_cause']
            print(f"  🎯 Root Cause Addressed: {solved_root_cause}")
        
        results.append({
            'task': task['name'],
            'execution': task['execution'],
            'status': status,
            'success': success,
            'verification': verification_status,
            'duration': task_duration,
            'expected_files': task.get('expected_files', []),
            'files_created': files_created,
            'solved_root_cause': solved_root_cause,
            'addresses_root_cause': task.get('addresses_root_cause'),
            'critical': task.get('critical', False)
        })
        
        # Task summary
        print(f"\n{'✅' if success else '❌'} Task Result:")
        print(f"  Status: {status}")
        print(f"  Duration: {task_duration:.1f}s")
        print(f"  Expected files: {task.get('expected_files', [])}")
        print(f"  Files created: {files_created}")
        if task['execution'] == 'cc_execute':
            print(f"  UUID Verification: {verification_status}")
        print(f"  Output saved: {output_file}")
        
        # Save checkpoint after each task
        save_checkpoint(task['num'], results)
        
        if not success:
            print(f"\n❌ Task failed. Stopping execution.")
            print(f"💾 Progress saved. Run script again to resume from task {task['num'] + 1}")
            break
        
        # Delay between tasks (except for the last task)
        if i < len(tasks) - 1:
            print(f"\n⏳ Waiting {DELAY_BETWEEN_TASKS}s before next task...")
            time.sleep(DELAY_BETWEEN_TASKS)
    
    # Overall summary
    total_duration = time.time() - start_time
    print(f"\n{'='*80}")
    print("EXECUTION SUMMARY")
    print(f"{'='*80}")
    print(f"Total execution time: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    print(f"\nTask Results:")
    
    for i, r in enumerate(results, 1):
        status_icon = "✅" if r['success'] else "❌"
        exec_type = "📡 Direct" if r['execution'] == 'direct' else "🔄 cc_execute"
        
        print(f"\n{status_icon} Task {i}: {r['task']}")
        print(f"   Execution: {exec_type}")
        print(f"   Duration: {r['duration']:.1f}s")
        print(f"   Files: {r['files_created']}")
        if r['execution'] == 'cc_execute':
            print(f"   Verification: {r['verification']}")
    
    # Pattern demonstration
    print(f"\n{'='*80}")
    print("PATTERNS DEMONSTRATED")
    print(f"{'='*80}")
    
    direct_tasks = sum(1 for r in results if r['execution'] == 'direct')
    cc_execute_tasks = sum(1 for r in results if r['execution'] == 'cc_execute')
    
    print(f"📡 Direct execution: {direct_tasks} task(s)")
    print("   - Used for simple operations")
    print("   - No fresh context needed")
    print("   - No UUID verification")
    
    print(f"\n🔄 cc_execute pattern: {cc_execute_tasks} task(s)")
    print("   - Used for complex generation")
    print("   - Fresh 200K context per task")
    print("   - Automatic UUID4 verification")
    print("   - WebSocket keeps long tasks alive")
    
    # ROOT CAUSE ANALYSIS SUMMARY
    print(f"\n{'='*80}")
    print("🎯 ROOT CAUSE ANALYSIS RESULTS")
    print(f"{'='*80}")
    
    executed_tasks = [r for r in results if r['status'] != 'skipped']
    skipped_tasks = [r for r in results if r['status'] == 'skipped']
    solved_root_causes = set(r['solved_root_cause'] for r in results if r['solved_root_cause'])
    
    print(f"Tasks executed: {len(executed_tasks)}")
    print(f"Tasks skipped (intelligent): {len(skipped_tasks)}")
    print(f"Root causes addressed: {len(solved_root_causes)}")
    print(f"Time saved by skipping: {len(skipped_tasks) * 180:.0f}s (~{len(skipped_tasks) * 3:.0f} minutes)")
    
    if solved_root_causes:
        print(f"\n✅ Root causes successfully addressed:")
        for cause in solved_root_causes:
            print(f"   - {cause}")
    
    if skipped_tasks:
        print(f"\n⏭️ Tasks intelligently skipped:")
        for task in skipped_tasks:
            print(f"   - {task['task']}: {task['skip_reason']}")
    
    # Efficiency insights
    print(f"\n{'='*80}")
    print("🚀 INTELLIGENT EXECUTION INSIGHTS")
    print(f"{'='*80}")
    print("1. Root cause analysis prevented symptom-chasing")
    print("2. Intelligent validation avoided unnecessary work")
    print("3. Early termination saved time when problems were solved")
    print("4. Sequential execution with delays prevented context overlap")
    print("5. Mixed execution patterns optimized for task complexity")
    print("6. Context file references improved task understanding")
    print("7. Comprehensive tracking enabled better debugging")
    
    if all(r['success'] for r in executed_tasks):
        print(f"\n🎉 All necessary tasks completed successfully!")
        print(f"\n📊 Execution Efficiency:")
        print(f"   - Total tasks planned: {len(tasks)}")
        print(f"   - Tasks executed: {len(executed_tasks)}")
        print(f"   - Tasks skipped: {len(skipped_tasks)}")
        print(f"   - Efficiency gain: {len(skipped_tasks)/len(tasks)*100:.1f}% time saved")
        print(f"\nExecution completed with {DELAY_BETWEEN_TASKS}s delays between tasks")
        print("Results saved to tmp/responses/ directory")
    
    # Clean up checkpoint file on successful completion
    cleanup_on_exit()

if __name__ == "__main__":
    main()
```

### Phase 5: Create task_list.md

Generate a task_list.md documenting the ADVANCED plan with mixed execution and comprehensive tracking:

```markdown
# [USER'S REQUIREMENT] - Advanced Task Execution Plan

Generated on: [DATE]

## Overview
[Brief description of what this task list accomplishes]

This execution plan demonstrates advanced cc_executor patterns:
- **Sequential execution** with configurable delays (default: 5 seconds)
- **Mixed execution patterns** (direct vs cc_execute) for optimal efficiency
- **Context file references** for better task understanding
- **Comprehensive tracking** with UUID verification and file validation

## Tasks

### Task 1: [Task Name]
**Execution Mode**: `cc_execute` (or `direct`)
**Purpose**: [Why this task is needed]
**Timeout**: 180 seconds
**Delay After**: 5 seconds

**Context Files**: 
- `/path/to/relevant/doc1.md` - [Why this helps with task understanding]
- `/path/to/relevant/doc2.md` - [Additional context provided]
- `/path/to/relevant/code.py` - [Existing implementation to reference]

**Expected Files**:
- `output1.py` - [What this file should contain]
- `output2.md` - [What this file should contain]

**Tools Needed**: ["Read", "Write", "Edit", "Bash", "TodoWrite"]

**Task Description**:
[The exact prompt that will be sent to Claude via cc_execute.md]

**Execution Strategy**: 
- Uses cc_execute for fresh 200K context
- UUID verification ensures authenticity  
- File creation validated post-execution

### Task 2: [Task Name]
**Execution Mode**: `direct`
**Purpose**: [Simple operation that doesn't need fresh context]
**Timeout**: 60 seconds
**Delay After**: 5 seconds

**Context Files**: 
- `/path/to/simple/ref.md` - [Quick reference needed]

**Expected Files**: []

**Tools Needed**: ["Read"]

**Task Description**:
[Simple operation that can be done without cc_execute]

**Execution Strategy**: 
- Direct execution for efficiency
- No UUID verification needed
- Quick operation completion

### Task 3: [Task Name]
[Similar advanced structure...]

## Advanced Execution Strategy

### 1. Mixed Execution Patterns
- **cc_execute tasks**: Complex generation, file creation, analysis
  - Fresh 200K token context per task
  - UUID4 verification for authenticity
  - WebSocket reliability for long operations
- **Direct tasks**: Simple tool calls, quick queries, status checks
  - No context isolation needed
  - Faster execution for simple operations
  - No verification overhead

### 2. Sequential Dependencies with Delays
- **5-second delays** between tasks prevent context overlap
- **Task dependencies**: Each task can reference outputs from previous tasks
- **Configurable timing**: Delays can be adjusted based on system load
- **Resumable execution**: Tasks can be restarted from any point

### 3. Comprehensive Tracking
- **Duration monitoring**: Track time spent on each task
- **File validation**: Verify expected outputs are created
- **UUID verification**: Ensure cc_execute tasks are authentic
- **Error recovery**: Detailed logging for debugging failures

### 4. Context File Integration
- **Documentation references**: Tasks include relevant .md files for context
- **Code references**: Existing implementations guide new development
- **Pattern consistency**: Follow established codebase patterns

## Why This Advanced Plan?

1. **Efficiency**: Mixed execution optimizes for task complexity
2. **Reliability**: UUID verification and error recovery
3. **Maintainability**: Clear tracking and documentation
4. **Scalability**: Sequential execution with proper delays
5. **Context Awareness**: Rich context file references

## Execution Patterns Demonstrated

### 📡 Direct Execution (Fast Path)
- Simple MCP tool calls
- Quick status checks
- File existence verification  
- No fresh context needed

### 🔄 cc_execute Pattern (Reliable Path)
- Complex code generation
- Multi-step analysis tasks
- File creation and editing
- Fresh context with verification

## Potential Risks & Advanced Mitigations

- **Risk**: Task timeout due to complexity
  **Mitigation**: Configurable timeouts, WebSocket keeps connections alive

- **Risk**: Context overlap between tasks
  **Mitigation**: Sequential execution with mandatory delays

- **Risk**: UUID verification failure
  **Mitigation**: Automatic retry with fresh context, detailed error logging

- **Risk**: File creation verification failure
  **Mitigation**: Post-task validation with specific file checks

- **Risk**: Mixed execution pattern confusion
  **Mitigation**: Clear execution mode documentation and consistent patterns

## Performance Characteristics

- **Total execution time**: Approximately [estimated] minutes
- **Tasks with delays**: Add 5 seconds between each task
- **cc_execute overhead**: Fresh context initialization (~2-3 seconds)
- **Direct execution speed**: Near-instantaneous for simple operations
- **Verification time**: UUID checking adds ~1 second per cc_execute task

## Debugging and Monitoring

- **Output files**: All results saved to `tmp/responses/task_N_timestamp.json`
- **Console logging**: Real-time progress with timestamps and status
- **UUID verification**: Detailed verification messages for cc_execute tasks
- **File tracking**: Created vs expected file comparison
- **Pattern demonstration**: Summary of execution patterns used
```

## 🎯 KEY ADVANCED DESIGN PRINCIPLES

1. **Mixed Execution Strategy**: Choose optimal execution method per task
   - `cc_execute` for complex generation, analysis, and file creation
   - `direct` for simple tool calls and quick operations
2. **Sequential with Delays**: 5-second delays between tasks prevent context overlap
3. **Fresh Context When Needed**: cc_execute tasks get clean 200K token context
4. **Context File Integration**: Reference relevant .md files for better understanding
5. **Comprehensive Tracking**: Monitor duration, files, verification, and patterns
6. **UUID Verification**: Automatic authenticity checking for cc_execute tasks
7. **File Validation**: Verify expected outputs are actually created
8. **Error Recovery**: Detailed logging and resumable execution
9. **Pattern Demonstration**: Show execution patterns and performance insights

## 📊 EXPECTED ADVANCED OUTPUT

After running /plan, you will:

1. **Present the Advanced Execution Plan** with mixed patterns and timing
2. **Create `./tasks/run_example.py`** - Advanced execution script with:
   - Mixed execution patterns (direct vs cc_execute)
   - Configurable delays between tasks (default: 5 seconds)
   - Comprehensive tracking and verification
   - UUID verification for cc_execute tasks
   - File validation and pattern demonstration
3. **Create `./tasks/task_list.md`** - Detailed documentation with:
   - Execution mode specifications per task
   - Context file references
   - Expected output validation
   - Advanced risk mitigation strategies
4. **Explain Advanced Next Steps**:
```markdown
## Advanced Execution Guide

### 1. Review Generated Files
- `./tasks/run_example.py` - Advanced execution script
- `./tasks/task_list.md` - Comprehensive task documentation

### 2. Execute with Monitoring
```bash
cd ./tasks && python run_example.py
```

### 3. Advanced Monitoring Features
- **Real-time progress**: Console output with timestamps and status
- **UUID verification**: Automatic authenticity checking
- **File validation**: Expected vs created file tracking
- **Pattern insights**: Execution pattern analysis
- **Duration tracking**: Per-task and total execution time

### 4. Output Analysis
- **Results directory**: `tmp/responses/task_N_timestamp.json`
- **Execution summary**: Pattern demonstration and performance metrics
- **Verification status**: UUID and file validation results
- **Error recovery**: Detailed logging for debugging

### 5. Advanced Features
- **Configurable delays**: Modify DELAY_BETWEEN_TASKS variable
- **Mixed execution**: Tasks automatically choose optimal execution method
- **Context awareness**: Rich context file integration
- **Resumable execution**: Continue from any failed task
```

## 🚨 IMPORTANT NOTES

- **DO NOT EXECUTE** - This command only creates the plan files
- **USE ULTRATHINK** - Deep reasoning for optimal task design
- **FOLLOW CC_EXECUTOR PATTERN** - Use the existing pattern from basic/run_example.py
- **CLEAR PROMPTS** - Each task desc should be a complete, self-contained prompt
- **SEQUENTIAL ONLY** - No parallel execution

## 🔑 Task Design Guidelines

For different types of requirements:

**Testing Tasks** (IMPORTANT: Include working directory instructions):
```python
{
    'num': 1,
    'name': 'Discover and Categorize Test Files',
    'desc': '''Find all test files in the project that match common patterns (test_*.py, *_test.py).
    For each file, check if it can be imported without errors.
    Run tests on each file to categorize failures:
    1. PASSING - All tests pass
    2. IMPORT_ERROR - Cannot import modules
    3. CONFIG_ERROR - Configuration or setup issues
    4. API_ERROR - External API connection problems
    5. DATABASE_ERROR - Database connection or migration issues
    
    Create a detailed summary showing:
    - Total test files found
    - Category breakdown with counts
    - Specific error messages for failed files
    - Recommendations for fixing each category
    
    This analysis will guide the fix prioritization strategy.''',
    'timeout': 300
}
```

**Configuration Fixing Tasks**:
```python
{
    'num': 2,
    'name': 'Fix Configuration and Setup Issues',
    'desc': '''For files identified with CONFIG_ERROR in the previous step:
    1. Identify missing configuration files or environment variables
    2. Fix Django settings if Django is used (DJANGO_SETTINGS_MODULE, database config)
    3. Resolve any database connection or migration issues
    4. Fix missing dependencies or import path problems
    5. Verify configuration fixes by running tests again
    
    For each fix:
    - Document what was changed and why
    - Test that the specific error is resolved
    - Ensure no new errors are introduced
    
    This systematic approach ensures configuration issues are resolved properly.''',
    'timeout': 480
}
```

**Implementation Tasks**:
```python
{
    'num': 3,
    'name': 'Implement Missing Features',
    'desc': '''Based on project requirements and any missing functionality identified:
    1. Review project documentation to understand what features are needed
    2. Implement missing features following existing code patterns
    3. Add proper error handling and logging
    4. Create appropriate tests for new functionality
    5. Validate that implementation works with existing system
    
    For each feature implemented:
    - Follow existing code style and patterns
    - Add comprehensive error handling
    - Document any design decisions made
    - Test integration with existing components
    
    This ensures new features are properly integrated and maintainable.''',
    'timeout': 600
}
```

Remember: Each task description becomes the ENTIRE prompt sent to a fresh Claude instance via cc_executor.

## 🚀 BEGIN PLANNING

Start by analyzing the user's requirements, then ultrathink about the optimal task sequence with intelligent parallelization...