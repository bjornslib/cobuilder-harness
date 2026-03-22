---
title: "Research Workflow"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Research Workflow Reference

Detailed guide for Step 2: Component and Pattern Research.

## Research Execution Strategy

Execute research tasks in parallel to minimize latency:

```
┌─────────────────────────────────────────────────────────────┐
│                    PARALLEL EXECUTION                        │
├─────────────────┬─────────────────┬─────────────────────────┤
│ Explore Agent   │ Magic UI MCP    │ Perplexity/Context7     │
│ (codebase)      │ (components)    │ (patterns)              │
├─────────────────┼─────────────────┼─────────────────────────┤
│ Find existing   │ Browse catalog  │ Research best practices │
│ patterns        │ Get animations  │ Accessibility guidance  │
│ Check Zustand   │ Find effects    │ Framework docs          │
└─────────────────┴─────────────────┴─────────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Component Research  │
                 │      Report         │
                 └─────────────────────┘
```

## 2a. Codebase Pattern Search

### Using Explore Agent

Spawn a Task with `subagent_type=Explore` to search:

```
Task(
  description="Find existing UI patterns",
  subagent_type="Explore",
  prompt="""
  Search the my-project-frontend codebase for:

  1. Components similar to: {list from brief}
  2. Layout patterns matching: {layout description}
  3. Animation/transition patterns in use
  4. Zustand slice patterns for: {state needs}

  Focus on:
  - components/ui/ for base components
  - components/ subdirectories for feature components
  - stores/slices/ for state patterns
  - app/ for page layout patterns

  Return file paths and key patterns found.
  """
)
```

### Key Directories to Search

| Directory | Contains |
|-----------|----------|
| `components/ui/` | shadcn base components (25+) |
| `components/assistant-ui/` | Chat interface components |
| `components/university/` | Verification UI components |
| `components/sidebar/` | Navigation patterns |
| `components/magicui/` | Animation components |
| `stores/slices/` | Zustand state patterns |

### Pattern Matching Queries

```bash
# Find card-like components
Glob: "components/**/*card*.tsx"

# Find status indicators
Grep: "status.*active|idle|error"

# Find animation patterns
Grep: "animate-|transition-|motion"

# Find metric/stat displays
Grep: "value.*trend|metric|stat"
```

## 2b. Magic UI Component Research

### Available MCP Tools

| Tool | Purpose | Example Query |
|------|---------|---------------|
| `getUIComponents` | Full component catalog | "Show all available UI components" |
| `getAnimations` | Animation library | "Find fade and slide animations" |
| `getTextAnimations` | Text effects | "Typewriter, gradient text effects" |
| `getButtons` | Button variants | "Find animated button styles" |
| `getBackgrounds` | Background effects | "Gradient, pattern backgrounds" |
| `getSpecialEffects` | Visual effects | "Glow, shimmer, particle effects" |
| `getDeviceMocks` | Device frames | "Phone/laptop mockups" |

### Component Selection Criteria

**Prefer Magic UI for:**
- Hero sections with animations
- Interactive hover effects
- Text reveal animations
- Background patterns/gradients
- Loading states with visual flair
- Card hover transformations

**Skip Magic UI for:**
- Simple data display (use shadcn)
- Form inputs (use shadcn)
- Basic layout (use Tailwind)
- Static content (use plain components)

### Query Examples

```
# For a dashboard with animated metrics
mcp__@magicuidesign/mcp__getUIComponents:
  "number counter animations, stat cards with hover effects"

# For a hero section
mcp__@magicuidesign/mcp__getAnimations:
  "fade in, slide up, stagger children animations"

# For call-to-action buttons
mcp__@magicuidesign/mcp__getButtons:
  "shimmer effect, gradient, magnetic buttons"
```

## 2c. Shadcn Component Check

### Checking Installed Components

Use shadcn MCP or check filesystem:

```bash
# List installed components
ls my-project-frontend/components/ui/

# Check for specific component
Glob: "components/ui/{component-name}.tsx"
```

### Common Components Available

Already installed in My Project:
- `button`, `card`, `badge`
- `dialog`, `popover`, `tooltip`
- `tabs`, `accordion`
- `input`, `textarea`, `select`
- `avatar`, `separator`
- `scroll-area`, `skeleton`

### Installing Missing Components

```bash
# Single component
npx shadcn@latest add [component]

# Multiple components
npx shadcn@latest add card badge button tabs
```

### Component Compatibility

Verify compatibility before selecting:
- React 19 support (most shadcn components work)
- Tailwind 4 compatibility (use CSS variables)
- Radix UI version alignment

## 2d. Pattern Research with Perplexity

### When to Use

- Complex UI patterns (dashboards, wizards)
- Accessibility best practices
- Performance optimization techniques
- Animation timing/easing recommendations

### Query Format

```
mcp__perplexity__perplexity_ask:
  "Best practices for {pattern} in React 19 with Tailwind CSS.
   Focus on: accessibility, performance, dark mode support.
   Include specific implementation patterns."
```

### Example Queries

```
# For metric dashboards
"Best practices for real-time metrics dashboard React.
 Auto-updating numbers, status indicators, responsive grid layout.
 Focus on performance with frequent updates."

# For data tables
"Accessible data table patterns React 2024.
 Sorting, filtering, pagination, keyboard navigation.
 Works with Tailwind CSS and shadcn/ui."

# For voice agent UI
"Real-time voice call status UI patterns.
 Active/idle/connecting states, call duration display,
 agent status indicators. Accessibility for screen readers."
```

## 2e. Framework Documentation

### Using Context7

```
# Resolve framework
mcp__context7__resolve-library-id:
  query: "next.js app router"

# Get specific docs
mcp__context7__get-library-docs:
  library_id: "nextjs"
  topic: "server components data fetching"
```

### Common Documentation Needs

| Topic | Library | Query |
|-------|---------|-------|
| Server Components | Next.js | "server vs client components" |
| CSS Variables | Tailwind | "custom properties dark mode" |
| Animations | Tailwind | "animate utilities keyframes" |
| State Updates | Zustand | "immer middleware maps" |

## Research Report Template

After completing research, compile findings:

```markdown
# Component Research Report

## Design: {Component/Page Name}

### Existing Patterns Found
| Component Need | Existing Pattern | Location |
|----------------|------------------|----------|
| Metric Card | ContactCard | components/university/ |
| Status Badge | VerificationBadge | components/assistant-ui/ |

### Recommended Components

#### From shadcn/ui
| Component | Status | Install Command |
|-----------|--------|-----------------|
| Card | Installed | - |
| Badge | Installed | - |
| Tabs | Missing | `npx shadcn@latest add tabs` |

#### From Magic UI
| Component | Purpose |
|-----------|---------|
| NumberTicker | Animated metric values |
| ShimmerButton | CTA buttons |
| BorderBeam | Card hover effects |

### Animation Recommendations
- Entry: `animate-in fade-in slide-in-from-bottom-4`
- Hover: `hover:shadow-lg transition-shadow`
- Status: `animate-pulse` for connecting states

### Accessibility Notes
- Use `aria-live="polite"` for status updates
- Include `tabindex` for interactive cards
- Announce metric changes to screen readers

### Installation Commands
```bash
npx shadcn@latest add tabs tooltip
npm install @magicui/number-ticker
```
```

## Parallel Execution Pattern

Execute all research in a single message with multiple tool calls:

```typescript
// Conceptual - execute these in parallel
[
  Task({ subagent_type: "Explore", prompt: "Find patterns..." }),
  mcp__@magicuidesign/mcp__getUIComponents({ query: "..." }),
  mcp__@magicuidesign/mcp__getAnimations({ query: "..." }),
  mcp__perplexity__perplexity_ask({ query: "..." })
]
```

This minimizes latency by gathering all research simultaneously.

## Decision Matrix

Use this to decide component sources:

| Condition | Source | Rationale |
|-----------|--------|-----------|
| Exact match exists in codebase | Existing | Consistency, no new deps |
| Standard UI element | shadcn | Accessible, themeable |
| Needs animation/effects | Magic UI | Visual polish |
| Simple layout | Tailwind only | No component overhead |
| Complex interaction | Custom + shadcn | Full control |

## Common Pitfalls

### Avoid
- Adding Magic UI for simple static content
- Installing shadcn components already in codebase
- Using Perplexity for questions answerable from docs
- Over-animating (causes performance issues)

### Prefer
- Reusing existing codebase patterns
- Minimal new dependencies
- CSS-only animations where possible
- Progressive enhancement approach
