# LazyToken Knowledge Network pilot

This is a local, standard-library-only Python pilot for a reusable asset graph and an incremental per-project source graph. The SQLite database lives under `%LOCALAPPDATA%\TheekHai\KnowledgeNetwork`; source code and secrets are never sent to a hosted service. The stdio MCP server exposes compact local tools to Antigravity and Codex. Search/indexing are deterministic and make no model call.

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

## Local 2D graph dashboard

After installing/seeding the pilot, start the local graph explorer from PowerShell:

```powershell
cd D:\LazyToken
.\run_dashboard.ps1
```

It opens `http://127.0.0.1:8765` in your browser. The dashboard uses only Python's standard library and binds only to loopback. Graph browsing reads the local database; explicit review actions can edit, approve, reject, or revalidate memory proposals. Requests that change review state require a same-origin request and a per-server session token. It does not index files or contact a hosted service. Search, asset-type filters, project scope, pan/zoom, draggable nodes, and the inspector run in the browser. Stop it with Ctrl+C in its PowerShell window. If the port is occupied, run `python .\dashboard.py --port 8766`.

The dashboard can start without an installed database and show an empty/setup-needed state. To select a database directory, set `KN_HOME` for the dashboard or CLI process; it expects `network.sqlite3` within that directory. Without `KN_HOME`, both prefer the documented LocalAppData database if it exists, then an existing legacy `~/.theekhai-knowledge` database, and otherwise use the LocalAppData location. Set `KN_HOME` explicitly if both stores exist and you need the legacy store.

Index another project by calling MCP `sync_project` with its absolute root path. This adds a separate code index in the same local SQLite store; it does not attach TheekHai's starter assets or relationship evidence. Then call `get_project_context` with that path and search using `project` set to that path. Index again after changes. The index hashes eligible files and parses only added/changed files, then removes deleted files. Git-ignore rules apply. It records file paths/size, declaration names and import strings, not file bodies. It excludes `.env*`, `local.properties`, credentials/key files, binaries, database files, generated/build/dependency directories and ignored files. It does not follow symlinks.

When `-ProjectRoot D:\TheekHai` is selected, the installer seeds six reusable assets from TheekHai's checked-in architecture and package metadata and adds six evidence-backed relationships scoped to TheekHai. It never attaches those starter links to a different project. The master graph shares reusable asset nodes, while each relationship retains its project evidence. Project searches spread activation over only that project's links plus explicitly global links; unscoped searches use only explicitly global links. Project-only decisions and lessons can be stored with `scope="project"` and the indexed root. This prevents one project's stack or decisions from shaping another project's results. The weighted graph uses deterministic spreading activation; it is neural-network-inspired retrieval, not a trained model. Use `record_asset` for vetted reusable libraries, frameworks, packages, skills, plugins, components, decisions, lessons and patterns. Use `link_assets` with evidence and project scope; pass `project="*"` only for a relationship that truly applies globally. `get_master_graph` returns shared assets and their evidence scopes, with an optional project filter; it excludes code symbols. Keep summaries short and sourced. Search defaults to eight results; project context returns at most 30 entries.

## LazyToken workspace and agent actions

Open **Knowledge workspace** in the dashboard to search metadata, review suggestions, inspect memory freshness, view benchmark comparisons, and inspect provisional dependency and cross-project candidates. Select a project before searching or reviewing. A stale approved memory can be marked reviewed after checking the changed evidence; revalidation records the current indexed file hashes. File content is never returned by these features.

The MCP tool `lazytoken` takes an `action` and `payload` object. The same actions are available from the CLI using `python .\kn.py lazytoken ACTION --json @args.json`, where `args.json` is a UTF-8 JSON object. Actions are `search`, `context`, `benchmark_record`, `benchmark_list`, `propose`, `proposals`, `review`, `dependencies`, and `discover`. For example, submit the following as a `propose` payload, replacing the project and file with an indexed project and path:

```json
{"project":"D:\\TheekHai","kind":"lesson","name":"Session recovery","summary":"Describe the verified solution.","task":"Fix session recovery","evidence":"Task tests and source review","paths":["README.md"],"commit_ref":"optional-commit"}
```

After completing a task, an agent can call `propose` with its task outcome and indexed evidence; this requires client cooperation, because the MCP server does not receive automatic task-completion events. A proposal remains pending until an explicit `review` action with `{"project":"D:\\TheekHai","id":1,"action":"approve"}`. Use `reject`, or `edit` with `name`, `summary`, and `evidence`; for a stale approved memory, verify its changed evidence first and use `revalidate`. Approvals create a separate project-scoped asset. Each evidence path must already be indexed in that project. Changes and deletions are detected on the next sync. Confidence is a transparent heuristic based on human approval, indexed-file evidence, matching file hashes, project scope, and a supplied commit reference; it is not a probability or verification that the commit exists.

`search` ranks paths, declarations, imports, asset text, and project/global graph links. `context` accepts `project`, optional `query`, `budget` (100–16000), and optional `exclude_paths` and `exclude_asset_ids` for items already supplied. The budget uses the pilot's character-based estimate and is not a strict model-token count. Existing `search_knowledge` and `get_project_context` MCP tools also accept an optional `budget` and return the bounded metadata response when it is supplied. Dependency candidates use import and declaration names and are not compiler-resolved. Pattern discovery suggests name matches and shared asset associations for human review; it does not publish global facts.

## Benchmark preparation protocol

Do not run matched tasks until explicitly requested. When ready, use comparable tasks and independent starting states with the same agent, model, settings, and success criteria. Record one `benchmark_record` payload per run with `task`, `variant` (`baseline` or `network`), and any available `model`, `settings`, `input_tokens`, `output_tokens`, `elapsed_seconds`, `successful`, `unnecessary_file_reads`, and `indexing_tokens`. Missing numbers and success are unknown, not zero. Use `benchmark_list` to compare the latest records grouped by exact task, model, and settings; confirm that the runs actually match before drawing conclusions. Net savings are shown only when both token totals and allocated indexing tokens are known. Synthetic records are suitable for testing the measurement interface, not claims of real-world savings.

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

No shell command execution, source-file writes, or file reads via MCP are included. `sync_project` is local and explicit. The optional dashboard is a loopback-only HTTP server. Its explicit review actions can change proposal status and, on approval, add a project-scoped asset; review requests require same-origin validation and a per-server token. Client config changes are opt-in through `-ConfigureClients`, preserve other entries, and create timestamped backups. Database data is user-local and should be backed up before manual database maintenance.
