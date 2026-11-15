# Task release-review

Working root: D:\LazyToken
Run: readiness-20261115
Objective: Improve retrieval evaluation, first-run setup and release readiness for the attached review.
Role: lazytoken_reviewer
Contract: sha256:f7cacd8cb051ba835d11dbe38fed0b5a0ce50e9627a6ff66dbc80b27f6e51fa3

## Immutable inputs

- RELEASING.md
- build_release.ps1
- install.ps1
- manage_install.ps1
- THIRD_PARTY_NOTICES.md

## Decisions

- Distinguish locally verifiable release work from external gates; do not publish or alter user data.

## Skills to read

- (none)

## Write ownership

- (none)

## Acceptance

- Report reproducible release and dependency gaps with the smallest fixes and safe verification commands.

## Dependencies

- (none)

## Version evidence

```json
{
  "inputs": {
    "RELEASING.md": "sha256:26db8cc5d13a423cbf8d91b40e3b3afda2499b9ca0cd6c2b1f62e8b6f99a4ae3",
    "THIRD_PARTY_NOTICES.md": "sha256:5331f827bee53fba96919a174d7c0e1e42e41690701d86f2f78e9a1d954790ff",
    "build_release.ps1": "sha256:b8c6a5034d2c297c080584a3bbf3b73b1746324cd28d8c1a9fb0c8a839ba97a9",
    "install.ps1": "sha256:89f429e86e35950dfad6b3e2abdba66a7313f0f7a32151559e27ca590cfb1644",
    "manage_install.ps1": "sha256:01bf526cc700000f11b869cb6472800b4eeaadfd9d2d9a3884e0787f72f8d642"
  },
  "accepted_dependency_outputs": {}
}
```

You are not alone. Preserve others' changes and edit only assigned paths.
The parent owns the run ledger, shared configuration, integration, and acceptance.
Do not spawn agents. Return completed/blocked/failed with actual checks and evidence.
