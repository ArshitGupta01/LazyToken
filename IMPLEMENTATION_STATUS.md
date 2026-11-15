# Implementation and release status

This records implemented behavior, not a production-readiness or token-savings claim.

- **Identity:** terminal-first CLI; no-argument executable prints help. 2D/3D dashboard remains optional and loopback-only.
- **Storage:** new default `%LOCALAPPDATA%\LazyToken`; KN_HOME override preserved. Legacy locations are detected only, with explicit copy migration, verified backup, collision refusal and guarded rollback. Production seed data disabled.
- **CLI:** init, add, sync (including previously selected projects), search, context, checkpoint, doctor, setup, MCP, migration, backup/restore and optional dashboard. Installed dispatcher handles update/rollback/uninstall outside the running executable. Separate guarded default-data deletion is explicit.
- **Setup:** discovers client binaries/config presence; previews before opt-in edits; preserves existing entries and unrelated settings; backs up exact bytes. Managed MCP registration uses a stable dispatcher across updates. CLI connection check verifies a server handshake and tool discovery; external client loading remains unverified.
- **Distribution:** standalone PyInstaller onedir runtime with a complete-file integrity manifest, release zip/checksums and bootstrap. Installer requires SHA-256, validates archive paths/links/limits and required files, and manages per-user PATH ownership. Prior versions remain available. No public release was accessible (GitHub API 404, 2026-11-14); public installation is blocked. No URL/release/push was published.
- **Context:** labelled default estimates; optional offline tokenizer-enforced JSON payload limits excluding transport/provider framing. Compact MCP catalog is opt-in. Cache survives internal session/telemetry writes; broker activity is recorded; asset summaries can be explicitly expanded under budget.
- **Learning:** pending task-finish checkpoints, explicit operator review, live evidence checks on approval/revalidation, indexed freshness and supersession. Similar text produces conflict-review candidates rather than blocking corrections. No automatic client hook or independent human identity authentication is claimed; OS-user shell/database access remains trusted.
- **Measurements:** canonical stored records share the file harness validator. Provenance, outcomes, reasoning accounting and pinned real snapshots are checked; missing data stays unknown. Legacy APIs/records are retained as unverified and cannot establish claims. An explicitly authorized real-agent micro-pilot is recorded in `docs/BENCHMARK_PILOT.md`: seven successful runs, two excluded infrastructure failures, mixed token results, and no observed graph-tool use. General savings remain unproven.
- **Index/UI fixes:** Unicode-safe Git listing, common JS imports, bounded source reads, reported errors and extractor-version refresh; ResizeObserver handles inspector resizing, request generations guard graph scope races, selector enables access to every displayed node, 3D rendering idles between interactions.

## Verification

On November 15, the local tree passed 120 Python tests (one skipped), three dashboard tests, and formatting checks. The `release/push-validation-candidate` standalone Windows package passed the isolated release smoke test, including MCP, dashboard, installation and update/rollback. This is a local candidate, not a published release. The agent pilots remain inconclusive; see `docs/BENCHMARK_PILOT.md` for measurements and limitations.

The MCP server now negotiates supported handshake versions and handles malformed input without executing request-shaped notifications. The current suite passed 110 tests with one Windows symlink test skipped. A separate isolated Codex run successfully called `get_task_context` when explicitly asked; this confirms client tool loading for that setup, not automatic usage or token savings.

`context --prompt` optionally combines a task with bounded, untrusted project metadata for an agent's initial prompt; it starts no agent and emits the task alone when retrieval abstains. Two isolated same-task brief experiments had mixed token results; see `docs/BENCHMARK_PILOT.md`. The updated tree passed 111 Python tests (one skipped), three dashboard tests, and the isolated `release/context-prompt-candidate` standalone smoke test, including the new prompt output. This build is a local candidate, not a published release.

Expanded memory retrieval falls back to a compact memory when its summary does not fit, preserving the option to expand it later. Session deduplication suppresses a compact repeat after an unchanged expanded result, but returns changed evidence.

Retrieval labels the indexed basis of current memory, warns when evidence is stale or unavailable, and down-ranks unavailable evidence while retaining directly matched stale memories.

Session checkpoints report the most recently supplied keys, with a bounded 30-key result and an exact project/session-scoped total from one database snapshot.

Compact task context omits a redundant file entry when a higher-ranked included or previously supplied symbol/import already provides that path; distinct symbols and dependencies remain. On the prepared session fixture, the context estimate dropped from 441 to 384 tokens with the same directly referenced paths. This is an offline payload estimate, not a provider-token benchmark. The current tree passed 120 Python tests, one skipped.

Two order-reversed matched pairs on a larger synthetic source-tree task used 283,985 baseline tokens and 263,203 with a preloaded context brief; this is limited to one task and does not establish general savings. `context --prompt` subsequently removed unnecessary bookkeeping while retaining scope and budget labels; strict counts are rechecked before output. The updated tree passed 118 Python tests, one skipped; the earlier package candidate predates these changes. See `docs/BENCHMARK_PILOT.md` for cached counts, correctness checks and limitations.

The v0.4.4 reuse-first integration sends brief workflow guidance in MCP initialization for full and compact catalogs. Initial memory breadcrumbs include verification state and freshness without automatically expanding lesson text. End-to-end regression coverage follows existing code and an approved lesson, inspects source, suppresses repeated session context, flags changed evidence and saves a new lesson as pending. Local verification passed 103 tests (102 passed, one Windows symlink test skipped for missing privileges). This provides guidance through existing tools; it does not enforce agent behavior, install client hooks or demonstrate provider-token savings.

The earlier `release/reuse-first-candidate` Windows x64 package passed `python tests/smoke_release.py release/reuse-first-candidate`, including compact MCP initialization with reuse-first instructions, bounded retrieval, bundled tokenizer/runtime, dashboard, watcher and isolated install/update/rollback/uninstall. Python and Node were absent from its child PATH, and real user PATH equality was checked. Archive SHA-256: `05ea8b7022d45b937d12e7eb67f7e7daea2dfee88e1083a4b8868e769a623c87`. This candidate has not been published; live client adherence is unverified.

Tests cover synthetic temporary databases, legacy detection/migration, checksum/traversal rejection, PATH ownership through a test store, client config preservation/rollback, and audit regressions. The v0.4.3 review fixes pass 100 tests (99 passed, one skipped); see `docs/REVIEW_FIXES.md` for the exact cases and packaged verification. Existing user data/configuration are not test fixtures. Hosted CI for these local changes has not been demonstrated.

## Remaining blockers

The v0.4.2 cleanup separates the MCP catalog from CLI behavior, preserves its compatibility exports, formats handwritten Python/dashboard sources, and adds repeatable development checks. Additional guards cover malformed search/context/task inputs, duplicate client setup, invalid client/integrity configuration, failed dashboard reads, and stale workspace responses. Maintenance now resumes an existing watcher after failed updates and successful update/rollback. Final execution results are recorded in the cleanup report; this statement alone is not a claim that every environment has been tested.

Public release authorization/publication and code-signing identity are absent. Clean Windows VM, disconnected-network VM, complete dependency/license audit, external-client loading, real GPU loss and broad assistive-technology validation remain pending. Real task-token benefit requires separately authorized matched tasks and provider usage; it is not inferred from smaller schemas, passing tests or graph size.

A publisher certificate pin is supported and persists across updates; authentic signed-artifact verification remains untested without a signing identity. Portable updates now preserve their original PATH-registration choice. An initial smoke run transiently registered its temporary PATH entry, then uninstall removed it; subsequent smoke checks assert real user PATH equality before, during and after the portable lifecycle.


## Automatic synchronization / Ponytail fixes

A one-worker-per-store background watcher now handles eligible edits/additions/renames/deletions, updates indexed evidence freshness, and derives project/framework links. Metadata polling, debounce and changed-path hints avoid rereading unchanged files on ordinary edits. Full verification is periodic. Add/init/setup/MCP/dashboard start it for selected projects; maintenance stops it before touching executable versions. Automated lifecycle and framework tests cover temporary stores.

Ponytail review fixed import-like text inside JS literals, Python imports inside strings, failed-request transaction rollback/stale request IDs, and watcher lock/status diagnostics. Framework detection and workspace display preserve scoped retrieval and existing manually recorded knowledge. A manual authorized D-drive scan added eleven codebases to the existing store, with a verified pre-scan backup; source files and client settings were not changed. Ponytail 5.3.3 is installed at the user's request but remains optional for LazyToken users.
