# Task retrieval

Working root: D:\LazyToken
Run: readiness-20261115
Objective: Improve retrieval evaluation, first-run setup and release readiness for the attached review.
Role: lazytoken_worker
Contract: sha256:3a4dcebb506d2448cd3182bf98ce2e7a14bc420ca3ae9fff030c2425cb3ecb3e

## Immutable inputs

- retrieval_eval.py
- benchmark/fixture_sessions
- benchmark/fixture_notebook
- task.md

## Decisions

- Do not claim agent-authored labels are independently human-reviewed or representative; measure actual retrieval including changed, renamed and removed files.

## Skills to read

- (none)

## Write ownership

- benchmark/retrieval_cases.json
- benchmark/retrieval_assessment.py
- tests/test_retrieval_assessment.py
- docs/RETRIEVAL_ASSESSMENT.md

## Acceptance

- Deliver reproducible actual retrieval evaluation with clearly identified evidence and meaningful tests, or explain limitations.

## Dependencies

- (none)

## Version evidence

```json
{
  "inputs": {
    "benchmark/fixture_notebook": "sha256:29de810c515ebdf125d7fb060c66b3c390f0b456910b8ed355c72d58a76f7f21",
    "benchmark/fixture_sessions": "sha256:1812ebe27f09a074cc125ed48298f0c7e51a4cfa7c7f625770ab8aee96ee2f7b",
    "retrieval_eval.py": "sha256:ec81671a208901ab517ae44a18b075f63010cf21a8e74842027d1663346b2061",
    "task.md": "sha256:cd277d1462b30d9d52835f0257deeb581bff572f12d23af9dcbe9ab7f8679805"
  },
  "accepted_dependency_outputs": {}
}
```

You are not alone. Preserve others' changes and edit only assigned paths.
The parent owns the run ledger, shared configuration, integration, and acceptance.
Do not spawn agents. Return completed/blocked/failed with actual checks and evidence.
