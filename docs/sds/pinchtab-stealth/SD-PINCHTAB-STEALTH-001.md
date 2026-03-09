---
title: "SD: PinchTab Anti-Detection Chrome Flag Fixes"
status: active
type: architecture
last_verified: 2026-03-08
grade: authoritative
---

# Solution Design: PinchTab Anti-Detection Chrome Flag Fixes

## Problem

PinchTab launches Chrome with `chromedp.DefaultExecAllocatorOptions` which includes `--enable-automation`. Even though PinchTab adds `--disable-automation` afterward, Chrome receives BOTH flags on the command line. LinkedIn's PerimeterX/HUMAN bot detection (`li.protechts.net`) detects:

1. `--enable-automation` flag presence
2. `--use-mock-keychain` (automation fingerprint)
3. `--disable-extensions` (real users have extensions)
4. Missing `--exclude-switches=enable-automation,enable-logging`

## Evidence

From `ps aux` output of PinchTab-launched Chrome:
```
--enable-automation --disable-automation= --disable-blink-features=AutomationControlled
```

Both `--enable-automation` AND `--disable-automation` appear simultaneously. LinkedIn's PerimeterX sees `--enable-automation` and throttles.

## Solution

### File: `internal/bridge/init.go`

#### Change 1: Filter DefaultExecAllocatorOptions (line 97)

Replace:
```go
opts := chromedp.DefaultExecAllocatorOptions[:]
```

With a filtered copy that removes `enable-automation` from the defaults:
```go
// Start with defaults but filter out automation-revealing flags
var opts []chromedp.ExecAllocatorOption
for _, opt := range chromedp.DefaultExecAllocatorOptions {
    opts = append(opts, opt)
}
// Override: explicitly disable automation detection
opts = append(opts, chromedp.Flag("enable-automation", false))
```

Note: `chromedp.DefaultExecAllocatorOptions` is a `[...]ExecAllocatorOption` array. The `Flag("enable-automation", false)` appended AFTER the defaults will override the default `Flag("enable-automation", true)` because chromedp processes flags in order with last-wins semantics for boolean flags.

#### Change 2: Add --exclude-switches (after line 146)

Add after the existing stealth flags block:
```go
// Exclude automation switches from Chrome's internal switch list
// This prevents detection via chrome://version or CDP's Browser.getVersion
chromedp.Flag("exclude-switches", "enable-automation,enable-logging"),
```

#### Change 3: Remove --use-mock-keychain from buildChromeArgs (line 458)

Remove this line:
```go
"--use-mock-keychain",
```

This is a macOS-specific flag that tells Chrome to use a mock keychain. Real users don't have this. It's an automation fingerprint.

#### Change 4: Add --exclude-switches to buildChromeArgs (after line 461)

Add:
```go
"--exclude-switches=enable-automation,enable-logging",
```

#### Change 5: Remove --disable-extensions from buildChromeArgs default (line 471)

The `--disable-extensions` flag in the else branch (when no extensions are loaded) is a bot fingerprint. Real browsers have extensions. Remove this line or make it conditional on stealth level.

### Verification

After rebuilding:
1. `ps aux | grep Chrome` should NOT show `--enable-automation`
2. Navigate to LinkedIn — should load at normal speed without throttling
3. `navigator.webdriver` should remain `undefined` (already working via stealth.js)
4. Chrome infobar "Chrome is being controlled by automated test software" should NOT appear

## Build & Install

```bash
cd pinchtab
go build -o bin/pinchtab ./cmd/pinchtab
cp bin/pinchtab ~/.npm-global/lib/node_modules/pinchtab/bin/pinchtab
```
