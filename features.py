"""Local review, measurements and metadata retrieval for LazyToken."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS lazytoken_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS benchmark_runs(id INTEGER PRIMARY KEY, task TEXT NOT NULL, variant TEXT NOT NULL, model TEXT, settings TEXT, input_tokens INTEGER, output_tokens INTEGER, elapsed_seconds REAL, successful INTEGER, unnecessary_file_reads INTEGER, indexing_tokens INTEGER, recorded_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS memory_proposals(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL, task TEXT NOT NULL, evidence TEXT NOT NULL, commit_ref TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', asset_id INTEGER, created_at INTEGER NOT NULL, reviewed_at INTEGER);
    CREATE TABLE IF NOT EXISTS memory_evidence(proposal_id INTEGER NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(proposal_id,path));
    INSERT OR IGNORE INTO lazytoken_migrations VALUES(1, strftime('%s','now'));
    ''')
    conn.commit()


def project_id(kn, conn, value):
    value = str(value or '').strip()
    resolved = kn.resolve_project(value, conn) if value and value != '*' else ''
    return resolved if resolved and conn.execute('SELECT 1 FROM projects WHERE id=?', (resolved,)).fetchone() else ''


def benchmark(args, conn):
    task = str(args.get('task','')).strip()[:240]
    variant = args.get('variant')
    if not task or variant not in ('baseline','network'):
        return {'error':'Provide a task and variant baseline or network.'}
    values = []
    for field in ('input_tokens','output_tokens','elapsed_seconds','unnecessary_file_reads','indexing_tokens'):
        v = args.get(field)
        if v is not None:
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0 or (field != 'elapsed_seconds' and int(v) != v):
                return {'error':field + ' must be a non-negative number or null.'}
        values.append(v)
    success = args.get('successful')
    if success is not None and not isinstance(success,bool): return {'error':'successful must be a boolean or null.'}
    settings = args.get('settings')
    if settings is not None and not isinstance(settings,(str,dict)): return {'error':'settings must be text or an object.'}
    serialized=json.dumps(settings,ensure_ascii=False,sort_keys=True) if settings is not None else None
    if serialized is not None and len(serialized)>4000: return {'error':'settings must be at most 4000 characters.'}
    cur=conn.execute('INSERT INTO benchmark_runs(task,variant,model,settings,input_tokens,output_tokens,elapsed_seconds,successful,unnecessary_file_reads,indexing_tokens,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (task,variant,str(args['model'])[:200] if args.get('model') is not None else None,serialized,*values[:3],int(success) if success is not None else None,*values[3:],int(time.time())))
    conn.commit()
    return {'saved':True,'id':cur.lastrowid}


def benchmark_list(conn):
    rows=[dict(r) for r in conn.execute('SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 200')]
    for r in rows:
        r['successful'] = bool(r['successful']) if r['successful'] is not None else None
        r['total_tokens'] = r['input_tokens']+r['output_tokens'] if r['input_tokens'] is not None and r['output_tokens'] is not None else None
    groups={}
    for r in rows:
        key=(r['task'],r['model'],r['settings'])
        group=groups.setdefault(key,{'task':r['task'],'model':r['model'],'settings':r['settings'],'baseline':None,'network':None,'net_tokens_saved':None})
        if group[r['variant']] is None: group[r['variant']]=r
    for group in groups.values():
        base,network=group['baseline'],group['network']
        if group['model'] and group['settings'] is not None and base and network and base['total_tokens'] is not None and network['total_tokens'] is not None and network['indexing_tokens'] is not None:
            group['net_tokens_saved']=base['total_tokens']-network['total_tokens']-network['indexing_tokens']
    return {'runs':rows, 'comparisons':list(groups.values()), 'note':'Latest runs grouped by task, model and settings; confirm they were matched. Missing values are unknown.'}


def propose(kn, args, conn):
    project=project_id(kn,conn,args.get('project'))
    kind=str(args.get('kind','')).strip(); name=str(args.get('name','')).strip(); summary=str(args.get('summary','')).strip(); task=str(args.get('task','')).strip(); evidence=str(args.get('evidence','')).strip()
    paths=args.get('paths',[])
    if not project: return {'error':'An indexed project is required.'}
    if kind not in ('lesson','decision','pattern','component') or not name or len(name)>160 or not summary or len(summary)>1200 or not task or not evidence or not isinstance(paths,list) or len(paths)>30:
        return {'error':'Provide kind, name, summary, task, evidence, and up to 30 indexed evidence paths.'}
    evidence_rows=[]
    for path in paths:
        if not isinstance(path,str): return {'error':'Evidence paths must be strings.'}
        row=conn.execute('SELECT digest FROM files WHERE project_id=? AND path=?',(project,path)).fetchone()
        if not row: return {'error':'Every evidence path must be an indexed file in the selected project.'}
        evidence_rows.append((path,row['digest']))
    cur=conn.execute('INSERT INTO memory_proposals(project_id,kind,name,summary,task,evidence,commit_ref,created_at) VALUES(?,?,?,?,?,?,?,?)',(project,kind,name,summary,task[:2000],evidence[:2000],str(args.get('commit_ref',''))[:200],int(time.time())))
    conn.executemany('INSERT OR IGNORE INTO memory_evidence VALUES(?,?,?)',[(cur.lastrowid,p,d) for p,d in evidence_rows]); conn.commit()
    return {'saved':True,'status':'pending','id':cur.lastrowid}


def proposal_list(kn, args, conn):
    project=project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    status=args.get('status','all')
    if status not in ('all','pending','approved','rejected'): return {'error':'Invalid status.'}
    rows=conn.execute('SELECT * FROM memory_proposals WHERE project_id=? AND (?=\'all\' OR status=?) ORDER BY id DESC LIMIT 200',(project,status,status))
    result=[]
    for row in rows:
        r=dict(row); r['paths']=[dict(x) for x in conn.execute('SELECT path,digest FROM memory_evidence WHERE proposal_id=?',(r['id'],))]
        r.update(health(conn,r['id'])); result.append(r)
    return {'proposals':result}


def health(conn, proposal_id):
    row=conn.execute('SELECT project_id,status,commit_ref FROM memory_proposals WHERE id=?',(proposal_id,)).fetchone()
    if not row: return {'error':'Unknown proposal.'}
    evidence=list(conn.execute('SELECT e.path,e.digest,f.digest current_digest FROM memory_evidence e LEFT JOIN files f ON f.project_id=? AND f.path=e.path WHERE e.proposal_id=?',(row['project_id'],proposal_id)))
    changed=[e['path'] for e in evidence if e['digest'] != e['current_digest']]
    state='stale' if changed else ('current' if evidence else 'unverified')
    reasons=['human approved' if row['status']=='approved' else 'not approved', 'indexed file evidence' if evidence else 'no indexed file evidence', state, 'project scoped', 'commit reference provided' if row['commit_ref'] else 'no commit reference']
    score=(0.35 if row['status']=='approved' else 0)+(0.25 if evidence else 0)+(0.2 if state=='current' else 0)+(0.1 if row['commit_ref'] else 0)+0.1
    return {'freshness':state,'changed_paths':changed,'confidence':round(score,2),'confidence_reasons':reasons}


def review(kn, args, conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        return _review(kn, args, conn)
    finally:
        if conn.in_transaction: conn.rollback()


def _review(kn, args, conn):
    project=project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    try: pid=int(args.get('id',0))
    except (ValueError,TypeError): return {'error':'Invalid proposal id.'}
    row=conn.execute('SELECT * FROM memory_proposals WHERE id=? AND project_id=?',(pid,project)).fetchone()
    if not row: return {'error':'Proposal not found in this project.'}
    action=args.get('action')
    if action=='revalidate':
        if row['status']!='approved': return {'error':'Only approved memories can be revalidated.'}
        paths=list(conn.execute('SELECT e.path,f.digest FROM memory_evidence e LEFT JOIN files f ON f.project_id=? AND f.path=e.path WHERE e.proposal_id=?',(project,pid)))
        if not paths or any(not p['digest'] for p in paths): return {'error':'All evidence files must be indexed before revalidation.'}
        conn.executemany('UPDATE memory_evidence SET digest=? WHERE proposal_id=? AND path=?',[(p['digest'],pid,p['path']) for p in paths])
        conn.execute('UPDATE memory_proposals SET reviewed_at=? WHERE id=?',(int(time.time()),pid)); conn.commit()
        return {'saved':True,'status':'approved',**health(conn,pid)}
    if row['status']!='pending': return {'error':'Only pending proposals can be reviewed.'}
    if action=='edit':
        name=str(args.get('name',row['name'])).strip(); summary=str(args.get('summary',row['summary'])).strip(); evidence=str(args.get('evidence',row['evidence'])).strip()
        if not name or len(name)>160 or not summary or len(summary)>1200 or not evidence: return {'error':'Invalid name, summary or evidence.'}
        changed=conn.execute("UPDATE memory_proposals SET name=?,summary=?,evidence=? WHERE id=? AND status='pending'",(name,summary,evidence[:2000],pid)).rowcount
        conn.commit()
        return {'saved':True,'status':'pending'} if changed else {'error':'Proposal was already reviewed.'}
    if action not in ('approve','reject'): return {'error':'action must be edit, approve, or reject.'}
    if action=='approve':
        if health(conn,pid)['freshness']=='stale': return {'error':'Evidence changed since submission; submit a fresh proposal before approval.'}
    status='approved' if action=='approve' else 'rejected'
    changed=conn.execute("UPDATE memory_proposals SET status=?,reviewed_at=? WHERE id=? AND status='pending'",(status,int(time.time()),pid)).rowcount
    if not changed:
        conn.rollback()
        return {'error':'Proposal was already reviewed.'}
    if action=='approve':
        # Create a distinct project-scoped asset; never overwrite existing trusted knowledge.
        cur=conn.execute('INSERT INTO assets(kind,name,summary,tags,source,created_at,scope,project_id) VALUES(?,?,?,?,?,?,?,?)',(row['kind'],row['name'],row['summary'],'',row['evidence'][:500],int(time.time()),'project',project))
        aid=cur.lastrowid
        conn.execute('INSERT INTO asset_projects VALUES(?,?,?)',(aid,project,'used_in'))
    else: aid=None
    conn.execute('UPDATE memory_proposals SET asset_id=? WHERE id=?',(aid,pid)); conn.commit()
    return {'saved':True,'status':status,'asset_id':aid}


def ranked_search(kn, args, conn):
    project=project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    query=str(args.get('query',''))[:1000]; terms=[t for t in kn.split_words(query) if len(t)>1][:12]
    aliases={'authentication':['auth','login','signin','session'], 'auth':['authentication','login','session'], 'user':['account','profile'], 'login':['auth','signin','session']}
    terms=list(dict.fromkeys(terms+[alias for t in terms for alias in aliases.get(t,[])]))
    if not terms: return {'query':query,'results':[]}
    def score(text):
        words=kn.search_words(text); return sum(1 for t in terms if t in words)
    rows=[]
    for r in conn.execute('SELECT path FROM files WHERE project_id=?',(project,)):
        n=score(r['path']);
        if n: rows.append({'type':'file','path':r['path'],'name':Path(r['path']).name,'score':n*2})
    for r in conn.execute('SELECT path,name,line FROM symbols WHERE project_id=?',(project,)):
        n=score(r['name'])*4+score(r['path'])*2
        if n: rows.append({'type':'symbol',**dict(r),'score':n})
    for r in conn.execute('SELECT source,target FROM imports WHERE project_id=?',(project,)):
        target_score=score(r['target'])
        if target_score: rows.append({'type':'import','path':r['source'],'name':r['target'],'score':target_score*3+score(r['source'])})
    for r in conn.execute("SELECT id,kind,name,summary,tags,source FROM assets WHERE scope='global' OR (scope='project' AND project_id=?)",(project,)):
        n=score(r['name'])*4+score(r['summary'])*2+score(r['tags'])
        if n:
            entry={'type':'asset',**dict(r),'score':n}; mem=conn.execute('SELECT id FROM memory_proposals WHERE asset_id=?',(r['id'],)).fetchone()
            if mem:
                entry.update(health(conn,mem['id']))
                entry['score']*=.5+.5*entry['confidence']
                if entry['freshness']=='stale': entry['score']*=.3
            rows.append(entry)
    # Include scoped neighbors of directly matched assets, without crossing project boundaries.
    matched={r['id'] for r in rows if r['type']=='asset'}
    for asset in list(matched):
        for e in conn.execute("SELECT source_id,target_id,weight FROM asset_link_evidence WHERE (scope='*' OR scope=?) AND (source_id=? OR target_id=?)",(project,asset,asset)):
            neighbor=e['target_id'] if e['source_id']==asset else e['source_id']
            if neighbor in matched: continue
            r=conn.execute("SELECT id,kind,name,summary,tags,source FROM assets WHERE id=? AND (scope='global' OR (scope='project' AND project_id=?))",(neighbor,project)).fetchone()
            if r:
                entry={'type':'asset',**dict(r),'score':round(float(e['weight']),2),'via':'graph'}
                memory=conn.execute('SELECT id FROM memory_proposals WHERE asset_id=?',(neighbor,)).fetchone()
                if memory:
                    entry.update(health(conn,memory['id']))
                    entry['score']*=.5+.5*entry['confidence']
                    if entry['freshness']=='stale': entry['score']*=.3
                rows.append(entry); matched.add(neighbor)
    rows.sort(key=lambda r:(-r['score'],str(r.get('name','')).casefold(),r.get('path','')))
    limit=max(1,min(100,int(args.get('limit',20))))
    return {'query':query,'project':project,'results':rows[:limit]}


def bounded_context(kn, args, conn):
    project=project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    try: budget=int(args.get('budget',1000))
    except (ValueError,TypeError): return {'error':'budget must be an integer.'}
    if not 100<=budget<=16000: return {'error':'budget must be between 100 and 16000 estimated tokens.'}
    query=str(args.get('query',''))[:1000]; omit=args.get('exclude_paths',[]); omit_assets=args.get('exclude_asset_ids',[])
    if not isinstance(omit,list) or any(not isinstance(p,str) for p in omit): return {'error':'exclude_paths must be a list of paths.'}
    if not isinstance(omit_assets,list) or any(isinstance(i,bool) or not isinstance(i,int) for i in omit_assets): return {'error':'exclude_asset_ids must be a list of integer asset IDs.'}
    result={'project':project,'budget':budget,'budget_type':'estimated characters / 4; not a model tokenizer','map':[],'results':[],'truncated':False}
    for r in conn.execute('SELECT path FROM files WHERE project_id=? ORDER BY path LIMIT 10',(project,)):
        if r['path'] not in omit: result['map'].append(r['path'])
    candidates=ranked_search(kn,{'project':project,'query':query,'limit':100},conn)['results'] if query else []
    for item in candidates:
        if item.get('path') in omit or (item.get('type')=='asset' and item.get('id') in omit_assets): continue
        result['results'].append(item)
        if kn.estimate(json.dumps(result,ensure_ascii=False,separators=(',',':')))>budget-20:
            result['results'].pop(); result['truncated']=True; break
    while result['map'] and kn.estimate(json.dumps(result,ensure_ascii=False,separators=(',',':')))>budget-20: result['map'].pop(); result['truncated']=True
    if kn.estimate(json.dumps(result,ensure_ascii=False,separators=(',',':')))>budget-20:
        return {'error':'Budget is too small for the project metadata.'}
    result['estimated_tokens']=kn.estimate(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    return result


def dependencies(kn,args,conn):
    project=project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    items=[]
    symbols=list(conn.execute('SELECT path,name,line FROM symbols WHERE project_id=?',(project,)))
    for imp in conn.execute('SELECT source,target FROM imports WHERE project_id=? ORDER BY source,target LIMIT 500',(project,)):
        leaf=imp['target'].replace('/','.').split('.')[-1]
        matches=[s for s in symbols if s['name']==leaf and s['path']!=imp['source']]
        items.append({'source':imp['source'],'import':imp['target'],'candidates':[dict(s) for s in matches[:10]],'status':'provisional' if matches else 'unresolved'})
    return {'dependencies':items,'note':'Name-based candidates are not compiler-resolved.'}


def discover(conn):
    rows=conn.execute('SELECT a.id,a.kind,a.name,a.summary,count(DISTINCT ap.project_id) projects FROM assets a JOIN asset_projects ap ON ap.asset_id=a.id WHERE a.scope=\'global\' GROUP BY a.id HAVING count(DISTINCT ap.project_id)>1 ORDER BY projects DESC,a.name LIMIT 100')
    candidates=[dict(r) for r in rows]
    for candidate in candidates:
        candidate['evidence']=[dict(r) for r in conn.execute('SELECT project_id,relation FROM asset_projects WHERE asset_id=? ORDER BY project_id',(candidate['id'],))]
    scoped=conn.execute("SELECT lower(trim(name)) normalized,kind,count(DISTINCT project_id) projects FROM assets WHERE scope='project' AND kind IN ('pattern','lesson','decision','component') GROUP BY normalized,kind HAVING count(DISTINCT project_id)>1 ORDER BY projects DESC,normalized LIMIT 100")
    for group in scoped:
        evidence=[dict(r) for r in conn.execute("SELECT id,name,summary,project_id FROM assets WHERE scope='project' AND lower(trim(name))=? AND kind=? ORDER BY project_id",(group['normalized'],group['kind']))]
        candidates.append({'name':evidence[0]['name'],'kind':group['kind'],'projects':group['projects'],'summary':'Similar names occur in separate projects; review each source before drawing conclusions.','evidence':evidence})
    return {'candidates':candidates, 'note':'Name matches and shared asset associations are candidates for human review, not evidence that project-specific behavior is global.'}
