import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kn


class LazyTokenFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        (self.root / 'AccountService.kt').write_text('import demo.AuthClient\nclass AccountService {}\n', encoding='utf-8')
        (self.root / 'AuthClient.kt').write_text('class AuthClient {}\n', encoding='utf-8')
        self.db = kn.connect(Path(self.temp.name) / 'test.sqlite3')
        kn.sync(self.root, self.db)
        self.project = str(self.root.resolve())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_action(self, operation, **args):
        return kn.feature_call(operation, args, self.db)

    def test_migration_is_idempotent_and_preserves_assets(self):
        kn.add_asset({'kind':'lesson','name':'old','summary':'existing'},self.db)
        self.db.close()
        self.db = kn.connect(Path(self.temp.name) / 'test.sqlite3')
        self.assertEqual(self.db.execute('SELECT count(*) FROM lazytoken_migrations').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets WHERE name='old'").fetchone()[0],1)

    def test_default_location_uses_existing_legacy_store_when_needed(self):
        local=Path(self.temp.name)/'local'; home=Path(self.temp.name)/'home'; legacy=home/'.theekhai-knowledge'; legacy.mkdir(parents=True)
        (legacy/'network.sqlite3').touch()
        with patch.dict(os.environ,{'LOCALAPPDATA':str(local)},clear=True), patch.object(Path,'home',return_value=home):
            self.assertEqual(kn.data_root(),legacy)
            preferred=local/'TheekHai'/'KnowledgeNetwork';preferred.mkdir(parents=True);(preferred/'network.sqlite3').touch()
            self.assertEqual(kn.data_root(),preferred)

    def test_proposal_review_freshness_and_isolation(self):
        proposal=self.run_action('propose',project=self.project,kind='lesson',name='Session fix',summary='Use the session service',task='Fix login',evidence='Verified by tests',paths=['AccountService.kt'])
        self.assertEqual(proposal['status'],'pending')
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets WHERE name='Session fix'").fetchone()[0],0)
        other=Path(self.temp.name)/'other';other.mkdir();kn.sync(other,self.db)
        self.assertIn('error',self.run_action('review',project=str(other),id=proposal['id'],action='approve'))
        result=self.run_action('review',project=self.project,id=proposal['id'],action='approve')
        self.assertEqual(result['status'],'approved')
        self.assertEqual(self.run_action('proposals',project=self.project)['proposals'][0]['freshness'],'current')
        (self.root/'AccountService.kt').write_text('class ChangedAccount {}\n',encoding='utf-8');kn.sync(self.root,self.db)
        self.assertEqual(self.run_action('proposals',project=self.project)['proposals'][0]['freshness'],'stale')
        found=self.run_action('search',project=self.project,query='Session fix')['results']
        self.assertEqual(next(r for r in found if r.get('name')=='Session fix')['freshness'],'stale')
        self.assertNotIn('Session fix',str(self.run_action('search',project=str(other),query='Session fix')['results']))
        self.assertEqual(self.run_action('review',project=self.project,id=proposal['id'],action='revalidate')['freshness'],'current')
        (self.root/'AccountService.kt').unlink();kn.sync(self.root,self.db)
        self.assertEqual(self.run_action('proposals',project=self.project)['proposals'][0]['freshness'],'stale')
        self.assertIn('error',self.run_action('review',project=self.project,id=proposal['id'],action='revalidate'))

    def test_rejected_and_stale_proposals_do_not_create_assets(self):
        p=self.run_action('propose',project=self.project,kind='decision',name='Decision',summary='Summary',task='Task',evidence='Evidence',paths=['AuthClient.kt'])
        (self.root/'AuthClient.kt').write_text('class NewClient {}',encoding='utf-8');kn.sync(self.root,self.db)
        self.assertIn('error',self.run_action('review',project=self.project,id=p['id'],action='approve'))
        self.assertEqual(self.run_action('review',project=self.project,id=p['id'],action='reject')['status'],'rejected')
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets WHERE name='Decision'").fetchone()[0],0)

    def test_metadata_search_budget_and_dependencies(self):
        results=self.run_action('search',project=self.project,query='Where is user authentication handled?')['results']
        self.assertTrue(any('Account' in str(r) or 'Auth' in str(r) for r in results))
        context=self.run_action('context',project=self.project,query='authentication',budget=100,exclude_paths=['AuthClient.kt'])
        self.assertLessEqual(context['estimated_tokens'],100)
        self.assertNotIn('AuthClient.kt',str(context))
        deps=self.run_action('dependencies',project=self.project)['dependencies']
        self.assertEqual(deps[0]['status'],'provisional')
        self.assertEqual(deps[0]['candidates'][0]['name'],'AuthClient')

    def test_benchmark_missing_values_and_pairing(self):
        self.run_action('benchmark_record',task='Synthetic task',variant='baseline',model='model',settings={'temperature':0},input_tokens=40,output_tokens=10)
        self.run_action('benchmark_record',task='Synthetic task',variant='network',model='model',settings={'temperature':0},input_tokens=20,output_tokens=5)
        group=self.run_action('benchmark_list')['comparisons'][0]
        self.assertIsNone(group['net_tokens_saved'])
        self.run_action('benchmark_record',task='Synthetic task',variant='network',model='model',settings={'temperature':0},input_tokens=20,output_tokens=5,indexing_tokens=2)
        self.assertEqual(self.run_action('benchmark_list')['comparisons'][0]['net_tokens_saved'],23)
        self.assertIsNone(group['network']['elapsed_seconds'])

    def test_cli_and_mcp_expose_bounded_context(self):
        env=os.environ.copy(); env['KN_HOME']=self.temp.name
        result=subprocess.run([sys.executable,str(Path(kn.__file__)), 'lazytoken','benchmark_list'],env=env,text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['runs'],[])
        value=kn.call('search_knowledge',{'project':self.project,'query':'auth','budget':120},self.db)
        self.assertLessEqual(value['estimated_tokens'],120)
        self.assertIn('not a model tokenizer',value['budget_type'])

if __name__ == '__main__': unittest.main()


