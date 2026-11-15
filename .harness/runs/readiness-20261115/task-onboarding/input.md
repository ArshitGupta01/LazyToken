# Task onboarding

Working root: D:\LazyToken
Run: readiness-20261115
Objective: Improve retrieval evaluation, first-run setup and release readiness for the attached review.
Role: lazytoken_worker
Contract: sha256:44a6e9c5076351df2cc35bc6b279212988a20b44bddf6f0b413c408f364612a9

## Immutable inputs

- docs/CLI.md
- kn.py

## Decisions

- Preserve opt-in configuration, rollback safety, existing user changes and JSON callers.

## Skills to read

- (none)

## Write ownership

- onboarding.py
- tests/test_onboarding.py

## Acceptance

- Identify and implement a concrete first-run usability improvement with meaningful checks, or report evidence why none is safe.

## Dependencies

- (none)

## Version evidence

```json
{
  "inputs": {
    "docs/CLI.md": "sha256:875c84f0f93ddc3af817ae7a6d5ceb4cf88706c0aa9d121ff05be4d173644d04",
    "kn.py": "sha256:5563fc3c736835bb01ba89d6f8b88b2254b5703e0fb71e44b3d0272d4c3debbe"
  },
  "accepted_dependency_outputs": {}
}
```

You are not alone. Preserve others' changes and edit only assigned paths.
The parent owns the run ledger, shared configuration, integration, and acceptance.
Do not spawn agents. Return completed/blocked/failed with actual checks and evidence.
