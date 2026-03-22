---
title: "Setup"
status: active
type: command
last_verified: 2026-02-19
grade: reference
---

# Parallel Development Setup

## Initialize Multi-Process Development Environment

**Setup parallel development with git worktrees and Claude Code sub-processes for complex projects requiring concurrent workstreams.**

## Usage

```bash
/project:parallel/setup [feature-branch] [research-branch]
/project:parallel/setup feature/user-auth research/auth-patterns
/project:parallel/setup feature/payment-system feature/notification-system  
```

## What This Command Does

### 1. Pre-Flight Safety Checks
```bash
# Ensure clean git state
git status --porcelain || echo "Working directory must be clean"

# Verify main branch is up to date
git fetch origin
git status
```

### 2. Create Git Worktrees
```bash
# Create feature worktree
git worktree add ../my-project-feature feature/user-auth

# Create research worktree  
git worktree add ../my-project-research research/auth-patterns

# Verify worktrees created
git worktree list
```

### 3. Launch Claude Code Sub-Processes
```bash
# Launch in feature worktree
cd ../my-project-feature && claude-code --task "Implement user authentication system" &

# Launch in research worktree
cd ../my-project-research && claude-code --task "Research OAuth and JWT patterns" &
```

### 4. Create Coordination Infrastructure
```bash
# Create coordination directory
mkdir -p .parallel-coordination

# Track active worktrees
echo '{
  "worktrees": [
    {"name": "feature", "branch": "feature/user-auth", "path": "../my-project-feature", "task": "Implementation"},
    {"name": "research", "branch": "research/auth-patterns", "path": "../my-project-research", "task": "Research"}
  ],
  "created": "'$(date)'",
  "main_branch": "'$(git branch --show-current)'"
}' > .parallel-coordination/active-worktrees.json
```

## Advanced Usage

### Research + Implementation Workflow
```bash
# Setup research and implementation in parallel
/project:parallel/setup feature/vector-search research/vector-algorithms

# Research agent explores: Vector databases, algorithms, performance patterns
# Implementation agent builds: Production-ready vector search system
```

### TDD Parallel Development
```bash
# Setup test and development branches
/project:parallel/setup feature/user-service tests/user-service-tests

# Test agent writes: Comprehensive test suite
# Dev agent implements: Code to pass tests
```

### Multi-Feature Development
```bash
# Setup multiple independent features
/project:parallel/setup feature/authentication feature/payment-processing

# Both agents work on separate features simultaneously
# Coordination prevents conflicts and manages integration
```

## Safety Features

### Git Worktree Management
- **Clean State Check**: Ensures working directory is clean before setup
- **Branch Verification**: Confirms branches exist or creates them safely
- **Path Isolation**: Each worktree gets separate directory outside main project
- **Conflict Prevention**: Isolated working directories prevent interference

### Process Management
- **Background Processes**: Claude Code instances run as background processes
- **Process Tracking**: Coordination files track active processes and PIDs
- **Resource Monitoring**: Memory and CPU usage tracked per process
- **Graceful Shutdown**: Proper cleanup procedures for process termination

### Coordination Protocols
- **Task Assignment**: Clear task definition per worktree prevents overlap
- **Progress Tracking**: JSON files track completion status and dependencies
- **Merge Queue**: Manages merge order and conflict resolution
- **Communication**: Shared files enable cross-worktree coordination

## Integration with Other Commands

### Monitor Progress
```bash
# Check status of all parallel work
/project:parallel/status

# Shows: Active worktrees, process health, completion status
```

### Coordinate Merging
```bash
# Manage integration of parallel work
/project:parallel/merge-workflow

# Handles: Sync with main, resolve conflicts, merge order
```

### Cleanup Resources
```bash
# Remove completed worktrees and stop processes
/project:parallel/cleanup

# Cleans: Worktrees, processes, coordination files
```

## Error Handling

### Common Issues and Solutions
```bash
# Worktree already exists
# Solution: Use different worktree name or clean existing

# Branch doesn't exist
# Solution: Command creates branch automatically from current HEAD

# Process launch failure
# Solution: Check system resources and retry with adjusted parameters

# Git conflicts
# Solution: Resolve conflicts in main branch before setup
```

### Recovery Procedures
```bash
# Manual cleanup if setup fails
git worktree remove ../my-project-feature --force
git worktree remove ../my-project-research --force
rm -rf .parallel-coordination/

# Check for orphaned processes
ps aux | grep claude-code
kill [PID] # if needed
```

## Best Practices

### When to Use Parallel Development
- **Complex Projects**: Multiple independent features or major refactoring
- **Tight Deadlines**: Need maximum development velocity
- **Research + Implementation**: Concurrent exploration and production work
- **Team Simulation**: Solo developer wanting "team of agents" experience

### Task Assignment Strategy
- **Clear Separation**: Each agent gets non-overlapping responsibility
- **Focused Context**: Specific, well-defined tasks per worktree
- **Dependency Management**: Coordinate dependent tasks through merge queue
- **Communication**: Use shared coordination files for cross-agent updates

### Resource Management
- **System Resources**: Monitor CPU and memory usage across processes
- **Git Resources**: Limit number of concurrent worktrees (recommend 2-4 max)
- **Disk Space**: Each worktree requires full repository copy
- **Network**: Multiple processes may increase API usage

**🔄 Use this command to unlock true parallel development velocity for complex projects requiring concurrent workstreams.**