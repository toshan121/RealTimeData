---
allowed-tools: all
description: Create orchestrated task execution plan for complex workflows
---

# Orchestrate Command

Generate a comprehensive task execution plan based on requirements: $ARGUMENTS

## Analysis Phase

1. Read provided documentation to understand current state
2. Perform Five Whys analysis to identify root causes
3. Design precise tasks that address core issues
4. Create intelligent execution sequence with parallel opportunities

## Output

Generate `./tasks/orchestrate_plan.md` containing the execution plan, and write the cc-executor command to `./tasks/orchestrate_command.txt` for the hook to execute:

### Project Context
- Clear description of current state
- Specific issues to be resolved
- Success criteria for completion

### Task Sequence
- Phase-based execution plan
- Tasks designed for first-time success
- Clear dependencies and prerequisites
- Parallel execution opportunities identified

### Execution Format
Each task includes:
- **Objective**: What needs to be accomplished
- **Context**: Relevant files and documentation
- **Expected Output**: Specific deliverables
- **Success Criteria**: How to verify completion

## Design Principles

- Address root causes, not symptoms
- Create self-contained, executable tasks
- Minimize dependencies between tasks
- Include comprehensive context for each task
- Design for reliability and first-time success