---
title: "Processes"
status: active
type: command
last_verified: 2026-02-19
grade: reference
---

# Complete Development Workflows and Research Protocols

## Core Development Process

### Task-Driven Development Workflow
1. **Task Context & Planning** - Always start here
2. **Research & Collaboration** - Use AI colleagues before coding
3. **Deep Thinking & Analysis** - Use sequential thinking for complex problems
4. **Implementation Discipline** - Follow LLM-first architecture principles
5. **Testing & Validation** - Comprehensive testing before completion
6. **Completion Protocol** - Sacred three steps with webhook

## Phase 1: Task Context & Planning

### Initial Context Gathering
```bash
# 1. Activate Serena project (ALWAYS FIRST)
mcp__serena__activate_project("my-project")

# 2. Check configuration and onboarding
mcp__serena__check_onboarding_performed()
mcp__serena__get_current_config()

# 3. Read task assignment
# Read Tasks.csv immediately for assigned work
# Check Planning.md for project context
```

### Task Selection Protocol
1. **Query Tasks.csv** for assigned "To Do" tasks
2. **Check parent task dependencies** are completed
3. **Select highest priority** task based on Due Date
4. **Update task Status** to "In Progress" and Start Date to current date
5. **Set appropriate Serena mode** for task type

### Serena Mode Selection
```python
# For solution design and planning
mcp__serena__switch_modes(["planning", "one-shot"])

# For implementation and coding
mcp__serena__switch_modes(["editing", "interactive"])

# For ongoing collaborative work
mcp__serena__switch_modes(["interactive", "editing"])
```

### Complex Task Breakdown
- **Use TodoWrite tool** for immediate task tracking (3+ steps)
- **Create subtasks in Tasks.csv** with Parent Task ID for complex work
- **Use sequential thinking** to analyze problems before implementation
- **Document your plan** in Planning.md before implementation

## Phase 2: Research & Collaboration Protocol

### Research-First Principle (MANDATORY)
- **ALWAYS research** implementation approaches with colleagues before coding
- **Check completed tasks** in Tasks.csv for similar implementations
- **Use search tools** to validate technical decisions and best practices
- **Research current API changes** and compatibility issues
- **Discuss architecture choices** and technology selection

### Colleague Research Patterns
```bash
# Use research colleagues command for detailed patterns
/project:workflow/research-colleagues [perplexity|brave|both]

# Standard research flow:
# 1. Perplexity for technical analysis
# 2. Brave Search for current documentation/tools
# 3. Context7 for framework-specific guidance
# 4. Validate findings with colleagues
```

### Context7 Framework Integration
```python
# 1. Resolve library first
mcp__context7__resolve-library-id("library_name")

# 2. Get documentation
mcp__context7__get-library-docs(
  context7CompatibleLibraryID="/org/project",
  topic="specific_feature"
)
```

## Phase 3: Deep Thinking & Analysis

### Sequential Thinking for Complex Problems
```python
# Use for complex architectural decisions
mcp__sequential-thinking__sequentialthinking(
  thought="Analysis of problem complexity...",
  nextThoughtNeeded=true,
  thoughtNumber=1,
  totalThoughts=5
)
```

### LLM-First Design Questions
Before implementing ANY feature, ask:
1. **Can an LLM understand this naturally?** (names, patterns, context)
2. **Is this deterministic logic?** (calculations, validations, rules)
3. **Does this require exact repeatability?** (compliance, auditing)
4. **Would loading complete data be more effective?** (vs filtering)
5. **Can the agent decide better than hardcoded rules?**

### Serena Semantic Analysis Protocol
```python
# Progressive search strategy
# 1. Overview first
mcp__serena__get_symbols_overview("relative_path")

# 2. Symbol discovery
mcp__serena__find_symbol("target_symbol", relative_path="src/")

# 3. Targeted reading only when necessary
mcp__serena__read_file("file.py", limit=50, offset=100)

# 4. Think about findings
mcp__serena__think_about_collected_information()
```

## Phase 4: Implementation Discipline

### Pre-Implementation Requirements
- **Verify task assignment** in Tasks.csv
- **Confirm parent tasks completed** if dependencies exist
- **CRITICAL: Request explicit user approval** before advancing from design to implementation
- **Read all relevant files** using Serena semantic analysis
- **Check existing patterns** from completed tasks
- **Verify required libraries** are installed
- **Research technology choices** with colleagues

### LLM-First Implementation Patterns
```python
# ✅ GOOD: Complete data loading with agent reasoning
csv_data = load_university_csv()  # Complete dataset
prompt = f"""
Universities available:
{csv_data}

Find the best match for: {university_name}
Handle variations naturally.
"""
result = await agent.run(prompt, output_type=StructuredResult)

# ❌ BAD: Hardcoded fuzzy matching
vector_results = await vector_search(name, threshold=0.5)
if vector_results:
    validation = await validate_match(query, vector_results[0])
```

### Natural Tool Integration (CRITICAL)
```python
# ✅ CORRECT: Natural agent integration
agent = Agent(model=model, mcp_servers=[...], system_prompt=prompt)
async with agent.run_mcp_servers():
    result = await agent.run(user_query)  # Agent decides tools naturally

# ❌ NEVER: Manual tool orchestration
if "university" in query:
    result = await call_verify_education_tool(query)
```

### Structured Output Patterns
```python
# Always use Pydantic models for agent responses
class UniversityMatch(BaseModel):
    university_name: str
    confidence: float
    reasoning: str
    database_id: Optional[int]

result = await agent.run(prompt, output_type=UniversityMatch)
```

## Phase 5: Testing & Validation

### Comprehensive Testing Protocol
```bash
# Use testing protocol command for detailed requirements
/project:development/testing-protocol [unit|integration|validation]

# Basic validation checklist:
# 1. Functionality works as expected
# 2. No breaking changes to existing code
# 3. Lint/typecheck errors resolved
# 4. Integration verified with dependent components
```

### Serena Testing Integration
```python
# Use symbol navigation for test understanding
mcp__serena__find_symbol("test_function", include_body=true)

# Use precision editing for test modifications
mcp__serena__replace_symbol_body("test_method", "test_file.py", "new_test_implementation")

# Verify testing with thinking tools
mcp__serena__think_about_whether_you_are_done()
```

## Phase 6: Completion Protocol

### Sacred Three Steps (MANDATORY)
```bash
# Use completion protocol command for detailed steps
/project:workflow/completion-protocol

# Essential flow:
# 1. Update Tasks.csv to "Done" with comprehensive description
# 2. Update Planning.md with current status and insights
# 3. Send completion webhook or face severe consequences
```

### Quality Validation Before Completion
- **Core requirements met** - All specified functionality implemented
- **Edge cases handled** - Error conditions addressed
- **Integration verified** - Works with existing system
- **Performance targets met** - Meets specified criteria
- **Tests pass** - All existing and new tests pass
- **Documentation updated** - Implementation notes captured

## Advanced Workflows

### O3-Pro Integration for Complex Tasks
```bash
# For complex solution design requiring deep analysis
python codex-o3-pro-model-support/start_o3_controlled.py "Task description" 60

# Monitor O3-Pro progress
python codex-o3-pro-model-support/check_o3_progress.py SESSION_ID

# Extract and apply findings
python codex-o3-pro-model-support/check_o3_progress.py SESSION_ID --extract
```

### Multi-Service Architecture Workflows
- **Main Orchestrator** (port 8000): Routes requests, coordinates services
- **User Chat Service** (port 5185): Knowledge base search, general support  
- **Education Verification** (port 5184): University credential verification
- **Redis Streaming**: Real-time progress updates via SSE

### Parallel Research Workflows
```bash
# Use Task tool for concurrent research
# Research with multiple colleagues simultaneously
# Combine findings for comprehensive understanding
# Validate approaches across different sources
```

## Emergency Procedures

### When Blocked
1. **Update task Status to "Blocked"** immediately
2. **Document blocker** in Description field with details
3. **Research with colleagues** for solutions
4. **Create blocker task** if resolution requires separate work
5. **Escalate to user** if unresolvable

### Error Recovery
```python
# Language server issues
mcp__serena__restart_language_server()

# Memory and context issues
mcp__serena__list_memories()  # Check available memories
mcp__serena__read_memory("relevant_memory")  # Read selectively

# Configuration verification
mcp__serena__get_current_config()
```

### Anti-Patterns to Avoid (CRITICAL)
- ❌ **Never constrain agents** - Let them decide tool usage naturally
- ❌ **Never create mock implementations** - Use real integrations
- ❌ **Never manually orchestrate tools** - Use natural agent reasoning
- ❌ **Never skip research phase** - Always consult colleagues first
- ❌ **Never ignore completion protocol** - Sacred three steps mandatory

## Integration with Other Commands

### Command Chaining for Complex Workflows
```bash
# Research → Architecture → Implementation → Testing → Completion
/project:workflow/research-colleagues | /project:development/llm-first-architecture | /project:development/testing-protocol | /project:workflow/completion-protocol

# Task Management → Serena Setup → Process Execution
/project:management/task-csv query | /project:integration/serena-mcp setup | /project:workflow/processes
```

**⚙️ Master these development workflows for systematic, high-quality implementation that leverages AI colleagues, semantic code analysis, and LLM-first architecture principles.**