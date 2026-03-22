---
title: "Status"
status: active
type: command
last_verified: 2026-02-19
grade: reference
---

# Parallel Development Status Monitor

## Monitor Active Multi-Process Development

**Check status of all parallel development workstreams, processes, and coordination.**

## Usage

```bash
/project:parallel/status
/project:parallel/status --detailed
/project:parallel/status --health-check
```

## What This Command Shows

### 1. Active Worktrees Status
```bash
# List all active git worktrees
git worktree list

# Parse coordination files
cat .parallel-coordination/active-worktrees.json | jq '.worktrees[] | {name, branch, task, status}'

# Output example:
# feature: feature/user-auth (Implementation) - Active
# research: research/auth-patterns (Research) - Active  
# testing: tests/auth-system (Testing) - Completed
```

### 2. Process Health Check
```bash
# Check Claude Code processes
ps aux | grep claude-code | grep -v grep

# Verify processes are running in correct directories
lsof -p [PID] | grep [worktree-path]

# Memory and CPU usage per process
top -p [PID1,PID2,PID3]
```

### 3. Git Synchronization Status
```bash
# Check if worktrees are synced with main
for worktree in $(git worktree list --porcelain | grep worktree | cut -d' ' -f2); do
  cd $worktree
  echo "$(basename $worktree): $(git status --porcelain | wc -l) changes"
  git rev-list --count HEAD ^origin/main
done
```

### 4. Coordination and Progress
```bash
# Show completion status
cat .parallel-coordination/progress.json

# Display merge queue
cat .parallel-coordination/merge-queue.json

# Show last activity timestamps
find .parallel-coordination/ -name "*.json" -exec stat -c "%y %n" {} \;
```

## Output Formats

### Standard Status Display
```
Parallel Development Status
==========================

Active Worktrees:
- feature/user-auth (../my-project-feature) - Implementation
  Status: Active, 15 commits ahead of main
  Process: PID 12345, Running, Memory: 245MB
  
- research/auth-patterns (../my-project-research) - Research  
  Status: Active, 8 commits ahead of main
  Process: PID 12346, Running, Memory: 178MB

Coordination:
- Setup: 2025-06-28 14:30:00
- Last Sync: 2025-06-28 15:45:00  
- Merge Queue: 0 pending

System Resources:
- Total Memory: 423MB across 2 processes
- CPU Load: 12% average
- Disk Usage: 1.2GB additional (worktrees)
```

### Detailed Health Check
```bash
/project:parallel/status --health-check

# Additional checks:
# - Git repository integrity per worktree
# - File system permissions
# - Network connectivity for API calls
# - MCP server status if using Serena
# - Coordination file integrity
```

### Compact Overview
```bash
/project:parallel/status --compact

# Output:
# 2 active worktrees, 2 running processes, 0 merge conflicts
```

## Alert Conditions

### Warning States
- **Process Not Responding**: Claude Code process has crashed or hung
- **High Memory Usage**: Process using >500MB memory  
- **Git Conflicts**: Merge conflicts detected between worktrees
- **Sync Drift**: Worktree more than 20 commits behind main
- **Coordination File Corruption**: JSON files damaged or missing

### Critical States  
- **Worktree Corruption**: Git worktree is in invalid state
- **Disk Space Low**: Less than 1GB available space
- **Multiple Process Conflicts**: Multiple Claude Code instances in same worktree
- **Main Branch Divergence**: Main branch has been force-pushed or rebased

## Integration with Other Commands

### Auto-Status in Other Commands
```bash
# Other parallel commands automatically show status
/project:parallel/merge-workflow  # Shows status first
/project:parallel/cleanup         # Shows what will be cleaned

# Status checks integrated into workflow commands
/project:parallel/sync-all        # Status before and after sync
```

### Monitoring Integration
```bash
# Watch mode for continuous monitoring
watch -n 30 '/project:parallel/status --compact'

# Log status to file for analysis
/project:parallel/status --detailed >> parallel-dev.log
```

## Troubleshooting

### Common Status Issues

**No Active Worktrees Shown**
```bash
# Verify coordination files exist
ls -la .parallel-coordination/

# Check git worktrees directly
git worktree list

# Rebuild coordination if corrupted
/project:parallel/setup --recover
```

**Process Status "Unknown"**
```bash
# Check if process still running
ps aux | grep claude-code

# Verify process working directory
lsof -p [PID] | grep -E "(cwd|txt)"

# Restart dead processes
/project:parallel/restart-process [worktree-name]
```

**Git Status Warnings**
```bash
# Sync with main branch
cd [worktree-path]
git fetch origin
git merge origin/main

# Resolve conflicts if needed
git status
git add .
git commit -m "Merge main branch"
```

### Emergency Commands
```bash
# Force refresh status
rm .parallel-coordination/cache.json
/project:parallel/status --refresh

# Kill unresponsive processes
/project:parallel/cleanup --force-processes

# Emergency stop all parallel development
/project:parallel/emergency-stop
```

## Performance Monitoring

### Resource Usage Tracking
```bash
# Memory usage over time
/project:parallel/status --memory-history

# CPU usage patterns
/project:parallel/status --cpu-trends  

# API usage per process
/project:parallel/status --api-metrics
```

### Optimization Recommendations
- **Memory Optimization**: Restart processes using >400MB
- **CPU Balancing**: Distribute work if total CPU >80%
- **Disk Cleanup**: Remove old worktrees if disk usage high
- **Process Limit**: Maximum 4 parallel processes recommended

## Command Line Usage

### Use with argument support
```bash
/project:parallel/status detailed      # Show comprehensive status
/project:parallel/status health        # Focus on health checks
/project:parallel/status compact       # Minimal status overview
```

**📊 Essential for monitoring and maintaining healthy parallel development environments.**