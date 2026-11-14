# LazyToken Knowledge Network pilot

This is a local, standard-library-only Python pilot for a reusable asset graph and an incremental per-project source graph. The SQLite database lives under `%LOCALAPPDATA%\TheekHai\KnowledgeNetwork`; source code and secrets are never sent to a hosted service. The stdio MCP server exposes compact local tools to Antigravity and Codex. Search/indexing are deterministic and make no model call. When available, SQLite FTS5 adds prefix matching over indexed file paths, declarations, and imports; otherwise lexical search remains available. FTS indexes metadata only and is updated during sync.

## Install on Windows

From PowerShell:

```powershell
cd D:\LazyToken
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

To also add the local stdio server to the current Windows profile's Antigravity and Codex configs, use `-ConfigureClients`. Existing unrelated entries are retained; only missing named entries are added, and the script makes a timestamped backup before changing an existing config file.

```powershell
.\install.ps1 -ConfigureClients
```

Python 3.11+ is sufficient for the pilot. The script initializes the local database, indexes the LazyToken folder by default, runs the self-checks, and writes `mcp_config.json`. To index TheekHai during setup, pass `-ProjectRoot D:\TheekHai`. It does not alter client settings or install extra packages. To also install optional Code-Graph-RAG using `uv`:

```powershell
.\install.ps1 -InstallCodeGraphRag
```

Code-Graph-RAG currently documents Python 3.12+, `ripgrep`, and the `treesitter-full`, `ast-grep`, and `semantic` extras. Its [main README](https://github.com/vitali87/code-graph-rag/blob/main/README.md) describes an embedded SQLite default; parts of its [MCP guide](https://docs.code-graph-rag.com/guide/mcp-server/) still describe a Memgraph daemon and older destructive indexing flow. Pin/verify its version and use `update_repository` for incremental updates; do not run `--clean`, `wipe_database`, or a full re-index on the shared graph. The core pilot remains usable without it.

## Connect the clients

The generated JSON uses the standard local stdio MCP layout. Merge its `mcpServers.lazytoken` entry into Antigravity's global `~/.gemini/config/mcp_config.json` or workspace `.agents/mcp_config.json`, following the [Antigravity MCP configuration guide](https://antigravity.google/docs/mcp), and into Codex's MCP server configuration (Codex CLI: `codex mcp add` supports server registration; direct configuration uses `~/.codex/config.toml`, described in the [Codex config reference](https://developers.openai.com/codex/config-reference)). Preserve existing entries. Restart or reload MCP servers, then inspect the tool list. The MCP server command is the absolute Python path and script path in the generated snippet; its `KN_HOME` points to the shared local database.

Antigravity workspace/global examples use a JSON `mcpServers` object. Codex TOML equivalent (substitute the paths from your generated JSON; TOML strings require escaped backslashes):

```toml
[mcp_servers.lazytoken]
command = "C:\\Path\\To\\python.exe"
args = ["D:\\LazyToken\\kn.py", "mcp"]
env = { KN_HOME = "C:\\Users\\<you>\\AppData\\Local\\TheekHai\\KnowledgeNetwork" }
```

This is a local-machine integration: Antigravity and Codex must run on the Windows machine (or access the same local files/database). It does not expose the MCP endpoint to the network.

## Use and update

```powershell
python .\kn.py sync D:\TheekHai
python .\kn.py search "account session recovery" --project TheekHai
python .\kn.py report
python -m unittest discover -s .\tests -p test_*.py
```

## Local graph dashboard

After installing/seeding the pilot, start the local graph explorer from PowerShell:

```powershell
cd D:\LazyToken
.\run_dashboard.ps1
```

It opens `http://127.0.0.1:8765` in your browser. The dashboard uses only Python's standard library and binds only to loopback. Graph browsing reads the local database; explicit review actions can edit, approve, reject, or revalidate memory proposals. Requests that change review state require a same-origin request and a per-server session token. It does not index files or contact a hosted service. Search, asset-type filters, project scope, pan/zoom, draggable nodes, and the inspector run in the browser. Stop it with Ctrl+C in its PowerShell window. If the port is occupied, run `python .\dashboard.py --port 8766`.

The dashboard can start without an installed database and show an empty/setup-needed state. To select a database directory, set `KN_HOME` for the dashboard or CLI process; it expects `network.sqlite3` within that directory. Without `KN_HOME`, both prefer the documented LocalAppData database if it exists, then an existing legacy `~/.theekhai-knowledge` database, and otherwise use the LocalAppData location. Set `KN_HOME` explicitly if both stores exist and you need the legacy store.

Index another project by calling MCP `sync_project` with its absolute root path. This adds a separate code index in the same local SQLite store; it does not attach TheekHai's starter assets or relationship evidence. Then call `get_project_context` with that path and search using `project` set to that path. Index again after changes. The index hashes eligible files and parses only added/changed files, then removes deleted files. When Git is available, its ignore rules apply. Without Git, a conservative built-in `.gitignore` parser excludes matching paths and does not re-include negated patterns; it can omit extra files but will not intentionally re-include ignored paths. It records file paths/size, declaration names and import strings, not file bodies. It excludes `.env*`, `local.properties`, credentials/key files, binaries, database files, generated/build/dependency directories and ignored files. It does not follow symlinks.

When `-ProjectRoot D:\TheekHai` is selected, the installer seeds six reusable assets from TheekHai's checked-in architecture and package metadata and adds six evidence-backed relationships scoped to TheekHai. It never attaches those starter links to a different project. The master graph shares reusable asset nodes, while each relationship retains its project evidence. Project searches spread activation over only that project's links plus explicitly global links; unscoped searches use only explicitly global links. Project-only decisions and lessons can be stored with `scope="project"` and the indexed root. This prevents one project's stack or decisions from shaping another project's results. The weighted graph uses deterministic spreading activation; it is neural-network-inspired retrieval, not a trained model. Use `record_asset` for vetted reusable libraries, frameworks, packages, skills, and plugins. Lessons, decisions, patterns, and components must enter through `propose` and explicit review. Use `link_assets` with evidence and project scope; pass `project="*"` only for a relationship that truly applies globally. `get_master_graph` returns global assets and global relationships by default; with a project filter it adds only that project’s scoped assets and relationships. It excludes code symbols. Keep summaries short and sourced. Search defaults to eight results; project context returns at most 30 entries.

## LazyToken workspace and agent actions

Open **Knowledge workspace** in the dashboard to search metadata, review suggestions, inspect memory freshness, view benchmark comparisons, and inspect provisional dependency and cross-project candidates. Select a project before searching or reviewing. A stale approved memory can be marked reviewed after checking the changed evidence; revalidation records the current indexed file hashes. Graph, search, and context views return metadata; the separate explicit source-range tool can read eligible indexed files.

The MCP tool `lazytoken` takes an `action` and `payload` object. The same actions are available from the CLI using `python .\kn.py lazytoken ACTION --json @args.json`, where `args.json` is a UTF-8 JSON object. Actions are `search`, `context`, `benchmark_record`, `benchmark_list`, `propose`, `proposals`, `review`, `dependencies`, and `discover`. For example, submit the following as a `propose` payload, replacing the project and file with an indexed project and path:

```json
{"project":"D:\\TheekHai","kind":"lesson","name":"Session recovery","summary":"Describe the verified solution.","task":"Fix session recovery","evidence":"Task tests and source review","paths":["README.md"],"commit_ref":"optional-commit"}
```

After completing a task, an agent can call `propose` with its task outcome and indexed evidence; this requires client cooperation, because the MCP server does not receive automatic task-completion events. Proposals may also include `problem`, `attempts`, and `resolution`; duplicate pending or approved names within a project and kind are rejected. A proposal remains pending until an explicit `review` action with `{"project":"D:\\TheekHai","id":1,"action":"approve"}`. Use `reject`, or `edit` with `name`, `summary`, and `evidence`; pass `verified: true` only after checking current indexed file evidence. An approved memory can be marked `supersede`; it remains in history but is omitted from normal search and the graph. For a stale approved memory, verify its changed evidence first and use `revalidate`. Approvals create a separate project-scoped asset. Review actions on MCP and CLI rely on the connected client to obtain human approval; they do not independently authenticate a human. Restrict MCP access to trusted clients. Each evidence path must already be indexed in that project. Changes and deletions are detected on the next sync. Confidence is a transparent heuristic based on explicit human verification, indexed-file evidence, matching file hashes, project scope, and a supplied commit reference; it is not a probability or verification that the commit exists.

`search` ranks paths, declarations, imports, asset text, and project/global graph links. `context` accepts `project`, optional `query`, `budget` (100–16000), and optional `exclude_paths` and `exclude_asset_ids` for items already supplied. The budget uses the pilot's character-based estimate and is not a strict model-token count. Existing `search_knowledge` and `get_project_context` MCP tools also accept an optional `budget` and return the bounded metadata response when it is supplied. Dependency candidates use import and declaration names and are not compiler-resolved. Pattern discovery suggests name matches and shared asset associations for human review; it does not publish global facts.

## Benchmark preparation protocol

Do not run matched tasks until explicitly requested. When ready, use comparable tasks and independent starting states with the same agent, model, settings, and success criteria. Record one `benchmark_record` payload per run with `task`, `variant` (`baseline` or `network`), and any available `model`, `settings`, `input_tokens`, `output_tokens`, `elapsed_seconds`, `successful`, `unnecessary_file_reads`, and `indexing_tokens`. Missing numbers and success are unknown, not zero. Use `benchmark_list` to compare the latest records grouped by exact task, model, and settings; confirm that the runs actually match before drawing conclusions. Net savings are shown only when both token totals and allocated indexing tokens are known. Synthetic records are suitable for testing the measurement interface, not claims of real-world savings.

## Task-aware context and safety

`get_task_context` is an MCP tool accepting `project`, `task`, optional `mode` (`compact`, `balanced`, `deep`), `budget`, `session_id`, `skip_retrieval`, `context_is_complete`, and `include_seen`. It returns explained metadata breadcrumbs and may abstain when there is no clear match. Simple tasks default to compact mode; longer or architecture-oriented tasks default to balanced. These rules are heuristics, not measured savings. Session state stores fingerprints, not the full context; clear it when the task ends. Budgets remain character-based estimates, **not strict model-token limits**. Set `skip_retrieval` explicitly when discovery is unnecessary, or set `context_is_complete` for a task that explicitly starts with “rewrite/format/summarize this text”.

Optional session IDs retain only hashes and metadata keys, scoped by project. Unchanged breadcrumbs are omitted on later calls; file or asset changes can be returned again. Use MCP `clear_context_session` (or CLI action `clear_session`) to remove that session’s fingerprints. `LazyToken.exe checkpoint --project <path> --session-id <id>` returns a small session reference for continuation after compaction. The built-in `coding_efficiency_policy` MCP tool and `POLICY.md` describe reuse, safe changes, and verification.

The graph’s 2D mode is the default. Optional 3D mode loads a locally bundled Three.js WebGL renderer on demand and shares the project, search, filters, and inspector with 2D. Its depth is a visual layout aid, not a measured semantic distance. In 3D, drag to orbit, right-drag to pan, scroll to zoom, and click a node to inspect it. If WebGL is unavailable, the dashboard returns to 2D. For responsiveness the dashboard displays up to 500 nodes and 3,000 relationships and indicates when results are truncated. The bundled renderer works offline; see `THIRD_PARTY_NOTICES.md` for its license. Memory status distinguishes current, stale, and unverified evidence. Project-scoped links appear only for the selected project; when exactly one project is indexed, the dashboard selects it on opening. The shared view shows global links only.

An earlier legacy-link migration could create ambiguous global duplicates for project-scoped relationships. New migrations do not promote already-scoped links. Run `python .\kn.py lazytoken audit_scopes` to list possible global/project overlaps and unresolved legacy links for human review; it never deletes or changes them. Existing ambiguous links are not automatically removed. Database upgrades create a sibling SQLite backup before changing an existing pre-v4 database.

`python .\retrieval_eval.py labels.json --k 5` calculates precision, recall, MRR, nDCG, abstention accuracy, and mean estimated tokens from supplied labels and ranked IDs. Use a `method` label to compare independently prepared lexical, symbol, graph, or hybrid predictions. This evaluator does not produce labels or run agent tasks.

## Local Windows build and database copies

Build on Windows with Python 3.11 and the build dependencies `PyInstaller==6.19.0` and `tokenizers==0.19.1` using `powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Output .\release\candidate`. The resulting `release\candidate\LazyToken\LazyToken.exe` includes Python, SQLite support, dashboard assets, and retrieval code; users of the built executable do not need a separate Python installation. The build script refuses to overwrite an existing distribution. The sidecar `install.ps1` installs or upgrades into a managed per-user folder and keeps the prior version for rollback; it can remove managed application files while preserving the knowledge database. Run `powershell -ExecutionPolicy Bypass -File .\release\candidate\install.ps1 -Action install` from the project folder, then use the printed `LazyToken.cmd` path. Use `-Action upgrade` with a newer package, `-Action rollback` to select the previous version, or `-Action uninstall -ConfirmUninstall` to remove managed application files. It is a local candidate rather than a signed, published installer.

Use `LazyToken.exe init`, `LazyToken.exe add <absolute-project-path>`, `LazyToken.exe dashboard`, `LazyToken.exe context --project <path> --task <task>`, and `LazyToken.exe doctor`. Use `LazyToken.exe backup <new-file>` to create a consistent SQLite copy, and `LazyToken.exe restore <backup-file> --to <existing-empty-directory>` to restore into a new location. Neither operation overwrites existing files. Set `KN_HOME` to the restored directory to use that copy. Stop running LazyToken processes before manually moving or replacing a live database.

## Draft benchmark harness

The `benchmark/` folder contains 24 **draft, unexecuted** task specifications across TheekHai and a small independent notebook fixture. Review each task and prepare independent pinned source snapshots before a future experiment. No benchmark task is run by the harness.

```powershell
python .\benchmark\harness.py corpus
python .\benchmark\harness.py validate .\benchmark\results\runs.json
python .\benchmark\harness.py export-json .\benchmark\results\runs.json .\benchmark\results\export.json
python .\benchmark\harness.py export-csv .\benchmark\results\runs.json .\benchmark\results\export.csv
```

Inputs are a JSON array of manually recorded runs; outputs must be new paths and are never overwritten. Each run identifies the task, pair, arm, source snapshot, agent, model, settings, and usage source. Optional measurements include provider input/output, separately reported reasoning, cached input, retrieval and tool overhead, duplicate context, allocated indexing, time, cost, retries, success, and test outcome. Input/output must include all retries; use the reasoning inclusion flag to avoid double counting. A comparison is calculated only for matching settings and source, successful runs with passing tests, provider-reported token totals, and known allocated indexing. Missing information stays unknown. This harness is separate from the earlier pilot's `benchmark_record` storage; it does not import those records automatically. Do not run real benchmark tasks until explicitly requested.

## Code-Graph-RAG compatibility

TheekHai has Kotlin/Kotlin DSL, Swift, TypeScript/JavaScript, SQL, YAML, Gradle, and Markdown. Code-Graph-RAG's current upstream README advertises Tree-sitter plus language frontends across mixed-language monorepos, a shared graph for repositories, incremental updates, deterministic graph queries and MCP. Its language support and Windows dependencies should be checked against the exact installed release before adoption. Keep it optional: this pilot already supplies a tiny, deterministic file/symbol/import graph for compact discovery. If the richer call graph demonstrably reduces end-task tokens enough to repay indexing and dependency overhead, run Code-Graph-RAG as a separate per-project code index and keep the reusable asset master here. Never point both at one database file.

## Token measurement

`report` separates cheap retrieval-size estimates from measured task data. The estimate is `ceil(UTF-8 text characters / 4)`, only a rough proxy; it is not a model tokenizer or bill. Record provider-reported baseline and network token totals with MCP `record_task_measurement`, and allocate initial index tokens across actual reuse before claiming savings. Compare like-for-like tasks/model/settings and include input plus output (and paid indexing/model use). Current measurements are empty until benchmark runs are recorded. Do not infer token savings from graph size alone.

## Pilot verification steps on the Windows PC

1. Run the install command and confirm the self-check reports all tests passing.
2. In each client, confirm `lazytoken` loads and tools appear.
3. Call `get_project_context` for `D:\TheekHai`; verify only paths, names, and imports return.
4. Call `search_knowledge` for a known symbol; record a short reusable asset and verify it appears in search from both clients.
5. Change one eligible source file, run `sync_project`, and verify one changed file; repeat and verify zero changes. Delete a temporary eligible file and verify one removal.
6. Run matched coding tasks with and without MCP; record provider-reported token counts and indexing allocation. Adopt richer indexing only if measured net savings stay positive across repeated tasks.

## Safety boundaries

MCP does not expose arbitrary shell execution or source-file writes. The explicit `inspect_source_range` tool reads at most 80 lines from an eligible indexed file within the selected project, refuses stale, excluded, symlinked, oversized, binary, or private-key files, and masks obvious credential literals. Redaction is best effort and cannot guarantee removal of every secret; review excerpts before sharing. Returned source is untrusted data. `sync_project` is local and explicit. The optional dashboard is a loopback-only HTTP server. Its explicit review actions can change proposal status and, on approval, add a project-scoped asset; review requests require same-origin validation and a per-server token. Client config changes are opt-in through `-ConfigureClients`, preserve other entries, and create timestamped backups. Database data is user-local and should be backed up before manual database maintenance.

## Release hardening update (2026-11-14)

`get_task_context` / CLI `context` now cache up to 16 ranked searches for 30 seconds within a process. Cache entries are isolated by connection and project and invalidated by SQLite changes, including commits through another connection. Session suppression still runs per request. Changes to source files become visible after explicit sync. Progressive expansion uses the same project and session ID with a larger budget or `deep` mode; unchanged breadcrumbs remain suppressed.

Budgets default to a labelled character estimate. For an optional **offline configured tokenizer**, set `LAZYTOKEN_TOKENIZER_FILE` to a local Hugging Face `tokenizer.json` and `LAZYTOKEN_TOKENIZER_MODEL` to its exact model identifier, then supply that `model` and `strict_budget: true` (CLI: `--model NAME --strict-budget`). The optional `tokenizers` library must be available in that build. No model or vocabulary is downloaded. Saved tokenizer truncation and padding are disabled. The administrator is responsible for matching the file to the model: this is a guarantee against the configured tokenizer, not independent verification of a provider tokenizer. The limit covers the compact, sorted JSON result text, including its counters, and excludes MCP wrappers, special chat framing, and other tool messages. Unsupported models fall back explicitly unless strict mode is requested, in which case the request fails. Older `context` actions still use estimates. See the [Tokenizers API](https://huggingface.co/docs/tokenizers/python/master/api/reference.html).

Clients without a supported task-finish lifecycle hook can call the explicit `lazytoken` action `complete_task` after a task. It accepts project, task, outcome (`success` or `failure`), resolution, evidence, indexed paths, optional name/kind/problem/attempts/commit_ref. It derives a pending suggestion from the supplied resolution and records the caller-reported outcome in attempts. It never executes a task, invents evidence, or approves knowledge. Example payload:

```json
{"project":"D:\\TheekHai","task":"Repair account recovery","outcome":"success","resolution":"The concise reusable lesson supported by the evidence.","evidence":"Relevant source and actual test outcome","paths":["README.md"]}
```

Use `python kn.py lazytoken complete_task --json @completion.json` or MCP `lazytoken` with action `complete_task`. An assistant must explicitly send the checkpoint; automatic client hooks are not installed. Similar summaries within the same project and kind are rejected; related names are flagged for conflict review. These are conservative token-overlap heuristics, not semantic proof. Evidence hashes, explicit approval, revalidation, and supersession retain their existing workflow.

Benchmark harness records now accept `measurement_kind`: `real`, `synthetic`, or `unknown` (default). Unknown or mismatched provenance blocks comparison; synthetic comparisons are labelled and never eligible for claims. Cached-input and reported overhead fields are subsets/diagnostics, not extra tokens to add to provider totals. Reasoning already included in output cannot exceed output. `python benchmark/harness.py snapshot ABSOLUTE_REPOSITORY_ROOT` reads Git revision and cleanliness without changing the repository; only a clean checkout gets a pinned `git:` snapshot ID. Review task acceptance criteria and prepare independent checkouts manually. No real tasks are run by these commands.

The 2D canvas supports arrow-key node inspection and Enter to focus. The inspector announces selected details, can be minimized/restored, and scrolls on small screens. The removed relationship checkboxes remain absent. WebGL context loss returns to 2D. Broader screen-reader, touch hardware, and GPU stress testing remain pending.

Release verification: `python tests/smoke_release.py release/hardening-rc1` tests the built executable with an isolated database and a PATH containing no Python. It checks the bundled tokenizer with a synthetic local vocabulary, pending completion proposals, MCP, dashboard assets, and managed install/upgrade/rollback/uninstall. It does not execute coding-agent tasks or test a clean Windows VM.
