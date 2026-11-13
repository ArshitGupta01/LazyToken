"""SQLite backup and restore-to-new-location helpers."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote


def copy_database(source: Path, target: Path) -> dict:
    source=Path(source).resolve();target=Path(target).absolute()
    if not source.is_file(): return {'error':'Source database does not exist.'}
    if source==target.resolve(): return {'error':'Source and destination must differ.'}
    if not target.parent.is_dir(): return {'error':'Destination directory does not exist.'}
    try:
        source_db=sqlite3.connect('file:'+quote(source.as_posix(),safe='/:')+'?mode=ro',uri=True)
        try:
            if source_db.execute('PRAGMA quick_check').fetchone()[0]!='ok': return {'error':'Source database failed integrity check.'}
            # Reserve a new path; never overwrite an existing file.
            fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            try:
                dest=sqlite3.connect(target)
                try:
                    source_db.backup(dest)
                    if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise sqlite3.DatabaseError('Backup integrity check failed.')
                finally: dest.close()
            except Exception:
                target.unlink(missing_ok=True)
                raise
        finally: source_db.close()
        return {'saved':True,'path':str(target),'note':'A new independent SQLite copy was created; the source was not changed.'}
    except (OSError,sqlite3.Error) as exc:
        return {'error':f'Unable to create database copy: {type(exc).__name__}'}
