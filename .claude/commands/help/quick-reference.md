---
title: "Quick Reference"
status: active
type: command
last_verified: 2026-02-19
grade: reference
---

# Quick Reference - Emergency Patterns and Daily Shortcuts

## Daily Startup Checklist ⚡

### Essential First 5 Commands (ALWAYS)
```bash
# 1. Activate Serena (MANDATORY FIRST)
mcp__serena__activate_project("my-project")

# 2. Check configuration
mcp__serena__get_current_config()

# 3. Clean up completed tasks (maintains clarity and performance)
/usr/bin/python3 cleanup_tasks.py

# 4. Clean up planning document if needed (maintains focus and readability)
/usr/bin/python3 cleanup_planning.py

# 5. Get initial instructions
mcp__serena__initial_instructions()
```

### Immediate Task Context
```bash
# Check assigned work
"List tasks from Tasks.csv where Assignee='Claude' and Status='To Do'"

# Check current work in progress  
"Show tasks from Tasks.csv where Assignee='Claude' and Status='In Progress'"

# Read project context
# Read Planning.md for current status
```

## Emergency Commands 🚨

### When Things Go Wrong
```python
# Language server issues
mcp__serena__restart_language_server()

# Check if project is still active
mcp__serena__get_current_config()

# Re-activate if needed
mcp__serena__activate_project("my-project")

# Check available memories
mcp__serena__list_memories()
```

### Blocked or Confused
```python
# Think about what you've collected
mcp__serena__think_about_collected_information()

# Verify you're on track
mcp__serena__think_about_task_adherence()

# Check if work is complete
mcp__serena__think_about_whether_you_are_done()
```

### Git Issues
```bash
# Check status
git status

# See recent commits for context
git log --oneline -10

# Check differences
git diff
```

## Serena Mode Quick Reference

### Mode Switching for Task Types
```python
# Solution design and planning
mcp__serena__switch_modes(["planning", "one-shot"])

# Implementation and coding
mcp__serena__switch_modes(["editing", "interactive"])

# Ongoing collaborative work
mcp__serena__switch_modes(["interactive", "editing"])
```

### Current Mode Check
```python
# See what modes are active
mcp__serena__get_current_config()
# Look for "Active modes:" in output
```

## Quick Research Patterns

### Fast Colleague Consultation
```python
# Quick technical question
mcp__perplexity__perplexity_ask([{
    "role": "user",
    "content": "Quick question about [SPECIFIC_TOPIC]"
}])

# Current documentation/tools
mcp__brave-search__brave_web_search("topic 2025", count=5)
```

### Framework Quick Reference
```python
# Find library
mcp__context7__resolve-library-id("library_name")

# Get specific docs
mcp__context7__get-library-docs("/org/project", topic="feature")
```

## Task Management Shortcuts

### Quick Task Updates
```bash
# Start work
"Update task 42 in Tasks.csv: Status='In Progress', Start Date='2025-06-28'"

# Mark complete
"Update task 42 in Tasks.csv: Status='Done', Description='[BRIEF_SUMMARY]'"

# Mark blocked
"Update task 42 in Tasks.csv: Status='Blocked', Description='[BLOCKER_DETAILS]'"
```

### Task Queries
```bash
# My current work
"Show tasks from Tasks.csv where Assignee='Claude' and Status='In Progress'"

# Upcoming deadlines
"Show tasks from Tasks.csv where Due Date<='2025-07-05' and Status!='Done'"

# Check dependencies
"Show all tasks from Tasks.csv where Parent Task=42"
```

## Code Analysis Quick Patterns

### Progressive Search Strategy
```python
# 1. Overview first (ALWAYS)
mcp__serena__get_symbols_overview("relative_path")

# 2. Find specific symbols
mcp__serena__find_symbol("class_name", relative_path="src/")

# 3. Understand usage
mcp__serena__find_referencing_symbols("symbol_name", "file.py")

# 4. Read file only when necessary
mcp__serena__read_file("file.py", limit=50, offset=100)
```

### Precision Editing
```python
# Replace symbol implementation
mcp__serena__replace_symbol_body("function_name", "file.py", "new_implementation")

# Add after symbol
mcp__serena__insert_after_symbol("class_name", "file.py", "new_method")

# Add before symbol  
mcp__serena__insert_before_symbol("function_name", "file.py", "new_code")
```

## LLM-First Quick Decisions

### When to Use Agents vs Code
**Use Agents For:** Pattern matching, fuzzy text, decisions, entity resolution, natural language
**Use Code For:** Math, dates, validation, API calls, deterministic logic

### Quick Agent Pattern
```python
# Always use structured outputs
class Result(BaseModel):
    answer: str
    confidence: float
    reasoning: str

result = await agent.run(prompt, output_type=Result)
```

### Anti-Pattern Alerts 🚫
- ❌ Never manually call tools (`_execute_tool()`)
- ❌ Never create mocks (`return {"mock": "data"}`)
- ❌ Never constrain agents (hardcoded tool selection)
- ❌ Never skip MCP lifecycle (`run_mcp_servers()`)

## Testing Quick Checks

### Before Completing Any Task
```bash
# Run linting (if available)
ruff check . || pylint . || echo "No linter found"

# Run type checking (if available)  
mypy . || echo "No type checker found"

# Test functionality
python test_basic_functionality.py || echo "Create basic test"
```

### Quality Gates
- ✅ **Functionality works** as specified
- ✅ **No breaking changes** to existing code
- ✅ **Tests pass** (existing + new)
- ✅ **Lint/typecheck clean** 
- ✅ **Integration verified**

## Completion Protocol Quick Steps

### Sacred Three Steps (NEVER SKIP)
```bash
# 1. Update Tasks.csv
"Update task [ID] in Tasks.csv: Status='Done', Description='[COMPLETE_SUMMARY]'"

# 2. Update Planning.md (manually edit file)

# 3. Send webhook (MANDATORY)
curl -X POST https://hook.us1.make.com/7hcfkou8f6riberxcixom46kxoihv1d3 \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "message": "Task [ID]: [SUMMARY]", "task_id": "[ID]"}'
```

## Command Discovery

### Available Slash Commands
```bash
# All commands
/project:help/list-commands

# Integration
/project:integration/serena-mcp

# Workflows  
/project:workflow/processes
/project:workflow/completion-protocol
/project:workflow/research-colleagues

# Development
/project:development/llm-first-architecture
/project:development/testing-protocol

# Task Management
/project:management/task-csv
```

### Command Usage
```bash
# Use tab completion
/project:<TAB>

# Chain commands
/project:workflow/research-colleagues | /project:development/llm-first-architecture

# Use arguments
/project:integration/serena-mcp setup
/project:workflow/research-colleagues both
```

## Performance Quick Tips

### Serena Performance
- Use `get_symbols_overview()` before specific searches
- Use symbol operations instead of reading entire files
- Read memories selectively, not all at once
- Switch modes appropriately for task type

### Agent Performance
- Load complete datasets instead of filtering
- Use structured outputs with Pydantic
- Keep prompts clear and specific
- Use confidence scores for fallback logic

## Common Error Recovery

### Serena Issues
```python
# Symbol not found
# → Check file path and symbol name spelling
# → Use get_symbols_overview() to discover available symbols

# Language server errors
# → Use mcp__serena__restart_language_server()
# → Re-activate project if necessary

# Memory issues
# → Use mcp__serena__list_memories() to see what's available
# → Read only relevant memories for current task
```

### Agent Issues
```python
# No tool visibility in terminal
# → Ensure using async with agent.run_mcp_servers()
# → Check for manual tool orchestration
# → Verify MCP server configuration

# Low confidence results
# → Improve prompt clarity and context
# → Add examples to prompts
# → Use fallback chains for low confidence
```

### Task Management Issues
```bash
# Can't find task
# → Check Task ID spelling
# → Verify task exists: "Show task [ID] from Tasks.csv"

# Dependency issues
# → Check parent tasks: "Show all tasks where Parent Task=[ID]"
# → Verify parent task is complete before starting
```

## O3-Pro Quick Launch

### Basic O3-Pro Workflow
```bash
# Launch with chat control
python codex-o3-pro-model-support/start_o3_controlled.py "Task description" 60

# Wait for initialization (CRITICAL)
sleep 120

# Check progress every 2-3 minutes
python codex-o3-pro-model-support/check_o3_progress.py SESSION_ID

# Extract results when complete
python codex-o3-pro-model-support/check_o3_progress.py SESSION_ID --extract
```

## Command Line Usage

### Use with argument support
```bash
/project:help/quick-reference daily      # Daily workflow patterns
/project:help/quick-reference emergency  # Emergency procedures
/project:help/quick-reference patterns   # Common patterns and shortcuts
```

## Pro Tips ⚡

### Efficiency Hacks
- **Batch tool calls** when possible for parallel execution
- **Use command chaining** for complex workflows  
- **Switch Serena modes** based on task type
- **Research with colleagues** before implementing
- **Use sequential thinking** for complex problems

### Quality Shortcuts
- **Symbol-level navigation** instead of reading full files
- **Structured agent outputs** with Pydantic models
- **Progressive search strategy** (overview → symbols → targeted reading)
- **Test incrementally** as you build
- **Document insights** in task descriptions

### Avoid Common Mistakes
- Don't read entire files when you need specific symbols
- Don't skip research phase - always consult colleagues
- Don't manually orchestrate tools - let agents decide
- Don't create mock implementations - use real integrations
- Don't skip completion protocol - webhook is mandatory

**⚡ Keep this reference handy for daily development and emergency situations!**