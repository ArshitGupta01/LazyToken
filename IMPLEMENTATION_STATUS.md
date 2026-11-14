# Implementation and release status

This records implemented behavior, not a production-readiness or token-savings claim.

- **Identity:** terminal-first CLI; no-argument executable prints help. 2D/3D dashboard remains optional and loopback-only.
- **Storage:** new default `%LOCALAPPDATA%\LazyToken`; KN_HOME override preserved. Legacy locations are detected only, with explicit copy migration, verified backup, collision refusal and guarded rollback. Production seed data disabled.
- **CLI:** init, add, sync (including previously selected projects), search, context, checkpoint, doctor, setup, MCP, migration, backup/restore and optional dashboard. Installed dispatcher handles update/rollback/uninstall outside the running executable. Separate guarded default-data deletion is explicit.
- **Setup:** discovers client binaries/config presence; previews before opt-in edits; preserves existing entries and unrelated settings; backs up exact bytes. Managed MCP registration uses a stable dispatcher across updates. CLI connection check verifies a server handshake only; external client behavior remains unverified.
- **Distribution:** standalone PyInstaller onedir runtime with a complete-file integrity manifest, release zip/checksums and bootstrap. Installer requires SHA-256, validates archive paths/links/limits and required files, and manages per-user PATH ownership. Prior versions remain available. No public release was accessible (GitHub API 404, 2026-11-14); public installation is blocked. No URL/release/push was published.
- **Context:** labelled default estimates; optional offline tokenizer-enforced JSON payload limits excluding transport/provider framing. Compact MCP catalog is opt-in. Cache survives internal session/telemetry writes; broker activity is recorded; asset summaries can be explicitly expanded under budget.
- **Learning:** pending task-finish checkpoints, explicit operator review, live evidence checks on approval/revalidation, indexed freshness and supersession. Similar text produces conflict-review candidates rather than blocking corrections. No automatic client hook or independent human identity authentication is claimed; OS-user shell/database access remains trusted.
- **Measurements:** canonical stored records share the file harness validator. Provenance, outcomes, reasoning accounting and pinned real snapshots are checked; missing data stays unknown. Legacy APIs/records are retained as unverified and cannot establish claims. No real tasks executed.
- **Index/UI fixes:** Unicode-safe Git listing, common JS imports, bounded source reads, reported errors and extractor-version refresh; ResizeObserver handles inspector resizing, request generations guard graph scope races, selector enables access to every displayed node, 3D rendering idles between interactions.

## Verification

Tests cover synthetic temporary databases, legacy detection/migration, checksum/traversal rejection, PATH ownership through a test store, client config preservation/rollback, and audit regressions. Final suite/build counts are recorded in the session report after execution. Existing user data/configuration are not test fixtures. CI definitions are prepared but hosted execution has not been demonstrated.

## Remaining blockers

The v0.4.2 cleanup separates the MCP catalog from CLI behavior, preserves its compatibility exports, formats handwritten Python/dashboard sources, and adds repeatable development checks. Additional guards cover malformed search/context/task inputs, duplicate client setup, invalid client/integrity configuration, failed dashboard reads, and stale workspace responses. Maintenance now resumes an existing watcher after failed updates and successful update/rollback. Final execution results are recorded in the cleanup report; this statement alone is not a claim that every environment has been tested.

Public release authorization/publication and code-signing identity are absent. Clean Windows VM, disconnected-network VM, complete dependency/license audit, external-client loading, real GPU loss and broad assistive-technology validation remain pending. Real task-token benefit requires separately authorized matched tasks and provider usage; it is not inferred from smaller schemas, passing tests or graph size.

A publisher certificate pin is supported and persists across updates; authentic signed-artifact verification remains untested without a signing identity. Portable updates now preserve their original PATH-registration choice. An initial smoke run transiently registered its temporary PATH entry, then uninstall removed it; subsequent smoke checks assert real user PATH equality before, during and after the portable lifecycle.


## Automatic synchronization / Ponytail fixes

A one-worker-per-store background watcher now handles eligible edits/additions/renames/deletions, updates indexed evidence freshness, and derives project/framework links. Metadata polling, debounce and changed-path hints avoid rereading unchanged files on ordinary edits. Full verification is periodic. Add/init/setup/MCP/dashboard start it for selected projects; maintenance stops it before touching executable versions. Automated lifecycle and framework tests cover temporary stores.

Ponytail review fixed import-like text inside JS literals, Python imports inside strings, failed-request transaction rollback/stale request IDs, and watcher lock/status diagnostics. Framework detection and workspace display preserve scoped retrieval and existing manually recorded knowledge. A manual authorized D-drive scan added eleven codebases to the existing store, with a verified pre-scan backup; source files and client settings were not changed. Ponytail 5.3.3 is installed at the user's request but remains optional for LazyToken users.
