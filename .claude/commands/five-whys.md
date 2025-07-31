---
allowed-tools: all
description: Apply the Five Whys root cause analysis technique to investigate issues
---

# 🔍 FIVE WHYS ANALYSIS - Root Cause Investigation

Apply the Five Whys root cause analysis methodology to drill down from symptoms to fundamental causes.

## 🎯 Purpose
This command implements systematic problem-solving by iteratively asking "why" to identify the true root cause behind issues, rather than just addressing surface-level symptoms.

## 📋 Usage
When you have a problem, symptom, or issue that needs deep analysis.

**Input**: The problem or symptom to analyze: $ARGUMENTS

## 🔄 Methodology

### Phase 1: Problem Definition
1. **Clearly state the problem**: What exactly is happening?
2. **Gather context**: When, where, how often does this occur?
3. **Define impact**: What are the consequences of this problem?

### Phase 2: Five Whys Analysis
Systematically ask "Why?" for each answer:

**Problem Statement**: [Initial issue from $ARGUMENTS]

**Why #1**: Why did this happen?
- **Answer**: [Direct cause]

**Why #2**: Why did [Answer #1] happen?
- **Answer**: [Underlying cause]

**Why #3**: Why did [Answer #2] happen?  
- **Answer**: [Deeper cause]

**Why #4**: Why did [Answer #3] happen?
- **Answer**: [Systemic cause]

**Why #5**: Why did [Answer #4] happen?
- **Answer**: [Root cause]

### Phase 3: Root Cause Validation
1. **Test the logic**: Work backwards from root cause to problem
2. **Check for multiple causes**: Are there parallel root causes?
3. **Verify actionability**: Can we actually address this root cause?

### Phase 4: Solution Design
1. **Address the root cause** (not just symptoms)
2. **Design preventive measures** to stop recurrence
3. **Implement monitoring** to detect early warning signs

## 📊 Output Format

```markdown
# Five Whys Analysis: [Problem]

## Problem Statement
**Issue**: [Clear description]
**Context**: [When/where/frequency]
**Impact**: [Consequences]

## Five Whys Chain
1. **Why**: [Question] → **Because**: [Answer]
2. **Why**: [Question] → **Because**: [Answer]  
3. **Why**: [Question] → **Because**: [Answer]
4. **Why**: [Question] → **Because**: [Answer]
5. **Why**: [Question] → **Because**: [Answer]

## Root Cause Identified
**Primary Root Cause**: [Fundamental issue]
**Secondary Causes**: [If any parallel causes exist]

## Validation Check
- ✅ Logic test: [Root cause → symptom chain verified]
- ✅ Actionability: [Can be addressed with available resources]
- ✅ Prevention potential: [Addressing this will prevent recurrence]

## Recommended Solutions
### Immediate Actions (Address Root Cause)
1. [Action to fix root cause]
2. [Action to fix root cause]

### Preventive Measures  
1. [Action to prevent recurrence]
2. [Action to prevent recurrence]

### Monitoring
1. [Early warning indicator]
2. [Success metric]
```

## 💡 Examples

### Example 1: Technical Issue
```
Problem: Application crashes on startup
Why 1: Database connection fails → Because connection string is invalid
Why 2: Connection string is invalid → Because environment variable not set  
Why 3: Environment variable not set → Because deployment script missing env setup
Why 4: Deployment script missing env setup → Because documentation didn't specify requirements
Why 5: Documentation incomplete → Because no review process for deployment docs

Root Cause: Missing deployment documentation review process
```

### Example 2: Process Issue  
```
Problem: Features deployed with bugs
Why 1: Bugs not caught in testing → Because tests are incomplete
Why 2: Tests incomplete → Because requirements unclear to testers
Why 3: Requirements unclear → Because specifications not reviewed
Why 4: Specifications not reviewed → Because no review process defined
Why 5: No review process → Because team priorities focus only on delivery speed

Root Cause: Team incentives prioritize speed over quality processes
```

## 🚨 Important Notes

- **Don't stop at exactly 5**: Stop when you reach the true root cause (could be 3, could be 7)
- **Avoid assumptions**: Base each "why" on evidence, not speculation
- **Multiple branches**: Some problems have multiple root causes - explore different paths
- **Focus on systems**: Look for process/system issues, not just individual mistakes
- **Be actionable**: Ensure the identified root cause can actually be addressed

## 🎯 Integration with /plan Command

The Five Whys analysis integrates with the `/plan` command to create smarter task execution:
1. Use `/five-whys` to identify root causes
2. Use `/plan` to create tasks that address those root causes (not symptoms)
3. Result: More efficient execution with fewer unnecessary tasks

## 🔄 When to Use

**Perfect for**:
- Recurring problems
- Complex technical issues  
- Process breakdowns
- Quality problems
- Performance issues
- Team/workflow problems

**Not ideal for**:
- Simple, obvious fixes
- One-time accidents
- Well-understood problems
- Urgent firefighting (do this after immediate fixes)

---

**Remember**: The goal is finding the **fundamental cause** that, when addressed, prevents the problem from recurring. Surface fixes only create temporary relief.