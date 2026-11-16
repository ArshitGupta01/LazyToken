# CLI reference

Commands below use the installed `toksmart` launcher. For source development, use `python app_entry.py COMMAND`; update, rollback and uninstall require a managed installation. Use `--help` after a command to inspect its arguments.

## Projects, context and dashboard

| Command                                                                  | Behavior                                                                                                                 |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `init [--project ABSOLUTE_PATH]`                                         | Initialize storage and discover clients read-only. Index only an explicitly supplied project. Safe to rerun.             |
| `add ABSOLUTE_PATH`                                                      | Index one explicitly selected existing repository.                                                                       |
| `sync [PATH]`                                                            | Sync one repository, or all previously selected repositories. Missing repositories preserve their indexes.               |
| `projects`                                                               | List indexed repositories, file and symbol counts, index errors, and folder availability without modifying data.         |
| `watch [start\|stop\|status\|run]`                                       | Control automatic synchronization. Defaults to status.                                                                   |
| `watch run [--interval SECONDS] [--debounce SECONDS]`                    | Run the worker in the terminal; defaults are 2 seconds and 1 second.                                                     |
| `search QUERY --project PATH`                                            | Search indexed metadata.                                                                                                 |
| `context --project PATH --task TEXT [--budget N] [--session-id ID]`      | Retrieve ranked task context with bounded payload and optional session deduplication.                                    |
| `context ... --expand-assets`                                            | Include full memory summaries and provenance within the budget; current verified summaries already appear when they fit. |
| `context ... --model NAME --strict-budget`                               | Require a matching configured offline tokenizer; refuse estimation fallback.                                             |
| `checkpoint --project PATH --session-id ID`                              | Return a compact reference to the context already supplied.                                                              |
| `checkpoint --project PATH --session-id ID --acknowledge-source`         | Accept the current indexed source as the session baseline after syncing and reviewing changes.                           |
| `mcp [--compact-tools]`                                                  | Run the local stdio MCP server; compact mode advertises fewer tools.                                                     |
| `context --project PATH --task TEXT --prompt`                            | Output the task and useful bounded metadata as a prompt; does not run an agent.                                          |
| `setup --project PATH [--client codex] [--client antigravity] [--apply]` | Preview or apply indexing and optional client registration.                                                              |
| `setup --test-connection`                                                | Verify local MCP initialization and tool discovery.                                                                      |
| `setup --rollback RECEIPT`                                               | Restore unchanged managed configuration from its verified backup. Refuse newer edits.                                    |
| `doctor [--format json\|text\|table]`                                    | Check runtime, package integrity, storage, SQLite, clients, watcher and dashboard port. JSON is the default.             |
| `dashboard [--port N] [--no-browser]`                                    | Run the loopback-only 2D/3D graph; 3D loads on demand.                                                                   |
| `serve [--port N] [--no-browser]`                                        | Start the local server and connect the browser interface.                                                                |

The offline tokenizer is configured with `LAZYTOKEN_TOKENIZER_MODEL` and `LAZYTOKEN_TOKENIZER_FILE`. The operator must select a tokenizer matching the requested model. No tokenizer is downloaded automatically. Budgets cover the compact JSON payload, excluding transport/provider framing.

Checkpoint test outcomes are caller-reported, not independently verified. `clear_session` clears fingerprints by default; pass `include_state: true` to also delete the project's stored checkpoint state. Opening an older database creates a pre-migration backup; rolling back the application does not reverse the database schema.

See [client integration evidence](CLIENT_COMPATIBILITY.md) for tested client versions and the limits of the local setup check. Setup preview reports whether an existing registration exactly matches the suggested entry; it preserves existing configuration either way.

## Installation and storage

| Command                                                      | Behavior                                                                                                                          |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `update [--version vX.Y.Z]`                                  | Download and verify an official release, retaining the prior version. Requires a published release.                               |
| `update --package ZIP --sha256 HASH`                         | Upgrade from an independently verified local archive.                                                                             |
| `rollback`                                                   | Select the prior app version; does not rewind database schema.                                                                    |
| `uninstall --yes [--remove-clients]`                         | Remove managed application files and the owned PATH entry, retaining data. Optional client cleanup refuses unrelated/newer edits. |
| `backup NEW_FILE`                                            | Create a verified independent SQLite copy, including committed WAL data. Never overwrite.                                         |
| `restore BACKUP --to DIRECTORY`                              | Restore to a new database file; never overwrite a destination.                                                                    |
| `migrate-data [--source OLD_DATABASE] [--apply]`             | Detect/preview or explicitly copy legacy storage; never merge or overwrite.                                                       |
| `migrate-data --rollback RECEIPT`                            | Remove an unchanged inactive migration copy, retaining source and backup.                                                         |
| `data-delete --confirm-directory ABSOLUTE_DEFAULT_DIRECTORY` | Explicitly delete only the inactive default database. Refuse legacy/override stores and WAL sidecars.                             |

Maintenance stops the background worker before touching executable versions. An existing watcher resumes after update/rollback or a rejected update, unless automatic startup is disabled. Uninstall preserves knowledge data by default. See [migration](MIGRATION.md) before moving or deleting storage.

## Structured actions and measurement

```powershell
toksmart toksmart proposals --json "@args.json"
```

The first `toksmart` is the executable; the second is the structured-action subcommand (aliases `toksmart`, `repomind`, and `lazytoken` are supported). `args.json` contains the action arguments, such as `{"project":"C:\\Projects\\MyApp"}`. Quote the `@` argument in PowerShell. Inline JSON is also supported.

Actions include `search`, `context`, `task_context`, `complete_task`, `propose`, `proposals`, `review`, `dependencies`, `discover`, `checkpoint`, `clear_session`, `inspect_source`, `benchmark_record`, `benchmark_runs`, `benchmark_list`, `policy` and `audit_scopes`. The CLI and local dashboard allow explicit operator review; MCP blocks review decisions.

`complete_task` requires project, task, outcome (`success` or `failure`), resolution, evidence and indexed evidence paths. It creates a pending suggestion, never a trusted memory automatically. `review` requires project, proposal ID and an explicit action: edit, approve, reject, revalidate or supersede.

| Command                                    | Behavior                                                            |
| ------------------------------------------ | ------------------------------------------------------------------- |
| `benchmark corpus`                         | Show the repeatable task protocol.                                  |
| `benchmark validate RUNS.json`             | Validate manually captured records.                                 |
| `benchmark export-json RUNS.json NEW_FILE` | Export validated records and comparisons without overwriting files. |
| `benchmark export-csv RUNS.json NEW_FILE`  | Export validated records with spreadsheet formula protection.       |
| `benchmark snapshot ROOT`                  | Inspect a clean Git revision without checking out or running tasks. |
| `evaluate LABELS.json --k N`               | Calculate retrieval metrics from supplied labels/predictions.       |

Measurements must distinguish synthetic, unknown and real provenance. Missing values are unknown, not zero. No command above runs coding agents. Real matched tasks require separate authorization; graph size and passing tests do not establish token savings.
