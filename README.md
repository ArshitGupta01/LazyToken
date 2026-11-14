# LazyToken

**Local-first AI coding memory and context optimization, from your terminal.**

LazyToken indexes repositories you choose and gives coding assistants compact, project-scoped context through MCP. It ranks paths, declarations, imports and knowledge links, suppresses repeated session context, and keeps reusable lessons behind an explicit review step.

Indexing and retrieval run locally without model calls. **End-to-end token savings have not been measured.**

## Installation status

The current version is **0.4.2**, with a tested Windows x64 package candidate. It bundles Python, SQLite, the memory engine, Context Broker, MCP server and local dashboard assets. End users do not need separately installed Python or Node.js.

**Public installation is not available yet.** The public latest-release endpoint returned HTTP 404 on November 15, 2026. Pushing source does not publish a release. See [RELEASING.md](RELEASING.md) for the remaining distribution steps.

If you already have an independently verified local archive and matching bootstrap, replace the checksum placeholder and install with:

```powershell
powershell -NoProfile -File .\bootstrap.ps1 -PackagePath .\lazytoken-v0.4.2-windows-x64.zip -ExpectedSha256 <trusted-64-character-SHA256>
```

The bootstrap is named `install.ps1` in the source checkout. It verifies the package before running its installer, installs per user and registers the managed CLI on your user PATH. Open a new terminal afterward. Installation preserves knowledge data and does not select repositories or edit assistant settings.

Same-channel checksums detect corruption, but do not independently protect against a compromised publisher. Signed-artifact validation and clean-machine verification remain pending. No remote `irm ... | iex` command is advertised as working.

## Quick start

After installing the CLI:

```powershell
lazytoken init
lazytoken add "C:\Projects\MyApp"
lazytoken setup --project "C:\Projects\MyApp" --client codex
```

`setup` previews assistant configuration. Apply the reviewed change explicitly:

```powershell
lazytoken setup --project "C:\Projects\MyApp" --client codex --apply
lazytoken setup --test-connection
lazytoken doctor
```

Restart your coding assistant and check its MCP tools. Setup preserves unrelated settings and existing LazyToken entries, creates backups, and supports guarded rollback. The local handshake tests the server, not whether a client loaded it.

Codex uses TOML `mcp_servers`. `--client antigravity` supports the existing JSON `mcpServers` adapter. Live loading in every client/version is not verified; no assistant lifecycle hook is silently installed.

For a **source checkout**, contributors need Python 3.11+ and can use `python app_entry.py COMMAND`. Installation lifecycle commands require the managed installed launcher.

## Retrieve context for a task

```powershell
lazytoken context --project "C:\Projects\MyApp" --task "Where is authentication handled?" --budget 600 --session-id auth-fix
```

- Ranked metadata includes retrieval reasons and initially avoids source excerpts.
- Reusing a session ID suppresses unchanged context already supplied. `--expand-assets` includes memory summaries and provenance within the budget.
- Budgets default to labelled character estimates. Optional strict budgets require a matching offline tokenizer and cover compact JSON, excluding MCP/provider framing.
- Explicit source inspection is bounded; source remains untrusted data and credential redaction is best effort.

## Automatic synchronization and memory

Adding a repository starts one background worker for the selected store. Eligible edits, additions, renames and deletions update indexed metadata, framework links and evidence freshness. MCP and the dashboard can also start it for an indexed store.

```powershell
lazytoken watch status
lazytoken watch stop
lazytoken watch start
```

The worker polls and debounces changes; updates usually take a few seconds. Periodic full verification handles timestamp-preserving edits. It continues after the client closes, but is **not a Windows login service**. `LAZYTOKEN_DISABLE_AUTOWATCH=1` disables automatic startup. Unavailable repositories retain their indexes and become unverified until recovery.

Automatic indexing does **not** approve lessons. An agent submits a task-finish suggestion with evidence; a person reviews, edits, approves or rejects it through the local dashboard or operator CLI. MCP cannot approve, revalidate or supersede memories. Evidence hashes flag changed or deleted sources for review.

## Optional graph dashboard

```powershell
lazytoken dashboard
```

The dashboard binds to `127.0.0.1`, defaults to port `8765`, and needs no separate web server. It offers a 2D graph, optional 3D loaded on demand, search/filter controls, a minimizable node inspector, evidence, proposal review and recorded benchmark comparisons.

**All projects** shows indexed projects and their framework relationships together. Project retrieval stays isolated; the shared catalog remains separate. Dependency links are provisional metadata, not compiler-resolved proof of production behavior. Visible graph data refreshes every ten seconds. Unmeasured token savings stay **Not measured**.

## Commands and data

| Command                         | Purpose                                                                                             |
| ------------------------------- | --------------------------------------------------------------------------------------------------- |
| `lazytoken init` / `add PATH`   | Initialize storage and select repositories.                                                         |
| `lazytoken sync`                | Refresh previously selected repositories.                                                           |
| `lazytoken context ...`         | Retrieve bounded task context.                                                                      |
| `lazytoken watch status`        | Inspect automatic synchronization.                                                                  |
| `lazytoken doctor`              | Check storage, runtime, client settings and dashboard availability.                                 |
| `lazytoken dashboard`           | Open the optional local graph.                                                                      |
| `lazytoken update` / `rollback` | Verify an update or select the prior installed version. Public updates require a published release. |
| `lazytoken uninstall --yes`     | Remove the managed application while retaining knowledge data.                                      |

See the [full CLI reference](docs/CLI.md) for flags, structured actions, local upgrades, backups and maintenance.

Fresh data lives at **`%LOCALAPPDATA%\LazyToken\network.sqlite3`**. `KN_HOME` preserves an explicit alternative directory. No repository is assumed and no unrelated prototype data is imported. Legacy migration requires explicit opt-in, creates a verified backup, and never merges or overwrites stores. See [data and migration](docs/MIGRATION.md).

## Verification and development

Local v0.4.2 validation completed **92 tests: 91 passed, one skipped**, including a wrapper for three workspace race scenarios. The Windows candidate passed bundled-runtime, MCP, dashboard, background-sync and install/update/rollback/uninstall checks with Python and Node absent from its child PATH. This is not clean-machine or comprehensive browser/device certification.

Benchmark records use manually supplied usage and outcomes; missing measurements remain unknown. Synthetic tests check calculations. **No real coding-agent benchmarks have been run and no measured token-savings claim is made.**

- [Development guide](docs/DEVELOPMENT.md): source map, formatting and tests. Node is optional for dashboard development checks, not a CLI runtime dependency.
- [Implementation status](IMPLEMENTATION_STATUS.md): implemented behavior and remaining verification gaps.
- [Release procedure](RELEASING.md): packaging, integrity and publication requirements.
- [Policy](POLICY.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

`docs/history/` retains historical pilot documents for compatibility context, not current installation guidance.
