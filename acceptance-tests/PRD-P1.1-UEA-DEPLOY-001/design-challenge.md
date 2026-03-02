---
title: "Design Challenge: PRD-P1.1-UEA-DEPLOY-001"
status: active
type: reference
last_verified: 2026-02-28
grade: authoritative
---

# Design Challenge Report: PRD-P1.1-UEA-DEPLOY-001

**Reviewer**: Independent Design Challenger
**Date**: 2026-02-28
**PRD**: UE-A Deployment & E2E Validation
**Branch**: `feature/ue-a-workflow-config-sla` (PR #212)

---

## Executive Summary

The PRD has one critical factual error that invalidates Epic 1 as currently specified, two high-severity operational risks around migration numbering, and several actionable gaps. The deployment sequence is recoverable, but needs significant amendment before execution.

---

## 1. Migration 038 Risk Assessment

### 1.1 The PRD Targets the Wrong Table

**CRITICAL FINDING**: The PRD states that migration 038 must convert `client_reference VARCHAR(255)` to `client_id INTEGER` on the `check_types` table. However, inspection of existing migrations shows:

- **Migration 036** (`036_customer_sla_resolution.sql`) adds `client_reference VARCHAR(255)` to `background_check_sequence`, not `check_types`.
- The `check_types` table (created by migration 035) never had a `client_reference` column — it only has `id`, `name`, `display_name`, `description`, `default_sla_hours`, `is_active`, `created_at`, `updated_at`.
- **Main already has migration 025** (`025_replace_client_reference_with_client_id.sql`) which performs the exact `client_reference -> client_id` conversion on `background_check_sequence`.

This means Epic 1's target column and table are misidentified. The work that migration 038 is supposed to do on the feature branch was already done on `main` (as migration 025, which post-dates 024 on main). After rebase, migration 025 will land before migrations 035-038, making the `client_reference` column on `background_check_sequence` already gone before migration 036 tries to add it.

### 1.2 UPDATE...FROM...WHERE Safety

The PRD's proposed migration strategy:

```sql
UPDATE check_types ct
SET client_id = c.id
FROM clients c
WHERE ct.client_reference = c.name OR ct.client_reference = c.id::text;
```

This approach has three problems:

1. **Silent data loss**: Rows where `client_reference` does not match any `clients.name` or `clients.id::text` will have `client_id` remain NULL and then the original value is permanently dropped. There is no error, no warning — the data is silently abandoned.

2. **Ambiguous match**: The `OR ct.client_reference = c.id::text` arm is dangerous. If a client's name is "2" and another client has id=2, both match and PostgreSQL will update the row twice in one statement (last write wins based on planner). Result is non-deterministic.

3. **No pre-flight check**: There is no assertion before the DROP that all non-null `client_reference` values were successfully mapped. The migration should `RAISE EXCEPTION` if `SELECT COUNT(*) FROM check_types WHERE client_reference IS NOT NULL AND client_id IS NULL > 0` after the UPDATE.

**Verdict on this specific strategy**: Unsafe for any environment where `check_types` rows exist with non-null `client_reference`. For a fresh Railway deployment (where these tables have never existed), the risk is moot — the seed data does not populate `client_reference` so the UPDATE affects 0 rows. But the migration as written would be a landmine for future environments that do have client-specific check types.

### 1.3 DROP COLUMN Safety

The PRD's risk table notes "keep backup column" as a mitigation but the implementation notes proceed with `DROP COLUMN IF EXISTS` immediately after the UPDATE, with no backup step. These are contradictory.

Dropping `client_reference` in the same migration as the data migration provides zero recovery window if the UPDATE was incorrect. The safer pattern is:

- Migration N: add `client_id`, run UPDATE, add NOT NULL guard on mapped rows, leave `client_reference` in place with a deprecation comment.
- Migration N+1: after validation in production, DROP `client_reference`.

For a first deployment to a database with no existing data in `check_types`, this is low risk in practice. But the pattern is still wrong and sets a bad precedent.

### 1.4 Idempotency

The `ALTER TABLE ADD COLUMN` in the proposed migration is not wrapped in an `IF NOT EXISTS` guard (unlike migrations 035-037 which all use `DO $$ BEGIN IF NOT EXISTS ... END $$`). Running the migration twice would fail with "column already exists". This violates AC-1.2.

---

## 2. Rebase Risk Assessment

### 2.1 Migration Numbering Collision — CRITICAL

This is the most dangerous operational risk in the entire PRD.

**Current state**:
- Feature branch migrations: 035, 036, 037 (and proposed 038)
- Main branch migrations: 025, 043, 044 (and earlier ones)

Main has jumped from 025 to 043. This means main had migrations 026-042 at some point that are either lost, on other feature branches, or were squashed. More importantly:

**After rebase, the feature branch will contain migrations from main (up to 044) plus its own 035, 036, 037, 038.** The numbering 035-038 does not conflict with 043-044 numerically. However:

- **Migration 025 on main already does what migration 036 on the feature branch does** (replace `client_reference` with `client_id` on `background_check_sequence`). After rebase, the sequence will be: ...024, 025 (drops `client_reference`, adds `client_id`)... then ...035 (creates tables), 036 (adds `client_reference` back to `background_check_sequence`). Migration 036 will add a column that migration 025 already removed — this will technically succeed because 025 ran first and 036 uses `IF NOT EXISTS` guards. But then migration 025's `client_id` column would co-exist with 036's re-added `client_reference` column, and migration 038 would try to do the conversion again. This is a multi-migration logical conflict, not a naming collision.

- **The unique index names collide**: Both migration 025 and migration 036 create `uq_bcs_customer_type_step_active` and `idx_bcs_resolution_lookup`. Migration 025 creates them with `client_id`; migration 036 drops them and recreates with `client_reference`. After rebase and sequential execution, the indexes will end up pointing at `client_reference` (the 036 version), but migration 025's version already ran. This is a logical contradiction in the schema.

**Bottom line**: The feature branch migrations 035-038 were written in a pre-025 world. Post-rebase, they will execute in a world where 025 has already restructured `background_check_sequence`. The migration chain is not rebase-safe as written.

### 2.2 Force-Push with Lease Risk

`git push --force-with-lease` is appropriate here (it protects against overwriting remote work that you haven't seen). However:

- If another developer pushed to the feature branch between your last fetch and your push, the push will be rejected. This is the correct behavior, not a risk.
- The real risk is that PR #212 has 19 commits. A rebase of 19 commits against a main that has diverged significantly (main went from ~024 to 044, indicating significant parallel development) is likely to produce multiple rebase conflicts. The PRD says "resolve incrementally, commit-by-commit if needed" but does not specify who does this or how to validate each interim state.
- If the rebase is interrupted and resumed incorrectly, the migration file order within git history may be inconsistent with the filesystem sort order that the migration runner uses to determine execution sequence.

### 2.3 Migration Numbering Gaps on Main

Main has: 023, 024, 025, 043, 044. Migrations 026-042 are absent from the main branch directory. This gap (17 missing migrations) suggests either:

a) Those migrations live on other feature branches not yet merged, or
b) They were applied to Railway directly and the files were lost, or
c) The migration runner on Railway has already applied 026-042 to the live database.

If (c), then after merging PR #212, Railway will receive the feature branch's 035-038 files. If the migration runner tracks applied migrations by filename (not by number), 035-038 would be treated as new. If it tracks by number, there may be a skip-ahead issue.

**This gap must be investigated before proceeding with Epic 3.**

---

## 3. Deployment Risk Assessment

### 3.1 Railway Migration Failure Mid-Execution

The PRD does not specify how Railway runs migrations. Key unknowns:

- Does Railway run migrations in a single transaction? If migration 036 fails halfway, does 035 get rolled back?
- Migrations 035-037 are individually wrapped in `BEGIN/COMMIT` blocks — each is its own transaction. A failure in 036 will leave 035's tables in place. Re-running the deployment will attempt 035 again; if `CREATE TABLE IF NOT EXISTS` is used (it is), 035 will silently succeed but 036 will fail again at the same point. This is actually the correct behavior — but it depends on the migration runner tracking which files have already been applied.

- The proposed migration 038 (as described in the PRD) is **not wrapped in `BEGIN/COMMIT`**. The implementation notes show raw SQL without a transaction block. If the DROP COLUMN succeeds but a subsequent step fails, the rollback is impossible — the column is gone.

### 3.2 Rollback Strategy

The PRD mentions "have rollback migration ready" as a mitigation but does not include one. For a first deployment where the tables don't exist, rollback = drop the new tables. A rollback migration should be specified:

```sql
-- 038_rollback.sql (if needed)
ALTER TABLE check_types ADD COLUMN IF NOT EXISTS client_reference VARCHAR(255);
-- Restore data? Impossible if DROP COLUMN already ran.
```

The honest assessment: once `DROP COLUMN` runs in production, rollback requires restoring from a database snapshot. The PRD should mandate taking a Railway database snapshot before running migrations.

### 3.3 Seed Data Idempotency

Migration 035's seed data uses `ON CONFLICT (name) DO UPDATE SET ...` for check_types and `ON CONFLICT (check_type_id, step_order) DO NOTHING` for sequences. This is correctly idempotent.

However, after rebase, the `ON CONFLICT` target for sequences changes. Migration 036 drops `uq_background_check_sequence_type_order` (the original `(check_type_id, step_order)` constraint) and replaces it with `uq_bcs_customer_type_step_active` which includes `customer_id` and `client_reference/client_id`. If migrations run sequentially, the 035 seed's `ON CONFLICT (check_type_id, step_order)` clause will reference a constraint that no longer exists after 036 runs. But since 035 runs before 036, this is fine for first deployment. For idempotent re-runs (e.g. staging resets), running 035 after 036 is already applied would fail because the conflict target is gone.

### 3.4 The check_types Table Population for AC-3.4

AC-3.4 requires `check_types` to have seed data (work_history 48h, work_history_scheduling 72h). Migration 035 seeds this correctly. This AC is achievable, but it depends on migration 035 succeeding, which depends on the migration runner finding and executing it after rebase.

---

## 4. Recommended PRD Amendments

### Amendment A — Mandatory Pre-Rebase Investigation (Epic 2, blocking)

Before writing migration 038, investigate:
1. What is in Railway's `schema_migrations` (or equivalent) table? What migration numbers has the live database already applied?
2. What do migrations 026-042 contain, and where do the files live?
3. Does the migration runner use filename-based or number-based tracking?

This investigation takes 30 minutes and prevents a potentially unrecoverable production database incident.

### Amendment B — Revise Migration 038 Scope and Target

The PRD must be corrected: `client_reference` on `check_types` does not exist. The actual work needed is reconciling the feature branch's `background_check_sequence.client_reference` (added by 036) with main's `background_check_sequence.client_id` (added by 025).

The migration strategy should be rewritten as:
- Post-rebase, check whether `client_reference` column exists on `background_check_sequence`. If main's 025 already ran, it does not. In that case, migration 036 is a no-op for the column add but must still handle the unique index recreation.
- Migration 038 should be conditional on what the post-rebase schema actually looks like, not on the pre-rebase assumption.

### Amendment C — Add Snapshot Step to Epic 3

Before `git push --force-with-lease` triggers Railway deployment, add:

```
AC-3.0: Railway database snapshot taken and snapshot ID recorded
```

This is the only rollback mechanism once migrations run in production.

### Amendment D — Migration 038 Must Be Transactional

Wrap the entire migration 038 in `BEGIN/COMMIT`. Add a pre-flight check after the UPDATE and before the DROP:

```sql
DO $$
DECLARE unmapped_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO unmapped_count
    FROM check_types
    WHERE client_reference IS NOT NULL AND client_id IS NULL;

    IF unmapped_count > 0 THEN
        RAISE EXCEPTION 'Migration 038 aborted: % rows have unmapped client_reference values', unmapped_count;
    END IF;
END $$;
```

### Amendment E — Clarify AC-2.3 Migration Ordering

AC-2.3 says "Migrations 035-038 are sequentially ordered after main's latest migration." This is ambiguous. After rebase, if main's latest is 044, the feature branch's 035-038 would be lower-numbered. If the migration runner sorts by number, they execute before 043 and 044. If it sorts by commit timestamp, they execute after. The PRD must specify which ordering behavior applies and verify the runner produces the correct result.

---

## 5. VERDICT

**AMEND**

The PRD is not ready for execution as written. The critical issue is that Epic 1's premise (converting `client_reference` on `check_types`) is factually wrong based on the existing migration files, and the migration numbering interaction between the feature branch (035-038) and main (025, 043-044) creates a logical schema conflict that is not addressed anywhere in the PRD.

The deployment sequence itself (rebase, test, PR merge, Railway auto-deploy) is sound. The operational risks around Railway mid-execution failure are manageable with a pre-deployment snapshot. The seed data is correctly idempotent for first deployment.

The amendments required before execution:

1. (Blocking) Investigate Railway's applied migration state and the 026-042 gap.
2. (Blocking) Rewrite Epic 1 scope based on actual schema state, not assumed state.
3. (High) Add Railway snapshot as a mandatory pre-merge AC.
4. (High) Wrap migration 038 in a transaction with pre-flight data validation.
5. (Medium) Clarify migration runner ordering behavior post-rebase.

None of these require redesigning the architecture. All can be resolved in a single focused session before re-executing this PRD.
