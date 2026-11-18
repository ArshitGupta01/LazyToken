# Working on TokSmart

The optional Windows executable bundles Python and needs no separately installed Node. The npm launcher and source checkout require a separately installed Python interpreter; npm also requires Node. The following tools are for contributors working on the source checkout.

## Source map

| File | Responsibility |
|---|---|
| `kn.py` | CLI commands, SQLite connection, indexing and legacy-compatible tool dispatch |
| `mcp_schema.py` | Full and compact MCP tool catalogs; no storage access |
| `source_index.py`, `frameworks.py` | Import extraction and derived project/framework relationships |
| `broker.py`, `token_budget.py` | Bounded context, session deduplication and optional offline tokenizer |
| `features.py`, `learning.py` | Search, proposed memories, explicit review, freshness and measurement records |
| `watcher.py` | One background synchronization worker per selected store |
| `dashboard.py` | Loopback-only HTTP server and guarded review endpoint |
| `app.js`, `features-ui.js`, `graph3d.js` | Graph explorer, knowledge workspace and optional 3D renderer |
| `onboarding.py`, `diagnostics.py` | Client setup, configuration backups and doctor checks |
| `data_ops.py`, `migration.py` | Verified SQLite copies and explicit legacy migration |
| `install.ps1`, `manage_install.ps1`, `dispatch.ps1` | Verified download, managed application versions and stable CLI launcher |
| `benchmark/performance_fixture.py`, `benchmark/real_repo_assessment.py`, `retrieval_eval.py` | Offline generated-corpus timing, pinned real-repository retrieval cases and metric calculation |

`kn.TOOLS` and `kn.mcp_tools` remain available for existing callers. Tool schemas belong in `mcp_schema.py`; do not add incremental schema mutations to the CLI. Project scopes and the explicit memory-approval boundary must stay intact.

## Consistent formatting

```powershell
python -m pip install -r requirements-dev.txt
python -m black .
npx --yes prettier@3.4.2 --write app.js features-ui.js graph3d.js index.html styles.css tests/first_run.test.cjs tests/mobile.test.cjs tests/workspace.test.cjs
```

Black and Prettier are development tools, not runtime dependencies. Configuration lives in `pyproject.toml` and `.prettierrc.json`. Vendor libraries and generated builds are excluded. CI checks formatting; avoid unrelated edits to bundled third-party code.

## Verification

```powershell
$env:LAZYTOKEN_DISABLE_AUTOWATCH = '1'
python -m unittest discover -s tests -p test_*.py
node --test tests/first_run.test.cjs tests/mobile.test.cjs tests/workspace.test.cjs
```

The Python suite includes the Node workspace tests when Node is available, and otherwise skips that development-only check. Tests use temporary stores and synthetic measurements. The workspace checks exercise out-of-order view/search responses and review project selection without adding a browser framework. They do not replace real browser/device checks.

Use `build_release.ps1` and `tests/smoke_release.py` as described in `RELEASING.md` to check the bundled executable. The smoke test removes Python and Node from its child PATH and exercises an isolated installation lifecycle, including watcher recovery after a rejected update and watcher resumption after update/rollback. It checks that the real user PATH remains unchanged.

Do not run real coding-agent benchmarks or publish a release without separate authorization. No measured token-savings claim follows from formatting, passing tests or graph size.
