---
name: lazytoken-orchestrator
description: Coordinate LazyToken implementation, review, and verification across project components. Use for multi-component changes and partial reruns; use the harness skill for harness maintenance.
---

# LazyToken orchestration

Inspect the current worktree, product contract, affected callers, and existing tests. Preserve user changes. The parent owns shared interfaces, integration, the run ledger, and completion decisions. Assign independent file ownership to workers and use a separate reviewer for validation.

Create a run with `.agents/skills/harness/scripts/run.py` using a project-local plan with concrete inputs, ownership, dependencies, decisions, and checks. Follow `.agents/skills/harness/references/runtime-guide.md` for native agent preflight, result registration, lifecycle, and communication. Use the project role definitions as instructions if the current session does not discover them. Do not claim native execution succeeded from local ledger changes alone.

Run focused checks when a component is ready, then the applicable project suite. Treat failing or unrun checks as unresolved. Resume with a new run when inputs or contracts change, and preserve prior records. Reassign ownership only after observing the previous worker idle or stopped.

Normal case: independent implementation and review, then integration checks. Failure: record the failure and retry a bounded correction; report remaining failures. Partial rerun: fingerprint changed inputs and repeat affected work and downstream checks.
