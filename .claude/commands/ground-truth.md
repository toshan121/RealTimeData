---
allowed-tools: all
description: Research project reality and update all documentation to match current implementation state
---

# 🔍 GROUND-TRUTH COMMAND - Documentation Reality Check

**CRITICAL**: This command ensures all documentation reflects the ACTUAL state of the project, not aspirations or outdated information.

**IMPORTANT**: 
1. This is a READ-ONLY analysis command. DO NOT EXECUTE any code, tests, or scripts.
2. DO NOT CREATE NEW FILES - only update existing documentation
3. Mark deprecated content for eventual removal
4. Verify .md files are actual documentation before updating

## 🔄 CACHING AND FORCE FLAG

### Cache Check (NEW!)
Before starting the ground-truth analysis, check if a recent analysis exists:

```bash
# Check for cached ground-truth
cache_file="/Users/toshan/PycharmProjects/stk_v5/.claude/cache/ground-truth-timestamp.txt"
force_flag="${1:-}"

# If --force flag is provided, skip cache check
if [[ "$force_flag" == "--force" ]]; then
    echo "🔄 Force flag detected - bypassing cache"
else
    # Check if cache exists and is less than 1 hour old
    if [[ -f "$cache_file" ]]; then
        last_run=$(cat "$cache_file")
        current_time=$(date +%s)
        time_diff=$((current_time - last_run))
        
        if [[ $time_diff -lt 3600 ]]; then
            echo "✅ Ground-truth was run $(($time_diff / 60)) minutes ago"
            echo "📝 Cache file: $cache_file"
            echo "Use '/ground-truth --force' to force a new analysis"
            exit 0
        fi
    fi
fi

# Record new timestamp
date +%s > "$cache_file"
echo "🔍 Starting ground-truth analysis at $(date)"
```

## 📋 MANDATORY SEQUENCE

1. **CHECK CACHE**: Verify if analysis needed (unless --force)
2. **COMMIT CHECKPOINT**: Run `/commit` with message: `checkpoint(pre-ground-truth): Save state before documentation reality check`
3. **DISCOVER** all .md files using Glob to find documentation
4. **VALIDATE** each .md file is actual documentation (not data/config)
5. **SCAN** the codebase to understand current reality
6. **UPDATE** existing .md files to match ground truth (DO NOT create new files)
7. **DEPRECATE** outdated content with clear markers
8. **UPDATE CACHE**: Record completion timestamp
9. **COMMIT RESULTS**: Run `/commit` with message: `docs(ground-truth): Update documentation to match implementation`

## 🎯 YOUR MISSION

You will perform a comprehensive audit of the Gap-Up ATM Trading Strategy project and update ALL documentation to reflect reality.

### Step 0: Cache Management (NEW!)

**FIRST, check the cache**:
```bash
# Read the cache check code above
# If cache is fresh and no --force flag, exit early
# Otherwise, proceed with full analysis
```

**Create cache timestamp file**:
```bash
echo "$(date +%s)" > /Users/toshan/PycharmProjects/stk_v5/.claude/cache/ground-truth-timestamp.txt
echo "Ground-truth completed at: $(date)" > /Users/toshan/PycharmProjects/stk_v5/.claude/cache/ground-truth-last-run.log
```

### Step 1: Codebase Analysis (READ ONLY)
```
READ and analyze these directories systematically:
- /seeking_alpha_research/ (main implementation)
- /seeking_alpha_research/tests/ (test coverage and status)
- /seeking_alpha_research/django_prototype_v0/ (UI implementation)
- All Python modules and their actual functionality

USE ONLY: Read, Glob, Grep, LS tools
DO NOT: Execute Python code, run tests, or call APIs
```

### Step 2: Find and Validate Documentation Files

**First, DISCOVER all .md files** in the project:
```bash
# Use Glob to find all markdown files
glob "**/*.md"
```

**Then VALIDATE each .md file** is actually documentation:
- Check if it contains documentation content (not data/config)
- Look for headers, descriptions, usage instructions
- Identify purpose: README, API docs, feature docs, etc.

**CATEGORIZE documentation files**:
1. **Project-level docs** (README.md, CLAUDE.md, specs.md)
2. **Feature documentation** (STANDALONE_FEATURES_DOCUMENTATION.md)
3. **Progress tracking** (TEST_PROGRESS_STATUS.md)
4. **Usage guides** (CLI_USAGE.md)
5. **Auto-generated** (test reports, logs - DO NOT UPDATE)
6. **Third-party** (library docs - DO NOT UPDATE)

**UPDATE only genuine documentation**:
- Mark features with status codes: [IMPLEMENTED], [BROKEN], [PARTIAL], [MISSING]
- Add deprecation warnings: [DEPRECATED - to be removed]
- Remove fictional or aspirational content
- Update test counts based on file analysis

**DEPRECATION PROCESS**:
1. First pass: Mark outdated docs with `[DEPRECATED - <reason>]`
2. Second pass: Move deprecated content to archive section
3. Third pass: Delete if confirmed obsolete

**DO NOT CREATE NEW FILES** - only update existing documentation

### Step 3: Reality Checks (CODE INSPECTION ONLY)

**For EACH module/feature claimed in docs**, verify by reading:
- Does the file actually exist? (use LS/Glob)
- Are imports present and look valid? (read file headers)
- Are there real implementations or just placeholders? (read function bodies)
- Do test files exist for this module? (check tests/ directory)
- What API dependencies are imported? (analyze import statements)

**Common Documentation Lies to Fix**:
- "Fully implemented" when it's just a stub
- "Integrates with X" when integration is broken
- "Supports Y" when Y was never built
- Test counts that don't match pytest output
- Features that exist in docs but not in code

### Step 4: Test Verification

**READ test files and analyze** (DO NOT EXECUTE):
```
# DO NOT RUN pytest - only read and analyze test files
# Look for patterns in test files to understand coverage
```

Document by reading test files:
- Count of test files in tests/ directory
- Analyze test structure and patterns
- Identify which modules have test coverage
- Note test naming conventions and organization
- Look for real API usage patterns vs mock usage

### Step 5: Implementation Status Codes

Use these codes in all documentation:
- `[WORKING]` - Fully functional with real data
- `[PARTIAL]` - Some functionality works
- `[BROKEN]` - Exists but fails with real data
- `[STUB]` - Placeholder code only
- `[MISSING]` - Documented but not implemented
- `[DEPRECATED]` - No longer used/maintained

### Step 6: Critical Information to Capture

**Project Reality Summary** must include:
1. Total modules: How many actually exist and are importable
2. Working features: What actually processes real data successfully
3. Test coverage: Real numbers from pytest, not estimates
4. API integrations: Which ones actually connect and work
5. Database state: What tables exist, what data is stored
6. Django status: Which views work, which are broken
7. Known blockers: Specific errors preventing progress

## 🚨 FORBIDDEN BEHAVIORS

- ❌ NO optimistic estimates ("should work", "probably functional")
- ❌ NO keeping outdated feature descriptions
- ❌ NO fictional test counts or success rates
- ❌ NO ignoring import errors or runtime failures
- ❌ NO documentation of planned features as completed

## ✅ REQUIRED OUTPUTS

After running /ground-truth, you MUST have:

1. **Updated all .md files** to reflect actual state based on code inspection
2. **Clear status markers** on every feature based on implementation depth
3. **Accurate test counts** from counting test files (not execution)
4. **Honest assessment** of implementation completeness from code reading
5. **Actionable summary** of gaps identified through static analysis
6. **Updated cache timestamp** for future runs

## 📊 Documentation Update Summary

**DO NOT CREATE A NEW REPORT FILE** - Update existing documentation inline.

### Example Updates for Existing Files:

**In CLAUDE.md:**
```markdown
## 🔍 CURRENT PROJECT REALITY (Ground Truth as of YYYY-MM-DD)

### What Actually Works
- ✅ **Core Strategy Logic**: [IMPLEMENTED] Gap detection, SEC analysis
- ⚠️ **Data Pipeline**: [PARTIAL] Alpaca working, IB unverified
- ❌ **Django UI**: [BROKEN] Import errors in views

### Test Status Reality
- **Total test files**: 72 (counted via ls)
- **Confirmed passing**: 6/31 real data tests
- **Import errors**: ~15 files
```

**In specs.md:**
```markdown
1. download daily candles... `[IMPLEMENTED]`
2. stock universe <$100M... `[PARTIAL - delisted integration missing]`
3. Django visualization... `[BROKEN - view imports failing]`
```

**In STANDALONE_FEATURES_DOCUMENTATION.md:**
```markdown
## ⚠️ GROUND TRUTH WARNING
Previous claims unverified. Only these confirmed:
- ✅ Statistical Validation [WORKING - 8/8 tests pass]
- ❌ Corporate Actions [UNVERIFIED - no test execution]
- 🚫 Django UI [BROKEN - import errors]
```

**Deprecation Examples:**
```markdown
[DEPRECATED - Duplicate of specs.md content]
[DEPRECATED - Outdated, see CLAUDE.md for current status]
[DEPRECATED - To be removed after next ground-truth run]
```

## 🎯 SUCCESS CRITERIA

The /ground-truth command succeeds when:
- Every .md file has been updated based on code inspection
- Test file counts are accurate from directory listing
- All features have status codes based on implementation analysis
- No fictional or aspirational content remains
- New developers can understand what appears implemented vs stubbed
- Cache timestamp is updated for future reference

**REMEMBER**: This is about TRUTH, not hope. Document what IS, not what SHOULD BE. Money is on the line - false documentation could lead to financial losses.

## 🔐 SAFETY PROTOCOL

**BEFORE STARTING**: 
```bash
# Check cache first
if cache is fresh and no --force flag:
    exit early
else:
    /commit with message: "checkpoint(pre-ground-truth): Save state before documentation reality check"
```

**AFTER COMPLETION**:
```bash
# Update cache
echo "$(date +%s)" > /Users/toshan/PycharmProjects/stk_v5/.claude/cache/ground-truth-timestamp.txt

# Commit changes
/commit with message: "docs(ground-truth): Update documentation to match implementation [GROUND-TRUTH-REPORT dated YYYY-MM-DD]"
```

Begin systematic analysis NOW...