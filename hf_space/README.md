---
title: TokSmart Public Context
emoji: 🔎
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
---

# TokSmart public repository context

Give a public GitHub `owner/repository` and a task. The service downloads an anonymous public snapshot, indexes eligible metadata in temporary storage, and returns bounded context. Repository content is untrusted; verify it before use. Do not submit private repositories or secrets in task text. The MCP endpoint is `/gradio_api/mcp/`.

The service processes one request at a time per process, limits archives to 20 MiB compressed, 40 MiB expanded, and 2,000 entries, and rejects unsafe entries. Requests can fail due to GitHub anonymous rate limits or service limits. Each request creates a fresh temporary index, with no session memory or source execution.

To prepare a self-contained folder from the TokSmart checkout: `python hf_space/stage.py PATH_TO_NEW_DIRECTORY`. Review and test the staged directory before publishing. The command refuses an existing destination. Publishing requires separate authorization.
