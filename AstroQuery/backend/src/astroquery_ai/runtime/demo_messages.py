"""Public, version-bound follow-up projection for portable demonstration histories."""
import json

PUBLIC_META = {'model', 'model_calls', 'fallback', 'elapsed_seconds'}
PUBLIC_COLUMNS={'id','task_id','role','content','thought_steps','citations','created_at','scope','request_id','question_id','answer','status','meta'}

def validate_public_message(row, task_id, snapshot_ref):
    scope=json.loads(row.get('scope') or 'null')
    meta=json.loads(row.get('meta') or '{}')
    if (set(row)-PUBLIC_COLUMNS or row.get('task_id') != task_id or row.get('role') not in {'user','assistant'}
            or row.get('status') != 'complete' or not isinstance(scope,dict)
            or scope.get('snapshot_ref') != snapshot_ref or not scope.get('delivery_id')
            or not isinstance(scope.get('delivery_revision'),int)
            or set(meta)-PUBLIC_META or json.loads(row.get('thought_steps') or '[]')):
        raise ValueError('Demo follow-up must be a complete public answer pinned to the saved snapshot')

def public_messages(conn, task_id, scope):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_messages'").fetchone():
        return []
    rows=[dict(r) for r in conn.execute('SELECT * FROM agent_messages WHERE task_id=? ORDER BY rowid',(task_id,))]
    questions={r['id']:r for r in rows if r['role']=='user' and json.loads(r.get('scope') or 'null')==scope}
    answers=[r for r in rows if r['role']=='assistant' and r.get('status')=='complete'
             and r.get('question_id') in questions and r.get('answer')
             and json.loads(r.get('scope') or 'null')==scope]
    used={r['question_id'] for r in answers}
    keep={r['id'] for r in answers}|used
    result=[]
    for row in rows:
        if row['id'] not in keep: continue
        row['thought_steps']='[]'
        row['meta']=json.dumps({k:v for k,v in json.loads(row.get('meta') or '{}').items() if k in PUBLIC_META},ensure_ascii=False)
        validate_public_message(row,task_id,scope['snapshot_ref'])
        result.append(row)
    return result
