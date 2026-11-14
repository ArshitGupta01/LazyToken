# LazyToken — active CLI and token-efficiency roadmap

LazyToken is a terminal-first, local AI coding memory/context CLI. The dashboard is optional. Default Windows data is `%LOCALAPPDATA%\LazyToken`; KN_HOME remains supported. Legacy stores are preserved and migrated only by explicit opt-in. Historical roadmap details remain in `docs/history/task-pre-cli.md`.

## Implemented; verify before distribution

- [x] CLI init/add/sync/context/search/doctor and optional dashboard.
- [x] Fresh initialization indexes no unselected project and imports no prototype seed data.
- [x] Explicit copy-only legacy migration with verified backup, collision refusal and guarded rollback.
- [x] Offline core with bundled Python/SQLite and local 2D/3D assets.
- [x] Setup preview, opt-in client entries, backups, guarded rollback and stable managed MCP path.
- [x] Managed install/update/rollback/uninstall entry points and owned user-PATH handling.
- [x] Checksum-required local/release installer with bounded safe archive extraction.
- [x] Context payload budgets, progressive memory expansion, session dedup and smaller opt-in MCP catalog.
- [x] Memory proposals; no MCP trust promotion; operator review checks live evidence.
- [x] Canonical benchmark record validation and explicit legacy/unverified records.
- [x] Unicode Git paths, common JS imports, bounded reads, explicit indexing errors and extractor-version refresh.
- [x] Dashboard inspector resizing, project-response race guard and all-node selector.

## Release gates

- [ ] Publish a separately authorized tested GitHub Release; no working public install URL yet.
- [ ] Code signing and complete dependency/distribution review.
- [ ] Clean-machine Windows and physically disconnected-network verification.
- [ ] Hosted CI result and external Codex/Antigravity connection verification.
- [ ] Broader touch/screen-reader/GPU stress and interrupted-update validation.

## Token-efficiency gates

- [ ] Human-reviewed representative relevance dataset and realistic profiling.
- [ ] Separately authorized matched agent tasks using provider-reported usage and correctness gates.
- [ ] Demonstrate lower total tokens per successful task after tool/retry/indexing overhead.
- [ ] Document/test supported assistant lifecycle hooks before offering automatic integration.

Do not run real agent tasks, push, publish a release, or claim token savings without the user's separate authorization/evidence. Keep scoped knowledge isolated, preserve databases/settings and avoid unnecessary dependencies.

- [x] Automatic selected-repository sync with debounce, bounded changed-file reads and evidence freshness.
- [x] Manifest/import-derived framework graph and explicit all-project visualization without widening scoped retrieval.
- [x] Fix six reproduced review defects: setup edit/receipt safety, empty search, verified rollback, strongest scoped graph evidence, and client configuration shape validation. See `docs/REVIEW_FIXES.md` for checks and limits.
