---
allowed-tools: all
description: Create a safety checkpoint commit before and after destructive operations
---

# 🔐 COMMIT COMMAND - Safety Checkpoint System

This command creates git commits as safety checkpoints before and after potentially destructive operations. It's automatically called by other commands that modify the codebase.

## 🎯 PURPOSE

Create atomic, well-documented commits that serve as:
1. **Safety checkpoints** before destructive operations
2. **Progress markers** after successful operations
3. **Recovery points** if something goes wrong

## 📋 WORKFLOW

### When Called Manually: `/commit`
1. Check git status and identify changes
2. Create a descriptive commit with context
3. Push to remote if requested

### When Called by Other Commands: 
Commands like `/ground-truth`, `/plan`, and `/execute` will call this automatically:
- **BEFORE**: Create safety checkpoint
- **AFTER**: Commit results of the operation

## 🚀 EXECUTION STEPS

### Step 1: Git Status Check
```bash
# Check current state
git status --porcelain

# If no changes
if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi
```

### Step 2: Determine Commit Type
Analyze the context to determine commit type:
- `checkpoint`: Safety commit before operation
- `update`: Documentation or minor changes
- `feat`: New features or capabilities
- `fix`: Bug fixes or corrections
- `refactor`: Code structure improvements
- `test`: Test additions or fixes
- `docs`: Documentation updates

### Step 3: Create Commit Message
Format: `type(scope): description [context]`

Examples:
- `checkpoint(pre-operation): Save state before /ground-truth documentation update`
- `docs(ground-truth): Update all documentation to match implementation reality`
- `feat(executor): Add sequential task executor for test fixing`
- `test(validation): Fix failing tests and update test counts`

### Step 4: Stage and Commit
```bash
# Stage specific files or all changes
git add -A  # Or specific files based on operation

# Create commit with descriptive message
git commit -m "type(scope): description [context]"
```

## 🔄 INTEGRATION WITH OTHER COMMANDS

### `/ground-truth` Integration
```markdown
BEFORE:
/commit with message: "checkpoint(pre-ground-truth): Save state before documentation reality check"

AFTER:
/commit with message: "docs(ground-truth): Update documentation to match implementation [GROUND-TRUTH-REPORT]"
```

### `/plan` Integration
```markdown
BEFORE:
/commit with message: "checkpoint(pre-plan): Save state before creating executor for: $ARGUMENTS"

AFTER:
/commit with message: "feat(executor): Create sequential executor for: $ARGUMENTS"
```

### `/execute` Integration
```markdown
BEFORE:
/commit with message: "checkpoint(pre-execute): Save state before running executor"

AFTER (if successful):
/commit with message: "fix(tests): Complete executor run - X/Y tasks successful"

AFTER (if failed):
/commit with message: "wip(executor): Partial executor run - X/Y tasks completed"
```

## 📊 COMMIT MESSAGE PATTERNS

### Pre-Operation Checkpoints
Always use `checkpoint` type:
```
checkpoint(pre-command): Save state before [operation description]
```

### Post-Operation Results
Based on what was accomplished:
```
docs(scope): Update documentation...
feat(scope): Add new capability...
fix(scope): Resolve issues...
test(scope): Update/fix tests...
refactor(scope): Improve structure...
```

## 🎯 SPECIAL CONTEXTS

### For Test Fixing Operations
```
# Before
checkpoint(pre-tests): Save state before fixing 29 test files

# After Success
test(all): Fix all 29 test files - 100% passing

# After Partial
test(partial): Fix 15/29 test files - continuing work needed
```

### For Documentation Updates
```
# Before
checkpoint(pre-docs): Save state before ground-truth analysis

# After
docs(reality): Update all .md files with actual implementation status
```

### For Feature Implementation
```
# Before
checkpoint(pre-feature): Save state before implementing [feature]

# After
feat(module): Implement [feature] with full test coverage
```

## 🚨 SAFETY FEATURES

### Conflict Prevention
```bash
# Always pull latest before committing
git pull --rebase

# If conflicts exist
if [ $? -ne 0 ]; then
    echo "⚠️  Conflicts detected. Resolve before committing."
    exit 1
fi
```

### Change Validation
```bash
# Show what will be committed
git diff --staged --stat

# Confirm with user for large changes
if [ $(git diff --staged --numstat | wc -l) -gt 50 ]; then
    echo "⚠️  Large changeset detected (50+ files)"
    echo "Continue with commit? (y/n)"
    # Wait for confirmation
fi
```

## 💡 BEST PRACTICES

1. **Atomic Commits**: Each commit should represent one logical change
2. **Clear Context**: Include WHY the change was made
3. **Reference Commands**: Mention which command triggered the commit
4. **Include Metrics**: Add success/failure counts where relevant

## 🔧 OPTIONS

### Manual Invocation
```bash
/commit "custom commit message"
/commit --push  # Also push to remote
/commit --amend  # Amend previous commit
```

### Automatic Context
When called by other commands, context is automatically provided:
- Command that triggered it
- Operation being performed
- Success/failure status
- Relevant metrics

## 📝 COMMIT LOG EXAMPLE

```
feat(executor): Create sequential executor for test fixing
checkpoint(pre-execute): Save state before running executor
test(validation): Fix test_statistical_validation_real.py - 8/8 passing
test(market-cap): Fix test_market_cap_real.py - 9/9 passing
checkpoint(progress): Save progress - 2/29 tests fixed
test(all): Complete test fixing - 29/29 tests passing
docs(status): Update TEST_PROGRESS_STATUS.md with final results
```

**REMEMBER**: Every destructive operation should be bracketed by commits for safety and traceability.