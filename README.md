<div align="center">
  <img src="logo.svg" width="48" height="48" alt="TokSmart logo" />

# TokSmart

Local code graph, search, and reviewed memory for AI coding work.

[![npm version](https://img.shields.io/npm/v/toksmart)](https://www.npmjs.com/package/toksmart)
[![Verify TokSmart](https://github.com/ArshitGupta01/TokSmart/actions/workflows/checks.yml/badge.svg)](https://github.com/ArshitGupta01/TokSmart/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[Website](https://toksmart.vercel.app) · [Phone prompts](https://toksmart.vercel.app/mobile.html) · [CLI reference](docs/CLI.md) · [Issues](https://github.com/ArshitGupta01/TokSmart/issues)

</div>

TokSmart indexes a repository **on your computer** and builds a SQLite graph of files, symbols, imports, and some statically detected calls. Browse the graph, search indexed names, and give an AI assistant a bounded task brief. Approved project lessons can appear in later briefs. Retrieval is deterministic lexical and graph search; TokSmart does not use embeddings or call an AI model to index your code.

The desktop app handles local repositories. The phone page supplies copyable Lite, Pro, and Coding prompts; it cannot inspect your files. Both are TokSmart experiences, with different capabilities.

## Requirements

- Node.js 18 or newer for `npx` or the npm launcher.
- Python 3.11 or newer available as `python`, `python3`, or `py -3` on Windows.
- An existing local repository. Give TokSmart its **absolute folder path**.

The npm package includes the Python source, but does not install Python. The graph server runs on loopback (`127.0.0.1`). The phone page is a separate prompt tool and does not index repositories.

The optional Windows executable bundles its runtime; see [release instructions](RELEASING.md). No verified public Windows release is available yet, so the npm/source instructions below are the current installation paths.

## Start in three steps

**1. Start the server** in a terminal:

```sh
npx toksmart@latest serve
```

Keep this terminal open. TokSmart opens the browser, or you can visit [toksmart.vercel.app](https://toksmart.vercel.app). If the hosted page cannot connect, open [http://127.0.0.1:8765](http://127.0.0.1:8765) on the **same computer**.

**2. Index your project** in a second terminal. Replace the path with your repository's absolute path:

```powershell
# Windows PowerShell
npx toksmart@latest add "C:\Projects\MyApp"
```

```sh
# macOS or Linux
npx toksmart@latest add "$HOME/projects/myapp"
```

**3. Explore the index** in your browser. Refresh the dashboard after `add`, select your repository, and open **Search** to find indexed code. The graph may be empty after indexing because code files alone do not create knowledge nodes; use `context` for a bounded task brief. When knowledge nodes are present, click one to inspect its relationships and evidence. Check what was indexed with:

```sh
npx toksmart@latest projects
```

`projects` lists indexed repositories, file and symbol counts, index errors, and whether each folder is still available. It does not change the index.

### Use the index while coding

```powershell
$project = "C:\Projects\MyApp"
npx toksmart@latest search "AccountStore" --project $project
npx toksmart@latest impact "AccountStore" --project $project
npx toksmart@latest context --project $project --task "Find and fix the account lookup bug" --budget 600
```

- `search` finds indexed **names and paths**, not arbitrary source body text.
- `impact` shows statically detected callers and dependencies. Dynamic calls and external consumers may be missing.
- `context` returns a bounded task brief. Add `--prompt` to output the task and brief together for copying into an AI chat.
- `sync` refreshes indexed projects. When a source file is deleted, the next sync removes its file, symbol, and import entries from the graph.

```sh
npx toksmart@latest sync
npx toksmart@latest doctor --format text
```

The index is local SQLite data and survives closing the terminal. See the [full CLI reference](docs/CLI.md) for watch, checkpoint, backup, migration, review, and data management commands.

## Install for regular use or MCP

For a stable command path, install globally:

```sh
npm install --global toksmart
toksmart doctor --format text
```

Then use `toksmart` in place of `npx toksmart@latest`. A temporary `npx` cache path can disappear, so use a stable installation for MCP registration.

TokSmart can preview and apply MCP registration for **Codex** and **Antigravity**:

```powershell
toksmart setup --project "C:\Projects\MyApp" --client codex
toksmart setup --project "C:\Projects\MyApp" --client codex --apply
toksmart setup --test-connection
```

The first command previews changes; `--apply` makes them. Restart your AI client after registration. Other MCP clients can launch `toksmart mcp --compact-tools` over standard input/output; see [client integration evidence](docs/CLIENT_COMPATIBILITY.md). Setup preserves unrelated client settings.

## Memory and graph behavior

- Indexing extracts metadata and static code relationships from supported files. It does not execute project code.
- Task briefs can include graph relationships and approved memories. A proposed lesson must be reviewed before it becomes trusted; open **Memory** in the local dashboard to inspect, edit, approve, reject, or supersede it.
- Session IDs let context calls suppress previously supplied items. `checkpoint` summarizes stored session state after a long task or chat compaction.
- File changes are picked up by `sync` or the local watcher. If a project folder is missing, its previous index is preserved instead of silently erased.

Run `toksmart capabilities` for supported languages and their limits. Notebook (`.ipynb`) code cells are not currently parsed as source files. Static import and call edges are evidence, not proof of runtime behavior.

## Website and phone page

The [website](https://toksmart.vercel.app) hosts the interface. On a desktop, your browser connects directly to the loopback server on that device; Vercel does not run your index or receive your repository through that connection. Visiting the hosted page still makes normal website requests to Vercel. The local dashboard is also available at `http://127.0.0.1:8765`.

The [phone page](https://toksmart.vercel.app/mobile.html) offers Lite, Pro, and Coding prompts to copy into an AI assistant. It works without the desktop server, an account, or an API key. Its benchmark viewer imports a JSON report into browser storage. It does not grant the AI access to your repository, run the graph on a phone, or guarantee token savings. See [mobile usage and benchmarks](docs/MOBILE_PROMPTS.md).

## Evidence and limits

The current retrieval tests use small authored fixtures. A separate [agent pilot](docs/BENCHMARK_PILOT.md) recorded provider token usage on a few isolated tasks, but some runs never called TokSmart's MCP tools and one cold-start comparison used more tokens than its baseline. These results cannot establish general savings. The [retrieval assessment](docs/RETRIEVAL_ASSESSMENT.md) explains its labels and metrics. Run `python benchmark/graph_ablation.py` to generate a local synthetic ablation report; its payload estimates are not provider token counts or task outcomes.

### Reproduce a local performance probe

Run `python benchmark/performance_fixture.py --files 200 --repeats 5`, then `python benchmark/performance_fixture.py --validate benchmark/results/performance_report.json`. The report is generated under ignored `benchmark/results/` and records the generated corpus hash and byte count, indexed file/symbol/import counts, platform/Python version, cold and unchanged warm indexing time, Python allocation peaks, and first/warm bounded-context latency. The fixture is deterministic and uses a temporary local SQLite database; it makes no network or model calls and does not touch your indexed repositories. Measurements vary by machine and include tracing overhead. Python allocation peaks omit SQLite/native memory; latency and result counts do not establish retrieval quality or token savings.

Earlier names such as LazyToken and RepoMind still occur in compatibility aliases, database paths, and historical benchmark records. New users should use `toksmart`; the [migration guide](docs/MIGRATION.md) explains existing data and configuration.

## Troubleshooting

| Symptom                       | What to do                                                                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Python is missing or too old  | Install Python 3.11+, reopen the terminal, and run `toksmart doctor`.                                                                 |
| Browser cannot connect        | Keep `serve` running and open `http://127.0.0.1:8765` on that computer. A phone's `127.0.0.1` is the phone, not your PC.              |
| Old interface after an update | Stop the old server and start `npx toksmart@latest serve` again. Check `/api/health` on the local server for its version.             |
| Port 8765 is occupied         | Check what is listening there. `serve --port 18775` runs a separate local dashboard, but the hosted page connects to 8765.            |
| File or symbol is missing     | Run `toksmart sync`, then `toksmart projects` for index errors. Ignored, sensitive, oversized, and unsupported files may be excluded. |

Before moving or deleting local data, read the [backup and data management commands](docs/CLI.md#installation-and-storage). Uninstall retains the knowledge database by default.

## Develop and verify

```sh
git clone https://github.com/ArshitGupta01/TokSmart.git
cd TokSmart
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"
python e2e/runner.py --all
node --test tests/mobile.test.cjs tests/workspace.test.cjs
```

You can run the source CLI as `python kn.py COMMAND` without installing npm. CI runs unit and end-to-end suites on Linux and Windows. Benchmark reports and limitations are in [docs](docs/); passing tests or a large graph do not prove token savings for a particular user.

Contributor setup and architecture are in [development notes](docs/DEVELOPMENT.md). The [CLI reference](docs/CLI.md) covers commands, [mobile guide](docs/MOBILE_PROMPTS.md) covers prompts and their measurement protocol, and the [two-day plan](docs/TOKSMART_10_OF_10_EXECUTION_PLAN.md) tracks remaining work.

## License

MIT. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
