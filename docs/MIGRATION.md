# Data, backup and legacy migration

Fresh Windows storage defaults to `%LOCALAPPDATA%\LazyToken\network.sqlite3`. `KN_HOME` selects an explicit alternative directory. No repository or prototype seed data is imported automatically. The deprecated `seed` command is retained as a no-op.

## Existing users

Legacy locations are detected for compatibility:

- `%LOCALAPPDATA%\TheekHai\KnowledgeNetwork`
- `~/.theekhai-knowledge`

These names are historical storage identifiers, not product branding or required repositories. They are never silently selected, merged, overwritten or deleted. Existing client configurations specifying `KN_HOME` continue using that store. `lazytoken doctor` and `lazytoken migrate-data` show detected locations.

## Explicit migration

Stop processes using the source and destination stores before migrating. Preview the actual paths first:

```powershell
lazytoken migrate-data --source "C:\path\to\legacy\network.sqlite3"
```

To approve that copy:

```powershell
lazytoken migrate-data --source "C:\path\to\legacy\network.sqlite3" --apply
```

Migration targets the new default directory. It creates an integrity-checked independent backup, copies that consistent snapshot to a new destination and records a rollback receipt. It never merges data, never overwrites an existing destination and leaves the legacy database untouched. A collision must be resolved by the operator without replacing a live store. If a copy step fails, retain the reported backup and inspect the result before retrying.

Migration does not rewrite existing assistant registrations or environment variables. A client with an explicit legacy `KN_HOME` continues using it until you deliberately change that registration. `setup` preserves existing LazyToken entries; inspect and back up client settings before updating them to the new directory.

To undo an unused migration copy:

```powershell
lazytoken migrate-data --rollback "C:\path\to\migration-receipt.json"
```

Rollback refuses a changed destination or one with active WAL/SHM sidecars. It retains the original source and verified backup.

## Backup, restore and uninstall

`lazytoken backup NEW_FILE` creates a verified independent SQLite copy, including committed WAL data, and refuses an existing target. `lazytoken restore BACKUP --to DIRECTORY` restores into a new database file without overwriting it.

Application rollback changes binaries, not schema. If an older binary refuses a newer schema, restore a verified pre-upgrade backup to a new location; never replace a live database.

`lazytoken uninstall --yes` retains knowledge data. Database removal is a separate explicit operator command, `data-delete --confirm-directory ABSOLUTE_DEFAULT_DIRECTORY`; it removes only the inactive identified default database and refuses legacy or overridden stores. Other user files and backups are preserved.
