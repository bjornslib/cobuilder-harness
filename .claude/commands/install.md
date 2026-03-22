---
title: "Install CoBuilder Harness Plugin"
status: active
type: command
last_verified: 2026-03-22
grade: authoritative
---

# Install CoBuilder Harness Plugin

## Quick Install

Add the marketplace and install:

```bash
# Add marketplace (one-time)
claude plugin marketplace add bjornslib/cobuilder-harness

# Install (choose scope)
claude plugin install cobuilder-harness@bjornslib-cobuilder --scope project   # shared with team
claude plugin install cobuilder-harness@bjornslib-cobuilder --scope user      # personal, all projects
claude plugin install cobuilder-harness@bjornslib-cobuilder --scope local     # project-only, gitignored
```

## Local Development Install

```bash
claude --plugin-dir /path/to/cobuilder-harness
```

## Verify

```
/plugin
/reload-plugins
```
