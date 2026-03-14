# Harness Documentation Gardening Report

**Generated**: 2026-03-14T19:59:04
**Target**: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude`
**Mode**: EXECUTE (fixes applied)

## Summary

- **Files scanned**: 454
- **Total violations found**: 188
- **Auto-fixed**: 0
- **Remaining violations**: 188

### Before

| Severity | Count |
|----------|-------|
| Errors   | 83 |
| Warnings | 101 |
| Info     | 4 |
| Fixable  | 0 |

### After Auto-fix

| Severity | Count |
|----------|-------|
| Errors   | 83 |
| Warnings | 101 |
| Info     | 4 |

## Manual Fix Required (Doc-Debt)

These violations require human attention:

| File | Category | Severity | Message |
|------|----------|----------|---------|
| `attractor/pipelines/evidence/PRD-DASHBOARD-AUDIT-001-impl-research/research_backend_sd.md` | naming | warning | Directory 'PRD-DASHBOARD-AUDIT-001-impl-research' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `attractor/pipelines/evidence/PRD-DASHBOARD-AUDIT-001-impl-research/research_backend_sd.md` | naming | warning | Filename 'research_backend_sd.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/PRD-DASHBOARD-AUDIT-001-impl-research/research_perstep.md` | naming | warning | Directory 'PRD-DASHBOARD-AUDIT-001-impl-research' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `attractor/pipelines/evidence/PRD-DASHBOARD-AUDIT-001-impl-research/research_perstep.md` | naming | warning | Filename 'research_perstep.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/cobuilder-upgrade-e04/research_eventbus.md` | naming | warning | Filename 'research_eventbus.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/research_e2e_findings.md` | naming | warning | Filename 'research_e2e_findings.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/research_email_templates.md` | naming | warning | Filename 'research_email_templates.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/research_frontend_case_detail_page.md` | naming | warning | Filename 'research_frontend_case_detail_page.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/research_gaps_findings.md` | naming | warning | Filename 'research_gaps_findings.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/research_pydantic_run_stream.md` | frontmatter | error | Invalid type 'research'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `attractor/pipelines/evidence/research_pydantic_run_stream.md` | naming | warning | Filename 'research_pydantic_run_stream.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/evidence/seq-retry-loop-impl/email_dispatch_system_research.md` | naming | warning | Filename 'email_dispatch_system_research.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `attractor/pipelines/simple-pipeline-run-20260304T003643Z/nodes/impl_task/prompt.md` | naming | warning | Directory 'simple-pipeline-run-20260304T003643Z' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `documentation/SD-TEMPLATE-SYSTEM-AND-S3-META-PIPELINE.md` | grades-sync | info | Grade 'authoritative' differs from directory default 'reference' for documentation/. Consider adding a fileOverride in quality-grades.json |
| `documentation/attractor-spec-reference.md` | crosslinks | error | Broken link: [Coding Agent Loop](./coding-agent-loop-spec.md) |
| `documentation/attractor-spec-reference.md` | crosslinks | error | Broken link: [Unified LLM Client](./unified-llm-spec.md) |
| `documentation/concern-queue-schema.md` | grades-sync | info | Grade 'authoritative' differs from directory default 'reference' for documentation/. Consider adding a fileOverride in quality-grades.json |
| `documentation/living-narrative-protocol.md` | grades-sync | info | Grade 'authoritative' differs from directory default 'reference' for documentation/. Consider adding a fileOverride in quality-grades.json |
| `documentation/session-handoff-format.md` | grades-sync | info | Grade 'authoritative' differs from directory default 'reference' for documentation/. Consider adding a fileOverride in quality-grades.json |
| `worktrees/attractor-merge/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/attractor-merge/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/attractor-merge/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/attractor-merge/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md#troubleshooting) |
| `worktrees/attractor-merge/acceptance-tests/PRD-P1.1-UEA-DEPLOY-001/design-challenge.md` | naming | warning | Directory 'PRD-P1.1-UEA-DEPLOY-001' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/attractor-merge/acceptance-tests/PRD-PIPELINE-ENGINE-001/revalidation-2026-03-03.md` | naming | warning | Directory 'PRD-PIPELINE-ENGINE-001' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/attractor-merge/acceptance-tests/PRD-UEA-001/IMPLEMENTATION_GAPS.md` | naming | warning | Directory 'PRD-UEA-001' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/attractor-merge/docs/guides/observability.md` | crosslinks | error | Broken link: [VALIDATION.md](../../skills/orchestrator-multiagent/VALIDATION.md#level-4-deploy-health-logfire-observability) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [attractor-spec-reference.md](./../documentation/attractor-spec-reference.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [sdk-vs-subprocess-analysis.md](./docs/references/sdk-vs-subprocess-analysis.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [attractor-spec-reference.md](./../documentation/attractor-spec-reference.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [sdk-vs-subprocess-analysis.md](./references/sdk-vs-subprocess-analysis.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./references/gastown-comparison.md) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [Logfire trace 2026-03-02](logfire) |
| `worktrees/attractor-merge/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [promise-7bfe8dc9.json](./../completion-state/promises/promise-7bfe8dc9.json) |
| `worktrees/attractor-merge/docs/sds/SD-COBUILDER-001-three-way-context.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic1-core-engine.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic1-core-engine.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic2-validation.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic2-validation.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic4-event-bus.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/sds/SD-PIPELINE-ENGINE-001-epic4-event-bus.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/attractor-merge/docs/sds/design-challenge-PRD-PIPELINE-ENGINE-001.md` | naming | warning | Filename 'design-challenge-PRD-PIPELINE-ENGINE-001.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/solution-designs/SD-ATTRACTOR-SDK-001-E1-worker-backend.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E1-worker-backend.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/solution-designs/SD-ATTRACTOR-SDK-001-E2-mode-aware-monitor.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E2-mode-aware-monitor.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/solution-designs/SD-ATTRACTOR-SDK-001-E3-signal-protocol.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E3-signal-protocol.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/solution-designs/SD-ATTRACTOR-SDK-001-E4-baton-passing.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E4-baton-passing.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/solution-designs/SD-ATTRACTOR-SDK-001-E5-three-layer-context.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E5-three-layer-context.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/attractor-merge/docs/tests/COVERAGE_GAP_REPORT.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/COVERAGE_GAP_REPORT.md` | frontmatter | error | Invalid type 'coverage-report'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/tests/specs/api-credential-verification.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/specs/api-credential-verification.md` | frontmatter | error | Invalid type 'api'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/tests/specs/api-health-check.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/specs/api-health-check.md` | frontmatter | error | Invalid type 'api'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/tests/specs/chat-send-message.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/specs/chat-send-message.md` | frontmatter | error | Invalid type 'e2e-browser'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/tests/specs/chat-session-management.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/specs/chat-session-management.md` | frontmatter | error | Invalid type 'e2e-browser'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/docs/tests/specs/visual-chat-interface.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/attractor-merge/docs/tests/specs/visual-chat-interface.md` | frontmatter | error | Invalid type 'visual'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/attractor-merge/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Environment Configuration Reference](references/environment-config.md) |
| `worktrees/attractor-merge/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Variables Reference](references/variables.md) |
| `worktrees/attractor-merge/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Deployment Management](../skills/railway-deployment/SKILL.md) |
| `worktrees/attractor-merge/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Project Management](../skills/railway-projects/SKILL.md) |
| `worktrees/impl_auth/ARCHITECTURE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/CLAUDE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/impl_auth/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/impl_auth/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| `worktrees/impl_auth/README.md` | crosslinks | error | Broken link: [SETUP_GUIDE.md](./SETUP_GUIDE.md#troubleshooting) |
| `worktrees/impl_auth/README.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/acceptance-tests/PRD-P1.1-UEA-DEPLOY-001/design-challenge.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/acceptance-tests/PRD-PIPELINE-ENGINE-001/revalidation-2026-03-03.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/acceptance-tests/PRD-UEA-001/IMPLEMENTATION_GAPS.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/ARCHITECTURE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/CONFIGURATION.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/EVALUATION.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/MODULES.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/PRD-SYSTEM3-ORCHESTRATOR-AUTONOMY-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/PRODUCTION_READINESS.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/README.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/USAGE_GUIDE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/ZEROREPO_DELTA_DESIGN.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/ZEROREPO_SERENA_DESIGN.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/design-references/unified-form-page-stitch-design.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/guides/observability.md` | crosslinks | error | Broken link: [VALIDATION.md](../../skills/orchestrator-multiagent/VALIDATION.md#level-4-deploy-health-logfire-observability) |
| `worktrees/impl_auth/docs/guides/observability.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [attractor-spec-reference.md](./../documentation/attractor-spec-reference.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [sdk-vs-subprocess-analysis.md](./docs/references/sdk-vs-subprocess-analysis.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./docs/references/gastown-comparison.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [attractor-spec-reference.md](./../documentation/attractor-spec-reference.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [sdk-vs-subprocess-analysis.md](./references/sdk-vs-subprocess-analysis.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [gastown-comparison.md](./references/gastown-comparison.md) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [Logfire trace 2026-03-02](logfire) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | crosslinks | error | Broken link: [promise-7bfe8dc9.json](./../completion-state/promises/promise-7bfe8dc9.json) |
| `worktrees/impl_auth/docs/prds/GAP-PRD-ATTRACTOR-SDK-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/PRD-COBUILDER-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/PRD-PIPELINE-ENGINE-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/SD-COBUILDER-001-context-injection.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/SD-COBUILDER-001-foundation.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/SD-COBUILDER-001-live-updates.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/SD-COBUILDER-001-pipeline-generation.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/SD-ZEROREPO-DOT-INTEGRATION-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/prds/agent-library-improvements.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/references/gastown-comparison.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/references/sdk-vs-subprocess-analysis.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/attractor-community-implementations.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/attractor-spec-analysis.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/dot-attractor-pipeline-capabilities.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/prd-sd-creation-workflow.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/zerorepo-implementation-status.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/research/zerorepo-paper-summary.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-COBUILDER-001-three-way-context.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/sds/SD-COBUILDER-001-three-way-context.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic1-core-engine.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic1-core-engine.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic1-core-engine.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic2-validation.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic2-validation.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic2-validation.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic4-event-bus.md` | frontmatter | error | Invalid type 'solution-design'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic4-event-bus.md` | frontmatter | error | Invalid last_verified date format: '2026-03-04T00:00:00.000Z'. Expected YYYY-MM-DD |
| `worktrees/impl_auth/docs/sds/SD-PIPELINE-ENGINE-001-epic4-event-bus.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/SD-PYDANTICAI-WEBSEARCH-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/design-challenge-PRD-PIPELINE-ENGINE-001.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/sds/design-challenge-PRD-PIPELINE-ENGINE-001.md` | naming | warning | Filename 'design-challenge-PRD-PIPELINE-ENGINE-001.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E1-worker-backend.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E1-worker-backend.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E1-worker-backend.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E2-mode-aware-monitor.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E2-mode-aware-monitor.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E2-mode-aware-monitor.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E3-signal-protocol.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E3-signal-protocol.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E3-signal-protocol.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E4-baton-passing.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E4-baton-passing.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E4-baton-passing.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E5-three-layer-context.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/solution-designs/SD-ATTRACTOR-SDK-001-E5-three-layer-context.md` | naming | warning | Filename 'SD-ATTRACTOR-SDK-001-E5-three-layer-context.md' doesn't follow naming conventions. Expected: kebab-case.md, UPPER_CASE.md, UPPER-kebab.md, v1.0-kebab.md, or _private.md |
| `worktrees/impl_auth/docs/tests/COVERAGE_GAP_REPORT.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/COVERAGE_GAP_REPORT.md` | frontmatter | error | Invalid type 'coverage-report'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/COVERAGE_GAP_REPORT.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/TEST_SPEC_FORMAT.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/specs/api-credential-verification.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/specs/api-credential-verification.md` | frontmatter | error | Invalid type 'api'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/specs/api-credential-verification.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/specs/api-health-check.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/specs/api-health-check.md` | frontmatter | error | Invalid type 'api'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/specs/api-health-check.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/specs/chat-send-message.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/specs/chat-send-message.md` | frontmatter | error | Invalid type 'e2e-browser'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/specs/chat-send-message.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/specs/chat-session-management.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/specs/chat-session-management.md` | frontmatter | error | Invalid type 'e2e-browser'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/specs/chat-session-management.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/docs/tests/specs/visual-chat-interface.md` | frontmatter | error | Missing required frontmatter field: status |
| `worktrees/impl_auth/docs/tests/specs/visual-chat-interface.md` | frontmatter | error | Invalid type 'visual'. Must be one of: agent, architecture, command, config, guide, hook, output-style, reference, skill |
| `worktrees/impl_auth/docs/tests/specs/visual-chat-interface.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/ADR-001-output-style-reliability.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/DECISION_TIME_GUIDANCE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/NATIVE-TEAMS-EPIC1-FINDINGS.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/ORCHESTRATOR_ARCHITECTURE_V2.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/SOLUTION-DESIGN-acceptance-testing.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/STOP_GATE_CONSOLIDATION.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/SYSTEM3_CHANGELOG.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/SYSTEM3_MONITORING_ARCHITECTURE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/UPDATE-validation-agent-integration.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/VALIDATION_AGENT_MONITOR_MODE.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/guides/agent-pr-validation.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Environment Configuration Reference](references/environment-config.md) |
| `worktrees/impl_auth/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Variables Reference](references/variables.md) |
| `worktrees/impl_auth/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Deployment Management](../skills/railway-deployment/SKILL.md) |
| `worktrees/impl_auth/documentation/guides/pr-environments.md` | crosslinks | error | Broken link: [Railway Project Management](../skills/railway-projects/SKILL.md) |
| `worktrees/impl_auth/documentation/guides/pr-environments.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/learnings/coordination.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/learnings/decomposition.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/learnings/failures.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/tests/hooks/README.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/validation/MONITOR_MODE_QUICK_START.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/validation/README.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/validation/evidence-templates.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
| `worktrees/impl_auth/validation/validation-request-protocol.md` | naming | warning | Directory 'impl_auth' doesn't follow kebab-case convention. Expected: lowercase-with-hyphens |
