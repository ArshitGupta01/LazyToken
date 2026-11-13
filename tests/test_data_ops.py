import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import data_ops

class DataCopyTests(unittest.TestCase):
    def test_copy_includes_committed_wal_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.sqlite3'; target=root/'backup.sqlite3'
            db=sqlite3.connect(source);db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE records(value TEXT)');db.execute("INSERT INTO records VALUES('kept')");db.commit()
            result=data_ops.copy_database(source,target);self.assertTrue(result['saved'])
            copy=sqlite3.connect(target);self.assertEqual(copy.execute('SELECT value FROM records').fetchone()[0],'kept');copy.close()
            before=target.read_bytes();self.assertIn('error',data_ops.copy_database(source,target));self.assertEqual(target.read_bytes(),before)
            self.assertIn('error',data_ops.copy_database(source,source));db.close()
    def test_invalid_source_does_not_create_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'invalid';target=root/'copy.sqlite3';source.write_text('not sqlite')
            self.assertIn('error',data_ops.copy_database(source,target));self.assertFalse(target.exists())

if __name__=='__main__': unittest.main()
