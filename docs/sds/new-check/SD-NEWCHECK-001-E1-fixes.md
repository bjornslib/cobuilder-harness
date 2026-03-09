# SD-NEWCHECK-001-E1-fixes — E1 Label & Validation Polish

## Target file
`app/checks-dashboard/new/page.tsx`

## Changes required (4 specific edits)

### 1. Label: "Company Name" → "Employer Name"
Find the `FormLabel` or `Label` component with text `Company Name` and change it to `Employer Name`.

### 2. Label: "Position" → "Position / Role"
Find the `FormLabel` or `Label` component with text `Position` (the required candidate field) and change it to `Position / Role`.

### 3. RHF mode: add `mode: 'onChange'` to useForm
Change:
```ts
const form = useForm<FormData>({
  resolver: zodResolver(schema),
```
To:
```ts
const form = useForm<FormData>({
  resolver: zodResolver(schema),
  mode: 'onChange',
```
This ensures validation errors clear immediately when the user starts typing, not only after the next submit.

### 4. Make `employerCountry` optional in schema
Change:
```ts
employerCountry: z.string().min(1, 'Required'),
```
To:
```ts
employerCountry: z.string().optional(),
```
This aligns the schema with the Gherkin acceptance tests which do not list Country as a required field.

## Acceptance criteria
- Field labelled "Employer Name *" (not "Company Name")
- Field labelled "Position / Role *" (not "Position")
- Typing into a field with a validation error immediately clears the error (onChange mode)
- Submitting the form without filling Country does not show a Country validation error
- All other form behaviour (POST /api/verify, redirect, Cancel) unchanged
