# Task space

Working root: D:\LazyToken
Run: public-release-20261115
Objective: Prepare a public Hugging Face MCP Space for public GitHub repositories and a distributable CLI.
Role: lazytoken_worker
Contract: sha256:fb453f4324c184212375ff10bb1cb5be88845e092e9d51cef3e1a6095c0493e9

## Immutable inputs

- kn.py
- broker.py
- features.py
- frameworks.py
- source_index.py

## Decisions

- The user chose a public remote Space for public GitHub repositories only. Never expose arbitrary filesystem or existing local MCP operations. Each request must use isolated temporary data; validate repository identifiers, restrict outbound hosts and redirects, cap download and extraction resources, avoid running repository code, and prevent cross-request leakage. Follow Gradio MCP Space conventions, implement useful retrieval using existing LazyToken, and make the staged Space self-contained.

## Skills to read

- (none)

## Write ownership

- hf_space/
- tests/test_hf_space.py

## Acceptance

- Deliver Space source and staging procedure with meaningful isolated tests and report remaining security or hosting limits.

## Dependencies

- (none)

## Version evidence

```json
{
  "inputs": {
    "broker.py": "sha256:8bb1cb4ab63f42573081f4ffe087ef4d5de2ca8912aa4484c0a5f583b6ce126b",
    "features.py": "sha256:725771480f6a4e78f9fa41d0c05ea616ba124213d31f9cbd36914d5a9f948dc6",
    "frameworks.py": "sha256:3906f673094e4906e6e49e739eeac10a229f9ceb779e89c1b593edf85e0fbc37",
    "kn.py": "sha256:5563fc3c736835bb01ba89d6f8b88b2254b5703e0fb71e44b3d0272d4c3debbe",
    "source_index.py": "sha256:dab5d5eee328fe1bded13dbcd077ddb43d7bd94d58b50bbee936b79370dc62e5"
  },
  "accepted_dependency_outputs": {}
}
```

You are not alone. Preserve others' changes and edit only assigned paths.
The parent owns the run ledger, shared configuration, integration, and acceptance.
Do not spawn agents. Return completed/blocked/failed with actual checks and evidence.
