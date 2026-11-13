import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import kn

class ContextBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)/'project';self.root.mkdir()
        (self.root/'AuthService.py').write_text('class AuthService:\n    pass\n',encoding='utf-8')
        self.db=kn.connect(Path(self.temp.name)/'store.sqlite3');kn.sync(self.root,self.db);self.project=str(self.root.resolve())
    def tearDown(self): self.db.close();self.temp.cleanup()
    def call(self,**args): return kn.call('get_task_context',{'project':self.project,'task':'authentication auth',**args},self.db)
    def test_budget_explanation_and_session_dedup(self):
        first=self.call(session_id='session-1',budget=500)
        self.assertEqual(first['decision'],'retrieve');self.assertTrue(first['results']);self.assertLessEqual(first['estimated_tokens'],500)
        self.assertTrue(all('why' in x for x in first['results']))
        second=self.call(session_id='session-1',budget=500)
        self.assertEqual(second['results'],[]);self.assertGreater(second['suppressed_seen'],0)
        checkpoint=kn.feature_call('checkpoint',{'project':self.project,'session_id':'session-1'},self.db)
        self.assertGreater(checkpoint['supplied_items'],0)
        self.assertNotIn('class AuthService',str(checkpoint))
        self.assertTrue(self.call(session_id='session-1',budget=500,include_seen=True)['results'])
        self.assertGreater(kn.call('clear_context_session',{'project':self.project,'session_id':'session-1'},self.db)['cleared'],0)
        self.assertTrue(self.call(session_id='session-1',budget=500)['results'])
    def test_changed_file_is_resent_and_project_sessions_are_isolated(self):
        self.call(session_id='one',budget=500)
        (self.root/'AuthService.py').write_text('class AuthService:\n    value = 1\n',encoding='utf-8');kn.sync(self.root,self.db)
        self.assertTrue(self.call(session_id='one',budget=500)['results'])
        other=Path(self.temp.name)/'other';other.mkdir();(other/'AuthService.py').write_text('class AuthService: pass',encoding='utf-8');kn.sync(other,self.db)
        result=kn.call('get_task_context',{'project':str(other.resolve()),'task':'auth','session_id':'one'},self.db)
        self.assertTrue(result['results']);self.assertTrue(all('project' not in x for x in result['results']))
    def test_skip_abstain_and_invalid_budget(self):
        self.assertEqual(self.call(skip_retrieval=True)['decision'],'skip')
        self.assertEqual(kn.call('get_task_context',{'project':self.project,'task':'zebra quantum nonexistent'},self.db)['decision'],'abstain')
        self.assertIn('error',self.call(budget=5))
    def test_directory_traversal_and_symlink_escape_are_excluded(self):
        self.assertFalse(kn.safe_relative('../secret.py'))
        outside=Path(self.temp.name)/'outside';outside.mkdir();(outside/'secret.py').write_text('secret',encoding='utf-8')
        link=self.root/'linked'
        try: link.symlink_to(outside,target_is_directory=True)
        except OSError: self.skipTest('Creating directory symlinks requires privileges on this platform')
        self.assertFalse(kn.safe_file(self.root,'linked/secret.py'))

    def test_fallback_indexing_respects_gitignore_without_git(self):
        (self.root/'.gitignore').write_text('private/\n*.secret.py\n!safe.secret.py\n',encoding='utf-8')
        (self.root/'private').mkdir();(self.root/'private'/'notes.py').write_text('class Private: pass')
        (self.root/'safe.secret.py').write_text('class ShouldStayExcluded: pass')
        nested=self.root/'nested';nested.mkdir();(nested/'.gitignore').write_text('ignored.py\n');(nested/'ignored.py').write_text('class Ignored: pass');(nested/'allowed.py').write_text('class Allowed: pass')
        with patch('kn.subprocess.run',side_effect=FileNotFoundError): files=kn.list_files(self.root)
        self.assertIn('nested/allowed.py',files)
        self.assertNotIn('private/notes.py',files)
        self.assertNotIn('safe.secret.py',files)
        self.assertNotIn('nested/ignored.py',files)
        self.assertFalse(kn.safe_relative('config/service-account.json'))
        self.assertFalse(kn.safe_relative('.env.local/data.py'))

if __name__=='__main__': unittest.main()
