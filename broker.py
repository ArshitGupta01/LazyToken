"""Task-aware, project-scoped metadata retrieval with optional session deduplication."""
from __future__ import annotations
import hashlib
import json
import time
import features

MODES={'compact':250,'balanced':600,'deep':1200}


def _encoded(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)


def _key(item):
    kind=item['type']
    if kind=='asset': return 'asset:'+str(item['id'])
    return ':'.join(str(item.get(k,'')) for k in ('type','path','name','line'))


def task_context(kn,args,conn):
    project=features.project_id(kn,conn,args.get('project'))
    if not project: return {'error':'An indexed project is required.'}
    task=args.get('task')
    if not isinstance(task,str) or not task.strip() or len(task)>2000: return {'error':'task must be non-empty text up to 2000 characters.'}
    inferred_complex = len(kn.split_words(task)) > 24 or any(term in task.casefold() for term in ('architecture','migration','cross-project','across projects'))
    mode=args.get('mode', 'balanced' if inferred_complex else 'compact')
    if mode not in MODES: return {'error':'mode must be compact, balanced, or deep.'}
    skip=args.get('skip_retrieval',False); repeat=args.get('include_seen',False); complete=args.get('context_is_complete',False)
    if not all(isinstance(x,bool) for x in (skip,repeat,complete)): return {'error':'skip_retrieval, include_seen and context_is_complete must be booleans.'}
    explicit_text_task=task.lstrip().casefold().startswith(('rewrite this text','format this text','summarize this text','summarise this text'))
    skip=skip or (complete and explicit_text_task)
    session=args.get('session_id')
    if session is not None and (not isinstance(session,str) or not session.strip() or len(session)>120): return {'error':'session_id must be non-empty text up to 120 characters.'}
    budget=args.get('budget',MODES[mode])
    if isinstance(budget,bool) or not isinstance(budget,int) or not 100<=budget<=16000: return {'error':'budget must be an integer from 100 to 16000 estimated tokens.'}
    response={'project':project,'mode':mode,'budget':budget,'budget_type':'estimate: characters / 4; not a tokenizer','decision':'skip' if skip else 'retrieve','reason':('Caller supplied complete context for a text-only task.' if complete and explicit_text_task else 'Caller explicitly requested no retrieval.') if skip else 'Search project metadata for task-relevant breadcrumbs.','results':[],'truncated':False,'suppressed_seen':0}
    if skip:
        response['estimated_tokens']=kn.estimate(_encoded(response))+8
        if response['estimated_tokens']>budget: return {'error':'Budget is too small for response metadata.'}
        return response
    ranked=features.ranked_search(kn,{'project':project,'query':task,'limit':100},conn)
    if 'error' in ranked: return ranked
    results=ranked['results']
    # Graph-only associations are not sufficient to assert relevance.
    if not any(item.get('via')!='graph' and item.get('score',0)>=2 for item in results):
        response['decision']='abstain';response['reason']='No confident metadata match; inspect the project or refine the task.';response['estimated_tokens']=kn.estimate(_encoded(response))+8
        return response if response['estimated_tokens']<=budget else {'error':'Budget is too small for response metadata.'}
    shown=[]
    for raw in results:
        crumb={k:raw[k] for k in ('type','name','path','line','id','kind','freshness','confidence','via') if k in raw}
        crumb['why']=raw.get('why','Metadata match.')
        key=_key(crumb)
        fingerprint_data={'crumb':crumb}
        if raw.get('path'):
            indexed=conn.execute('SELECT digest FROM files WHERE project_id=? AND path=?',(project,raw['path'])).fetchone()
            fingerprint_data['file_digest']=indexed['digest'] if indexed else None
        if raw['type']=='asset':
            fingerprint_data.update({k:raw.get(k) for k in ('summary','tags','source')})
        fingerprint=hashlib.sha256(_encoded(fingerprint_data).encode('utf-8')).hexdigest()
        if session and not repeat:
            seen=conn.execute('SELECT fingerprint FROM context_session_items WHERE project_id=? AND session_id=? AND item_key=?',(project,session,key)).fetchone()
            if seen and seen['fingerprint']==fingerprint: response['suppressed_seen']+=1;continue
        response['results'].append(crumb)
        if kn.estimate(_encoded(response))+8>budget:
            response['results'].pop();response['truncated']=True;break
        shown.append((project,session,key,fingerprint,int(time.time())))
    if not response['results'] and response['suppressed_seen']:
        response['reason']='All matching breadcrumbs were already supplied in this session.'
    response['estimated_tokens']=kn.estimate(_encoded(response))+8
    if response['estimated_tokens']>budget: return {'error':'Budget is too small for response metadata.'}
    if session and shown:
        conn.executemany('INSERT INTO context_session_items VALUES(?,?,?,?,?) ON CONFLICT(project_id,session_id,item_key) DO UPDATE SET fingerprint=excluded.fingerprint,updated_at=excluded.updated_at',shown);conn.commit()
    return response


def clear_session(kn,args,conn):
    project=features.project_id(kn,conn,args.get('project'));session=args.get('session_id')
    if not project or not isinstance(session,str) or not session.strip() or len(session)>120: return {'error':'An indexed project and session_id are required.'}
    count=conn.execute('DELETE FROM context_session_items WHERE project_id=? AND session_id=?',(project,session)).rowcount;conn.commit()
    return {'cleared':count}


def session_checkpoint(kn,args,conn):
    project=features.project_id(kn,conn,args.get('project'));session=args.get('session_id')
    if not project or not isinstance(session,str) or not session.strip() or len(session)>120: return {'error':'An indexed project and session_id are required.'}
    rows=conn.execute('SELECT item_key,updated_at FROM context_session_items WHERE project_id=? AND session_id=? ORDER BY item_key',(project,session)).fetchall()
    return {'project':project,'session_id':session,'supplied_items':len(rows),'recent_keys':[r['item_key'] for r in rows[:30]],'truncated':len(rows)>30,'note':'Reuse this project and session_id after compaction. Stored fingerprints suppress unchanged breadcrumbs; source contents are not stored.'}
