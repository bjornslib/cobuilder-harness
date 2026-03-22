---
title: "SD-NEWCHECK-001-E1: New Check Form Page UI"
status: active
type: guide
grade: authoritative
last_verified: 2026-03-07
version: "2.0"
---

# SD-NEWCHECK-001-E1: New Check Form Page UI

## Epic
E1 — New Check form page at `/checks-dashboard/new`

Bead: `my-project-0h4w`

---

## SD Version History (What Changed in v2 — Required for Re-run)

> **This section exists so the pipeline runner can identify the delta between the first dispatch (v1) and this re-run (v2).**

### v1 → v2 Changes

| Area | v1 (Initial dispatch) | v2 (This SD) |
|------|-----------------------|--------------|
| **Component library** | Plain Tailwind `<input>`, `<select>`, `<div>` | ShadCN components (see Component Map below) |
| **Form validation** | Manual `useState` validation object | `react-hook-form` + ShadCN `Form` + `zodResolver` |
| **Radio buttons** | Custom styled `<label>/<input type="radio">` | `RadioGroup` + `RadioGroupItem` from ShadCN |
| **Error/success banners** | Custom Tailwind `<div>` banner | ShadCN `Alert` + `AlertDescription` |
| **Breadcrumb** | Custom `<a>` + chevron text | ShadCN `Breadcrumb` + `BreadcrumbItem` + `BreadcrumbSeparator` |
| **Call config section** | Always-visible section | `Collapsible` from ShadCN (collapsed by default) |
| **Submit action** | Unclear — must call POST /api/verify | **Creates background task via POST /api/verify** — same as `handleCreateTask()` in `/aura-call`. No voice call. No LiveKit. |
| **Imports** | `useState`, `useRouter`, `cn` | + `useForm`, `zodResolver`, ShadCN components |
| **Zod schema** | None | Full Zod schema for required field validation |

### ShadCN Components to Install (Run Before Implementing)

```bash
# Run in my-project-frontend/
npx shadcn@latest add radio-group alert breadcrumb collapsible form
```

### Already Installed (No Install Needed)

`Card`, `Input`, `Label`, `Checkbox`, `Select`, `Button`, `Separator`, `Badge` — all present in `components/ui/`.

---

## Overview

Create a new Next.js page at `app/checks-dashboard/new/page.tsx` that renders the New Verification form. The form uses ShadCN components, `react-hook-form` with Zod validation, and submits to the existing `POST /api/verify` endpoint to **create a background verification task** (no voice call, no LiveKit).

This mirrors the **"Create Task"** flow (`handleCreateTask`) in `/aura-call/page.tsx` — same endpoint, same payload, same outcome.

---

## Files to Create

```
app/checks-dashboard/new/
└── page.tsx          ← New Check form page (client component)
```

No changes to `layout.tsx` — `checks-dashboard/layout.tsx` automatically applies.

---

## ShadCN Component Map

| UI Element | Component | Source | Install Needed |
|-----------|-----------|--------|----------------|
| Section containers | `Card`, `CardHeader`, `CardContent` | `@/components/ui/card` | No |
| Text inputs | `Input` | `@/components/ui/input` | No |
| Field labels | `Label` | `@/components/ui/label` | No |
| Checkboxes (verify fields) | `Checkbox` | `@/components/ui/checkbox` | No |
| Dropdowns (Employment Type, Location, Phone Type) | `Select`, `SelectTrigger`, `SelectContent`, `SelectItem`, `SelectValue` | `@/components/ui/select` | No |
| Submit / Cancel buttons | `Button` | `@/components/ui/button` | No |
| Section divider | `Separator` | `@/components/ui/separator` | No |
| Check type radio | `RadioGroup`, `RadioGroupItem` | `@/components/ui/radio-group` | **Yes** |
| Error / success banners | `Alert`, `AlertDescription` | `@/components/ui/alert` | **Yes** |
| Page breadcrumb | `Breadcrumb`, `BreadcrumbItem`, `BreadcrumbLink`, `BreadcrumbSeparator`, `BreadcrumbPage`, `BreadcrumbList` | `@/components/ui/breadcrumb` | **Yes** |
| Call config (collapsible) | `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` | `@/components/ui/collapsible` | **Yes** |
| Form with validation | `Form`, `FormField`, `FormItem`, `FormLabel`, `FormControl`, `FormMessage` | `@/components/ui/form` | **Yes** |

---

## Submit Action: Background Task Creation

> **IMPORTANT**: This form creates a **background verification task** via `POST /api/verify`.
> There is NO voice call, NO LiveKit connection, NO token fetch.
> This is identical to `handleCreateTask()` in `app/aura-call/page.tsx`.

```typescript
// On form submit:
const response = await fetch('/api/verify', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    firstName, middleName, lastName,
    employerName, employerWebsite,
    employerCountry, employerCity,
    contactPersonName,
    contactPhoneNumber: contactPhoneNumber || undefined,
    employerPhone: contactPhoneNumber || undefined,
    position, startDate, endDate,
    verifyFields,
    location, phoneType,
    agentType: 'work-history-agent',
    taskId: taskId || undefined,
  }),
});
// On success: router.push('/checks-dashboard?checkCreated=1')
// On error: show Alert with error message
```

---

## Form State

```typescript
// react-hook-form + Zod
const schema = z.object({
  firstName: z.string().min(1, 'Required'),
  lastName: z.string().min(1, 'Required'),
  middleName: z.string().optional(),
  position: z.string().min(1, 'Required'),
  startDate: z.string().min(1, 'Required'),
  endDate: z.string().min(1, 'Required'),
  employmentType: z.string().optional(),
  taskId: z.string().optional(),
  employerName: z.string().min(1, 'Required'),
  employerWebsite: z.string().optional(),
  employerCountry: z.string().min(1, 'Required'),
  employerCity: z.string().optional(),
  contactPersonName: z.string().optional(),
  contactPhoneNumber: z.string().optional(),
  location: z.enum(['australia', 'singapore']).default('singapore'),
  phoneType: z.string().default('direct_contact'),
});

// Verify fields managed separately with useState (not in form schema)
const [verifyFields, setVerifyFields] = useState({
  salary: false,
  supervisor: false,
  employment_type: true,
  rehire_eligibility: false,
  reason_for_leaving: false,
});
```

---

## Layout Structure

```tsx
<div className="container mx-auto px-4 pb-8">

  {/* Breadcrumb */}
  <Breadcrumb className="mb-4">
    <BreadcrumbList>
      <BreadcrumbItem><BreadcrumbLink href="/checks-dashboard">Checks</BreadcrumbLink></BreadcrumbItem>
      <BreadcrumbSeparator />
      <BreadcrumbItem><BreadcrumbPage>New Verification</BreadcrumbPage></BreadcrumbItem>
    </BreadcrumbList>
  </Breadcrumb>

  {/* Header */}
  <div className="mb-8">
    <h2 className="text-2xl font-bold">New Verification</h2>
    <p className="text-muted-foreground text-sm mt-1">Submit a new background verification check for a candidate.</p>
  </div>

  <Form {...form}>
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6 max-w-4xl">

      {/* Section 1: Check Selection */}
      <Card>
        <CardHeader><h3 className="text-sm font-bold uppercase tracking-wider">Check Selection</h3></CardHeader>
        <CardContent>
          <RadioGroup defaultValue="work_history" className="grid grid-cols-2 gap-4">
            <label className="flex cursor-pointer rounded-lg border border-primary ring-1 ring-primary p-4 gap-3">
              <RadioGroupItem value="work_history" id="work_history" />
              <div>
                <p className="text-sm font-medium">Work History</p>
                <p className="text-xs text-muted-foreground">Standard employment verification</p>
              </div>
            </label>
            <label className="flex cursor-not-allowed rounded-lg border border-muted p-4 gap-3 opacity-50">
              <RadioGroupItem value="schedule_work_history" id="schedule_work_history" disabled />
              <div>
                <p className="text-sm font-medium">Schedule Work History</p>
                <p className="text-xs text-muted-foreground">Coming soon</p>
              </div>
            </label>
          </RadioGroup>
        </CardContent>
      </Card>

      {/* Section 2: Candidate Details */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined">person</span>
            <h3 className="text-sm font-bold uppercase tracking-wider">Candidate Details</h3>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* 3-col: First / Middle / Last Name */}
          <div className="grid grid-cols-3 gap-4">
            <FormField name="firstName" render={...} /> {/* Input */}
            <FormField name="middleName" render={...} /> {/* Input, optional */}
            <FormField name="lastName" render={...} />  {/* Input */}
          </div>
          {/* Position (half width) */}
          <div className="w-1/2">
            <FormField name="position" render={...} />
          </div>
          {/* Start/End date (2-col) */}
          <div className="grid grid-cols-2 gap-4">
            <FormField name="startDate" render={...} />
            <FormField name="endDate" render={...} />
          </div>
          {/* Employment Type (half width, Select) */}
          <div className="w-1/2">
            <FormField name="employmentType" render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value}>
                <SelectTrigger><SelectValue placeholder="Select employment type" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="full_time">Full-time</SelectItem>
                  <SelectItem value="part_time">Part-time</SelectItem>
                  <SelectItem value="contract">Contract</SelectItem>
                </SelectContent>
              </Select>
            )} />
          </div>
          <Separator />
          {/* Task ID (half width, optional) */}
          <div className="w-1/2">
            <FormField name="taskId" render={...} />
            <p className="text-xs text-muted-foreground mt-1">Link to existing background task for E2E testing</p>
          </div>
        </CardContent>
      </Card>

      {/* Section 3: Employer Details */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined">domain</span>
            <h3 className="text-sm font-bold uppercase tracking-wider">Employer Details</h3>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <FormField name="employerName" render={...} />
            <FormField name="employerWebsite" render={...} /> {/* type="url" */}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField name="employerCountry" render={...} />
            <FormField name="employerCity" render={...} />
          </div>
          <div className="w-1/2">
            <FormField name="contactPersonName" render={...} />
          </div>
          <div className="w-1/2">
            {/* contactPhoneNumber - not in form schema, use local state */}
            <Label>Contact Phone Number</Label>
            <Input value={contactPhoneNumber} onChange={...} placeholder="+61 2 1234 5678" />
          </div>
        </CardContent>
      </Card>

      {/* Section 4: Additional Verification Points */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-green-500">check_circle</span>
            <h3 className="text-sm font-bold uppercase tracking-wider">Additional Verification Points</h3>
          </div>
          <p className="text-xs text-muted-foreground">Select which additional questions to ask during verification</p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            {VERIFY_FIELDS.map(({ key, label, icon, color }) => (
              <label key={key} className={cn(
                "flex items-center gap-3 p-3 border rounded-lg cursor-pointer",
                verifyFields[key] ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"
              )}>
                <Checkbox
                  checked={verifyFields[key]}
                  onCheckedChange={(checked) => setVerifyFields(prev => ({ ...prev, [key]: !!checked }))}
                />
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span className={cn("material-symbols-outlined text-[18px]", color)}>{icon}</span>
                  {label}
                </span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Section 5: Call Configuration (Collapsible) */}
      <Collapsible>
        <Card>
          <CardHeader>
            <CollapsibleTrigger className="flex items-center justify-between w-full">
              <h3 className="text-sm font-bold uppercase tracking-wider">Call Configuration</h3>
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <FormField name="location" render={({ field }) => (
                  <Select onValueChange={field.onChange} defaultValue="singapore">
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="singapore">Singapore</SelectItem>
                      <SelectItem value="australia">Australia</SelectItem>
                    </SelectContent>
                  </Select>
                )} />
                <FormField name="phoneType" render={({ field }) => (
                  <Select onValueChange={field.onChange} defaultValue="direct_contact">
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="direct_contact">Direct Contact</SelectItem>
                      <SelectItem value="reception">Reception</SelectItem>
                      <SelectItem value="hr">HR</SelectItem>
                    </SelectContent>
                  </Select>
                )} />
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Error banner */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Actions */}
      <div className="flex justify-end gap-4 pt-2">
        <Button type="button" variant="ghost" onClick={() => router.push('/checks-dashboard')}>Cancel</Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? 'Submitting...' : 'Submit Check'}
        </Button>
      </div>

    </form>
  </Form>
</div>
```

---

## Verify Fields Config

```typescript
const VERIFY_FIELDS = [
  { key: 'salary',            label: 'Salary',            icon: 'attach_money',    color: 'text-green-600' },
  { key: 'supervisor',        label: 'Supervisor',        icon: 'manage_accounts', color: 'text-slate-500' },
  { key: 'employment_type',   label: 'Employment Type',   icon: 'card_travel',     color: 'text-purple-500' },
  { key: 'rehire_eligibility',label: 'Rehire Eligibility',icon: 'autorenew',       color: 'text-amber-500' },
  { key: 'reason_for_leaving',label: 'Reason for Leaving',icon: 'assignment_late', color: 'text-red-500' },
] as const;
```

---

## Required Imports

```typescript
'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

// ShadCN — already installed
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';

// ShadCN — install with: npx shadcn@latest add radio-group alert breadcrumb collapsible form
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
```

---

## Pre-Implementation Checklist (for Worker)

```bash
# 1. Install missing ShadCN components FIRST
cd /path/to/my-project-frontend
npx shadcn@latest add radio-group alert breadcrumb collapsible form

# 2. Verify zod + react-hook-form + @hookform/resolvers are available
cat package.json | grep -E "zod|react-hook-form|hookform"
# If missing: npm install zod react-hook-form @hookform/resolvers

# 3. Then implement page.tsx
```

---

## Acceptance Criteria

- [ ] `npx shadcn@latest add radio-group alert breadcrumb collapsible form` runs without error
- [ ] Page renders at `/checks-dashboard/new` with checks-dashboard layout (sidebar visible)
- [ ] All 5 form sections use ShadCN components per Component Map
- [ ] Submitting valid form calls `POST /api/verify` (background task creation, no voice call)
- [ ] Success redirects to `/checks-dashboard?checkCreated=1`
- [ ] API error shows ShadCN `Alert` with `variant="destructive"`
- [ ] Required field validation uses react-hook-form + Zod (inline `FormMessage` per field)
- [ ] Loading state on Submit button during API call
- [ ] "Schedule Work History" `RadioGroupItem` has `disabled` prop
- [ ] Call Configuration section is `Collapsible` (collapsed by default)

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
