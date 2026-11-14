"""Read-only UI facts. Historical reads never borrow future object versions."""
from collections import Counter
from datetime import datetime
import json
import re

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.stages import JOB_STAGE
from astroquery_ai.science.evidence_views import review_evidence

STAGES = [('understand','任务理解'),('retrieval','数据检索'),('extraction','数据提取'),
          ('quality_check','质量检查'),('clean','数据清洗'),('comparison','数据对照'),
          ('deliver','数据交付'),('insight','数据洞察'),('done','最终查询摘要')]
EXECUTION = {'catalog':'retrieval','literature':'retrieval','acquisition':'retrieval',
             'extraction':'extraction','quality':'quality_check','normalization':'clean',
             'postcheck':'comparison','delivery':'deliver','insight':'insight'}
TERMINAL = {'completed','cancelled','failed','error','budget_exhausted','definition_invalidated'}

def seconds(a,b):
    if not a or not b:return None
    try:return max(0,(datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds())
    except (ValueError,TypeError):return None

def redacted(value):
    text=str(value or '')
    text=re.sub(r'(?i)(bearer\s+)[\w.\-]+',r'\1[已隐藏]',text)
    text=re.sub(r'(?i)((?:api[_-]?key|token|authorization|password|secret)\s*[=:]\s*)[^\s&,;]+',r'\1[已隐藏]',text)
    return text[:8000]

def history_scope(application,conn,task_id,at_seq=None):
    """Resolve one source horizon before either cache lookup or history reads."""
    task=application.repository.task(conn,task_id)
    source=application.history.source(conn,task_id)
    capture_identity=None
    if source!=task_id:
        from .presentation_cache import cached_objects
        meta=conn.execute("SELECT version,content_sha256,created_at FROM objects WHERE task_id=? "
            "AND kind='replay_snapshot' AND object_id=? ORDER BY version DESC LIMIT 1",
            (task_id,task_id)).fetchone()
        if meta is None:
            raise DomainError('REPLAY_SOURCE_UNAVAILABLE','回放快照不可用',410)
        captured=cached_objects(application,conn,task_id,'replay_snapshot',meta[2],
            lambda:[application.repository.object(conn,task_id,'replay_snapshot',task_id,meta[0])])[0]
        saved=captured.get('source_view') or {}
        horizon=saved.get('core_event_cursor',saved.get('last_event_seq'))
        if type(horizon) is not int or horizon<0:
            raise DomainError('REPLAY_SOURCE_UNAVAILABLE','回放未保存原历史游标',410)
        # The snapshot holds lifecycle/title fallbacks as well as the event
        # horizon. Never replace those with the source's later mutable state.
        task={key:saved[key] for key in task if key in saved}
        task['last_event_seq']=horizon
        task['_captured_reviews']=saved.get('reviews',[])
        capture_identity=(task_id,meta[0],meta[1])
    cursor=task['last_event_seq'] if at_seq is None else at_seq
    if type(cursor) is not int or not 0<=cursor<=task['last_event_seq']:
        raise DomainError('RESYNC_REQUIRED','历史游标无效',422)
    return task,source,cursor,capture_identity


def history(application,conn,task_id,at_seq=None):
    task,source,cursor,_=history_scope(application,conn,task_id,at_seq)
    from .presentation_cache import history_rows
    rows=history_rows(application,conn,source,cursor)
    cutoff=rows[-1]['committed_at'] if rows else task['created_at']
    return task,source,cursor,cutoff,rows


def objects(conn,tid,kind,cutoff):
    rows=conn.execute('''SELECT payload FROM objects o WHERE task_id=? AND kind=? AND created_at<=?
        AND version=(SELECT max(version) FROM objects i WHERE i.task_id=o.task_id AND i.kind=o.kind
        AND i.object_id=o.object_id AND i.created_at<=?) ORDER BY created_at,object_id''',(tid,kind,cutoff,cutoff))
    return [loads(r[0]) for r in rows]

def replay_clock(application,task_id):
    """The clock needs event positions, not the execution log or the scientific result."""
    with application.repository.read() as conn:
        task,tid,_,_,events=history(application,conn,task_id)
        # A supported recovery can produce another execution after an earlier
        # terminal event. End at the current terminal, not the first one; later
        # exports and follow-ups are still outside the recorded query clock.
        terminal=next((e for e in reversed(events) if e['kind']=='task_state_changed'
                       and e['payload'].get('lifecycle') in TERMINAL),None) if task['lifecycle'] in TERMINAL else None
        if terminal:
            events=[e for e in events if e['seq']<=terminal['seq']]
        timeline=[];milestones=[];terminal_at=None
        for e in events:
            p=e['payload'];kind=e['kind']
            if kind.startswith('export_'):continue
            point={'seq':e['seq'],'at':e['committed_at'],'kind':kind}
            if kind in {'review_ready','answer_received','review_applied','review_withdrawn'}:
                point['review_id']=p.get('review_id')
            if kind=='execution_stage_changed':
                point['stage_id']=EXECUTION.get(p.get('stage_id'),'understand')
                milestones.append(point)
            if kind=='task_state_changed':point['lifecycle']=p.get('lifecycle')
            timeline.append(point)
            if point.get('lifecycle') in TERMINAL:
                terminal_at=point['at']
            elif kind=='task_state_changed':
                terminal_at=None
        # The only future information allowed in replay is a locked historical
        # choice. It never changes the as-of question, receipt or scientific data.
        gates=[]
        saved={r['review_id']:r for r in (task['_captured_reviews'] if tid!=task_id
                                         else application.reviews.list(conn,tid))}
        for e in events:
            if e['kind']!='review_ready':continue
            rid=e['payload']['review_id'];review=saved.get(rid,{})
            revision=e['payload'].get('revision',1)
            answer=review.get('answer') or {}
            matched=(review.get('revision')==revision and
                     answer.get('basis_hash')==review.get('basis_hash') and bool(answer))
            next_question=next((x['seq'] for x in events if x['seq']>e['seq'] and
                x['kind'] in {'review_ready','review_withdrawn'} and x['payload'].get('review_id')==rid),None)
            accepted=next((x for x in events if x['seq']>e['seq'] and
                (next_question is None or x['seq']<next_question) and
                x['kind']=='answer_received' and x['payload'].get('review_id')==rid and
                x['payload'].get('answer_id')==answer.get('answer_id')),None)
            gates.append({'key':f"{rid}:{revision}:{e['seq']}",'review_id':rid,
                'review_revision':revision,'basis_hash':review.get('basis_hash'),
                'question_seq':e['seq'],'answer_seq':accepted['seq'] if accepted else None,
                'available':bool(matched and accepted),
                'answer':{k:answer.get(k) for k in ('action','correction','correction_measurement_id',
                    'selected_interpretation_id','comparison_outcome','simulation','actor','actual_user_answer')}
                    if matched and accepted else None})
        return {'created_at':task['created_at'],'terminal_at':terminal_at,'timeline':timeline,
                'milestones':milestones,'review_gates':gates}

def _advance_event(state,event):
    lifecycle=state['lifecycle']
    delivery_ref=state['delivery_ref']
    active=state['active']
    intervals=state['intervals']
    opened=state['opened']
    human_wait=state['human_wait']
    waiting=state['waiting']
    jobs=state['jobs']
    milestones=state['milestones']
    waiting_reviews=state['waiting_reviews']
    p=event['payload'];kind=event['kind'];at=event['committed_at']
    if kind=='task_state_changed':
        lifecycle=p.get('lifecycle',lifecycle)
        if waiting and lifecycle not in {'waiting_review','waiting_input'}:
            waiting['end']=at;human_wait.append(waiting);waiting=None
        if not waiting and lifecycle in {'waiting_review','waiting_input'}:
            waiting={'stage_id':active,'start':at,'end':None}
    if kind=='query_confirmed':lifecycle='running'
    if kind=='review_ready':waiting_reviews.add(p.get('review_id'))
    if kind in {'review_applied','review_withdrawn'}:
        waiting_reviews.discard(p.get('review_id'))
        if lifecycle=='waiting_review' and not waiting_reviews:
            lifecycle='running'
            if waiting:
                waiting['end']=at;human_wait.append(waiting);waiting=None
    if kind=='job_state_changed':jobs[p.get('job_id')]=p
    if kind=='execution_stage_changed':
        if opened:opened['end']=at;intervals.append(opened)
        active=EXECUTION.get(p.get('stage_id'),'understand')
        opened={'stage_id':active,'execution_stage':p.get('stage_id'),'start':at,'end':None,
                'local_repair':p.get('local_repair',False),'seq':event['seq']}
        milestones.append({'seq':event['seq'],'at':at,'stage_id':active})
    if kind=='delivery_ready':delivery_ref=p.get('delivery_ref')
    state['lifecycle']=lifecycle
    state['delivery_ref']=delivery_ref
    state['active']=active
    state['intervals']=intervals
    state['opened']=opened
    state['human_wait']=human_wait
    state['waiting']=waiting
    state['jobs']=jobs
    state['milestones']=milestones
    state['waiting_reviews']=waiting_reviews


def presentation(application,task_id,at_seq=None,include_chat_activity=False,activity_limit=5):
    with application.repository.read() as conn:
        return presentation_in_snapshot(application,conn,task_id,at_seq,include_chat_activity,activity_limit)


def presentation_in_snapshot(application,conn,task_id,at_seq=None,include_chat_activity=False,
                             activity_limit=5,*,reviews_data=None):
    from .presentation_cache import cache_for, dependencies, cached_projection, save_projection
    task,source,cursor,capture_identity=history_scope(application,conn,task_id,at_seq)
    cache=cache_for(application)
    key=dependencies(conn, (task_id,capture_identity or task), source, cursor, include_chat_activity, activity_limit)
    result=cached_projection(cache,key)
    if result is None:
        result=_presentation_uncached(application,conn,task_id,at_seq,include_chat_activity,
                                      activity_limit,reviews_data=reviews_data)
        save_projection(cache,key,result)
    return result


def _presentation_uncached(application,conn,task_id,at_seq=None,include_chat_activity=False,
                           activity_limit=5,*,reviews_data=None):
    repo=application.repository
    task,tid,cursor,cutoff,events=history(application,conn,task_id,at_seq)
    current=at_seq is None or cursor==task['last_event_seq']
    cached={}
    def get(kind):
        if kind not in cached:
            from .presentation_cache import cached_objects
            cached[kind]=cached_objects(application,conn,tid,kind,cutoff,lambda:objects(conn,tid,kind,cutoff))
        return cached[kind]
    drafts=get('draft');draft=drafts[-1] if drafts else {}
    specs=get('confirmed_query');spec=specs[-1] if specs else {}
    if not any(e['kind']=='query_confirmed' for e in events):spec={}
    bindings=spec.get('properties') or [b for b in (draft.get('property_support') or {}).get('bindings',[])
        if b['property_id'] in draft.get('selected_property_ids',[])]
    names={b['property_id']:b['definition']['name_cn'] for b in bindings}
    from .presentation_cache import folded_events
    state=folded_events(application,tid,events,_advance_event,{
        'lifecycle':'clarifying','delivery_ref':None,'active':'understand','intervals':[],
        'opened':None,'human_wait':[],'waiting':None,'jobs':{},'milestones':[],'waiting_reviews':set()})
    lifecycle=state['lifecycle']
    delivery_ref=state['delivery_ref']
    active=state['active']
    intervals=state['intervals']
    opened=state['opened']
    human_wait=state['human_wait']
    waiting=state['waiting']
    jobs=state['jobs']
    milestones=state['milestones']
    waiting_reviews=state['waiting_reviews']
    if current:lifecycle=task['lifecycle']
    terminal_at=next((e['committed_at'] for e in reversed(events) if e['kind']=='task_state_changed' and e['payload'].get('lifecycle') in TERMINAL),None)
    # Some archived tasks saved an outcome without a terminal event.
    # Once only later exports remain, the stored outcome is known. Its
    # missing timestamp cannot be estimated from those export times.
    if not current and not terminal_at and task['lifecycle'] in TERMINAL and not conn.execute(
        "SELECT 1 FROM events WHERE task_id=? AND seq>? AND seq<=? AND substr(json_extract(payload,'$.kind'),1,7)!='export_' LIMIT 1",
        (tid,cursor,task['last_event_seq'])).fetchone():
        lifecycle=task['lifecycle']
    wall_end=terminal_at if lifecycle in TERMINAL else cutoff
    if waiting:
        waiting['end']=cutoff;human_wait.append(waiting)
    if opened:
        opened['end']=terminal_at if lifecycle in TERMINAL else None;intervals.append(opened)
    if intervals:
        intervals.insert(0,{'stage_id':'understand','start':task['created_at'],'end':intervals[0]['start'],
            'local_repair':False,'seq':0,'execution_stage':'understand'})
    for item in intervals:item['seconds']=seconds(item['start'],item['end'])
    pools=(get('material_preparation') or [{}])[-1].get('pools',{})
    policy=spec.get('run_policy',{}).get('literature',{})
    target=policy.get('target_readable_per_property',policy.get('maximum_body_works_per_property',policy.get('selected_limit')))
    # The frozen policy has changed names across releases; never infer a
    # different target from number of completed worker jobs.
    for key in ('target_works_per_property','readable_target','target_per_property'):
        if key in policy:target=policy[key]
    material=[]
    for pid in list(names)+[k for k in pools if k not in names]:
        p=pools.get(pid,{})
        if pid not in pools:
            material.append({'property_id':pid,'name':names.get(pid,pid),'recorded':False,
                'evaluated':None,'eligible':None,'attempted':None,'readable':None,'target':None,
                'long_downloaded':None,'waiting':None,'batch':None,'action_step':None,
                'action':'此历史未保存分性质材料池' if lifecycle in TERMINAL else '等待材料准备',
                'state':'unknown' if lifecycle in TERMINAL else 'waiting'})
            continue
        material.append({'property_id':pid,'name':names.get(pid,pid),'evaluated':len(p.get('evaluated',[])),
            'eligible':len(p.get('eligible',[])),'attempted':len(p.get('attempted',[])),
            'readable':len(p.get('acquired',[])),'target':target,'batch':p.get('batches_used'),
            'long_downloaded':len(p.get('long_downloaded',[])),'waiting':len(set(p.get('eligible',[]))-set(p.get('attempted',[]))),
            'action':'已备齐' if target and len(p.get('acquired',[]))>=target else '本轮材料准备已结束' if (get('material_preparation') or [{}])[-1].get('closed') else '继续检索',
            'close_reason':p.get('close_reason'),
            'action_step':None,
            'state':'completed' if target and len(p.get('acquired',[]))>=target else 'partial' if (get('material_preparation') or [{}])[-1].get('closed') else 'running'})
    def cardinality(kind):
        return conn.execute('SELECT count(DISTINCT object_id) FROM objects WHERE task_id=? AND kind=? AND created_at<=?',(tid,kind,cutoff)).fetchone()[0]
    figure_count=cardinality('figure');candidate_count=cardinality('candidate')
    records=get('measurement');sources=get('source');checks=get('archive_comparison')
    score=(get('quality') or [{}])[-1]
    components={x['key']:x for x in score.get('components',[])}
    quality_scope=components.get('quality_cleaning',{})
    # Source-specific job failures are coverage facts, not task failure.
    failed=[{'job_id':jid,**p} for jid,p in jobs.items() if p.get('status')=='failed']
    job_rows={r['job_id']:dict(r) for r in conn.execute('SELECT job_id,kind,owner,payload FROM jobs WHERE task_id=?',(tid,))}
    visible_jobs={jid:{**job_rows[jid],'status':state.get('status'),
        'payload':loads(job_rows[jid]['payload'])} for jid,state in jobs.items() if jid in job_rows}
    for item in material:
        pid=item['property_id']
        if any(job['status']=='running' and job['kind']=='acquire_work' and
               job['payload'].get('work_id') in pools.get(pid,{}).get('attempted',[])
               for job in visible_jobs.values()):
            item['action_step']='acquire'
        elif any(job['status']=='running' and job['kind']=='literature_discover' and
                 job['payload'].get('property_id')==pid for job in visible_jobs.values()):
            item['action_step']='search'
    def kinds(*wanted):return [p for jid,p in jobs.items() if job_rows.get(jid,{}).get('kind') in wanted]
    def count_jobs(*wanted):return sum(p.get('status')=='succeeded' for p in kinds(*wanted))
    def progress(unit,*wanted):
        values=kinds(*wanted)
        if not values:return None
        return {'unit':unit,'total':len(values),'finished':sum(
            item.get('status') in {'succeeded','failed','cancelled','not_run'} for item in values)}
    def operation_state(*wanted):
        values=[p.get('status') for p in kinds(*wanted)]
        if not values:return 'unknown'
        if 'running' in values:return 'running'
        if any(v in {'ready','waiting_dependency','awaiting_review'} for v in values):return 'waiting'
        if 'failed' in values:return 'partial'
        if all(v=='cancelled' for v in values):return 'cancelled'
        if all(v=='not_run' for v in values):return 'skipped'
        return 'completed'
    catalog_ops=[k for k,s in JOB_STAGE.items() if s=='catalog']
    material_ops=[k for k,s in JOB_STAGE.items() if s in {'literature','acquisition'} and k!='attachment_discover']
    reports=get('insight');insight=reports[-1] if reports else None
    insight_presentation = spec.get('run_policy', {}).get('insights', {}).get('presentation')
    material_summary = insight_presentation in {'material-summary/1', 'research-workbench/2'}
    composite_insights = insight_presentation == 'research-workbench/2'
    insight_state=operation_state('insights')
    if insight and insight.get('status') != 'pending':
        insight_state='skipped' if insight.get('status','').startswith('disabled') else 'partial' if insight.get('status')=='partial' else 'completed'
    prepared=(get('material_preparation') or [{}])[-1]
    literature_state=operation_state(*material_ops)
    if prepared.get('closed') and pools:
        literature_state='completed' if target and all(len(p.get('acquired',[]))>=target for p in pools.values()) else 'partial'
    reviewed_ids={e['payload']['review_id'] for e in events if e['kind']=='review_ready'}
    quality_closed=lifecycle in TERMINAL or active in {'clean','comparison','deliver','insight','done'}
    review_state=operation_state('apply_review')
    if reviewed_ids and count_jobs('apply_review')<len(reviewed_ids) and review_state=='unknown':review_state='waiting'
    if not reviewed_ids and quality_closed:review_state='skipped'
    reextract_state=operation_state('quality_reextract')
    if reextract_state=='unknown' and quality_closed:reextract_state='skipped'
    normalize_state=operation_state('normalize')
    if quality_scope and quality_closed and quality_scope.get('processed_or_no_change_verified',0)<quality_scope.get('eligible_records',0):normalize_state='partial'
    block_states={
        'understand':['completed' if spec.get('target') or draft.get('target') else 'waiting' if lifecycle=='waiting_input' else 'running' if operation_state('prepare') in {'running','waiting'} else 'pending',
            'completed' if spec else 'waiting' if bindings else 'pending','completed' if spec else 'waiting' if (draft.get('pending_question') or {}).get('preview') else 'pending'],
        'retrieval':[operation_state(*catalog_ops),literature_state,operation_state('attachment_discover')],
        'extraction':[operation_state('catalog_extract','attachment_extract'),operation_state('paper_batch','source_reconcile'),operation_state('paper_figures','paper_figure_page')],
        'quality_check':[operation_state('quality_verify','assess_batch'),reextract_state,review_state],
        'clean':[normalize_state,normalize_state,normalize_state],
        'comparison':[operation_state('compare_results')]*3,
        'deliver':['completed' if delivery_ref else 'running' if active=='deliver' else 'pending']*3,
        'insight':['completed' if insight else 'unknown',insight_state,'completed' if insight and insight_state!='skipped' else insight_state],
        'done':['completed' if lifecycle=='completed' else 'cancelled' if lifecycle=='cancelled' else 'partial' if lifecycle in TERMINAL else 'pending']*2}
    def step(label,count=None,unit=None,detail=None):return {'label':label,'count':count,'unit':unit,'detail':detail}
    blocks={
        'understand':[step('识别天体',detail=(spec.get('target') or draft.get('target') or {}).get('main_id')),step('选择具体性质',len(bindings),'项'),step('确认请求',detail='已确认，原请求只读' if spec else '等待确认')],
        'retrieval':[step('星表检索',count_jobs('catalog_extract'),'张已处理表','无匹配与访问未完成分别见处理范围'),step('文献检索与下载',len({w for p in pools.values() for w in p.get('acquired',[])}),'篇不同可读正文'),step('官方补充材料',count_jobs('attachment_discover'),'篇已检查父论文')],
        'extraction':[step('星表与官方表行列',sum(s.get('kind') in {'catalog','official_attachment'} for s in sources),'份来源'),step('提取的性质候选',candidate_count,'项候选'),step('论文图像',figure_count,'幅已保存图像')],
        'quality_check':[step('原文核验',count_jobs('quality_verify'),'批'),step('必要局部重提',count_jobs('quality_reextract'),'批'),step('人工判断与答后复检',count_jobs('apply_review'),'次已应用')],
        'clean':[step('判定表示和单位'),step('转换或保留原报',sum(r.get('main_state')=='ready' for r in get('derived')),'条主值已处理'),step('核对主值与独立误差',detail='误差各成分的状态见记录详情')],
        'comparison':[step('按性质及必要条件归集',len(checks),'份核查'),step('核对重复记载',sum(len(x.get('duplicates',[])) for x in checks),'个归档组'),step('复核明显差异',detail='未检查范围不表示没有差异')],
        'deliver':[step('固定科学快照',detail='已封存' if delivery_ref else '尚未封存'),step('整理记录及原件入口',len(records),'条原报'),step('开放结果与导出',detail='可查看' if delivery_ref else '等待交付')],
        'insight':[step('生成资料总结'),step('生成性质综合洞察'),step('关联原件与任务知识快照')]
            if composite_insights else [step('整理资料与性质'),step('生成资料总结'),step('关联原件与知识')]
            if material_summary else [step('汇集已交付记录'),step('按性质生成解释'),step('关联证据与知识条目')],
        'done':[step('实际结局',detail=lifecycle),step('耗时和成果',len(records),'条原报')]}
    visited={x['stage_id'] for x in intervals};position=dict((k,i) for i,(k,_) in enumerate(STAGES))
    stages=[]
    for sid,name in STAGES:
        if sid == 'insight' and material_summary:
            name = '资料总结与性质洞察' if composite_insights else '资料总结'
            material_report = (insight.get('material_report') or {}) if composite_insights and insight else insight
            if material_report and material_report.get('counts'):
                ready = sum(c['ready'] for c in material_report['counts'].values())
                requested = sum(c['requested'] for c in material_report['counts'].values())
                blocks[sid][0 if composite_insights else 1] = step('生成资料总结', ready, '份', f'{ready} / {requested} 份资料总结')
            if composite_insights and insight:
                prop_report = insight.get('property_report') or {}
                blocks[sid][1] = step('生成性质综合洞察', len(prop_report.get('qualified_property_ids', [])), '项已通过',
                    (insight.get('components', {}).get('property') or {}).get('reason'))
        seen=sid=='understand' or sid in visited or sid=='done' and lifecycle in TERMINAL
        state='pending'
        if seen:
            state='completed' if (sid!=active and (position[sid]<position.get(active,0) or sid in visited)) or lifecycle=='completed' else 'running' if sid==active else 'waiting'
            if lifecycle in TERMINAL and state!='completed':state='cancelled' if lifecycle=='cancelled' else 'partial'
        if sid=='done':state=('completed' if lifecycle=='completed' else 'cancelled' if lifecycle=='cancelled' else 'partial') if lifecycle in TERMINAL else 'pending'
        if sid=='understand' and spec:state='completed'
        if sid=='deliver' and delivery_ref:state='completed'
        if sid=='comparison' and any(x.get('state') not in {'checked','not_applicable'} for x in checks):state='partial'
        if state=='completed' and sid=='extraction' and components.get('extraction',{}).get('state')=='partial':state='partial'
        if state=='completed' and sid=='quality_check' and quality_scope.get('concluded_roots',0)<quality_scope.get('candidate_roots',0):state='partial'
        if sid=='quality_check' and quality_scope:
            blocks[sid][0]=step('原文核验',quality_scope.get('concluded_roots'),'项候选已闭环',f"应核 {quality_scope.get('candidate_roots','未记录')} 项；未闭环范围保留")
        if sid=='clean' and quality_scope:
            blocks[sid][1]=step('转换或保留原报',quality_scope.get('processed_or_no_change_verified'),'条已处理/核验不变',f"进入范围 {quality_scope.get('eligible_records','未记录')} 条；其余状态按原报逐项保留")
        owned_failures=[f for f in failed if EXECUTION.get(JOB_STAGE.get(job_rows.get(f['job_id'],{}).get('kind'))) == sid]
        if owned_failures and state=='completed':state='partial'
        if sid=='understand' and not spec and lifecycle in {'waiting_input','paused','interrupted'}:state='waiting'
        if sid=='insight' and insight_state=='skipped':
            state='skipped';blocks[sid][1]['detail']='此历史版本未启用洞察；不补算为已生成。'
        for index,block in enumerate(blocks[sid]):
            block['state']=block_states[sid][index]
            if not seen and block['state'] in {'unknown','skipped'}:block['state']='pending'
            block['state_basis']='已保存的原件/作业/回执；同一操作内未记录独立内部进度'
        if sid=='quality_check' and quality_scope and quality_scope.get('concluded_roots',0)<quality_scope.get('candidate_roots',0) and quality_closed:blocks[sid][0]['state']='partial'
        stages.append({'id':sid,'name':name,'status':state,'seen':seen,'blocks':blocks[sid],
            'human_wait_seconds':sum(seconds(w['start'],w['end']) or 0 for w in human_wait if w['stage_id']==sid) if any(w['stage_id']==sid for w in human_wait) else None,
            'summary':next((b['detail'] for b in blocks[sid] if b.get('detail')),''),
            'intervals':[x for x in intervals if x['stage_id']==sid],
            'local_failures':len(owned_failures)})
    receipts=[e['payload'] for e in events if e['kind']=='review_applied']
    revisions={e['payload']['review_id']:e['payload'].get('revision',1) for e in events if e['kind']=='review_ready'}
    withdrawn={e['payload']['review_id'] for e in events if e['kind']=='review_withdrawn'}
    by_id={r['measurement_id']:r for r in records}
    change_example=None
    for d in get('derived'):
        raw=by_id.get(d.get('measurement_id'),{})
        raw_value=raw['value'].get('value') if isinstance(raw.get('value'),dict) else None
        value=d['value_typed'].get('value') if isinstance(d.get('value_typed'),dict) else None
        unit=d['coordinate_units'].get('target') if isinstance(d.get('coordinate_units'),dict) else None
        if d.get('main_state')!='ready' or not unit or not isinstance(raw_value,(str,int,float)) or not isinstance(value,(str,int,float)):continue
        item={'property_id':(raw.get('property_ref') or {}).get('id'),'before':str(raw_value),'before_unit':raw.get('unit'),'after':str(value),'after_unit':unit}
        changed=item['before']!=item['after'] or item['before_unit']!=unit
        if not change_example or changed:change_example=item
        if changed:break
    received={e['payload'].get('review_id') for e in events if e['kind']=='answer_received'}
    applied={r.get('review_id') for r in receipts}
    reviews=[]
    if tid!=task_id:reviews_data=task['_captured_reviews']
    for r in (reviews_data if reviews_data is not None else application.reviews.list(conn,tid)):
        if r.get('created_at','')>cutoff:continue
        if not current and r['review_id'] not in reviewed_ids:continue
        answer=r.get('answer')
        if answer and answer.get('received_at','')>cutoff:answer=None
        missing_revision=not current and revisions.get(r['review_id'],1)!=r.get('revision',1)
        if missing_revision:
            # The mutable question table cannot reconstruct an old wording.
            # Keep historical answers that actually existed, never borrow
            # the later question, choices, or changed evidence scope.
            answer=next((a for a in reversed(get('review_answer')) if a.get('review_id')==r['review_id']),None)
        review_event=next((e for e in reversed(events) if e['kind']=='review_ready' and e['payload'].get('review_id')==r['review_id']),None)
        reviews.append({'review_id':r.get('review_id'),'question':r.get('question'),'created_at':r.get('created_at'),
            'task_id':task_id,'revision':r.get('revision'),'basis_hash':r.get('basis_hash'),
            'seq':review_event['seq'] if review_event else None,
            'allowed_actions':[] if missing_revision else r.get('allowed_actions',[]),
            'issue_kind':r.get('issue_kind'),'basis':{} if missing_revision else r.get('basis',{}),
            'scope':{} if missing_revision else r.get('scope',{}),
            'correction_types':[] if missing_revision else r.get('correction_types',[]),
            'evidence_refs':[] if missing_revision else r.get('evidence_refs',[]),
            'current_interpretation':None if missing_revision else r.get('current_interpretation'),
            'approved_conditions':[] if missing_revision else r.get('approved_conditions',[]),
            'scientific_issue':None if missing_revision else r.get('scientific_issue'),
            'record_interpretations':{} if missing_revision else r.get('record_interpretations',{}),
            **({'question':'审核问题曾修订；此时点的完整题干未保存。','impact':'仅展示当时已保存的原回答，不借用后来的解释。'} if missing_revision else {'impact':r.get('impact')}),
            'answer':answer if current or r['review_id'] in received else None,'choices':[] if missing_revision else r.get('choices',[]),
            'evidence':[] if missing_revision else [review_evidence(repo,conn,tid,ref,cutoff) for ref in r.get('evidence_refs',[])],
            'status':r.get('status') if current else 'closed_unanswered' if r['review_id'] in withdrawn else 'applied' if r['review_id'] in applied else 'accepted' if r['review_id'] in received else 'pending'})
    # All numerators and denominators use jobs already visible at this cursor.
    chat_progress={
        'catalog':progress('张表','catalog_extract'),
        'attachments':progress('篇论文','attachment_discover'),
        'tables':progress('张表','catalog_extract','attachment_extract'),
        'papers':progress('批','paper_batch'),
        'figures':progress('篇论文','paper_figures'),
        'verify':progress('批','quality_verify'),
        'reextract':progress('批','quality_reextract'),
        'normalize':progress('条记录','normalize'),
        'compare':progress('项性质','compare_results'),
    }
    sealed=None
    header_only=False
    if delivery_ref:
        if conn.execute("SELECT 1 FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                        (tid,delivery_ref['id'],delivery_ref['version'])).fetchone():
            try:
                sealed=application.delivery.read_header(conn,task_id,delivery_ref['id'],delivery_ref['version'],as_of=cutoff)
                header_only=True
            except DomainError as error:
                if error.code != 'RESULT_NOT_READY':
                    raise
                # A visible, captured delivery_ready event can precede the
                # mutable task pointer. Only this already bounded history read
                # uses its exact saved object; public delivery APIs stay strict.
                sealed=application.delivery.read_snapshot(conn,tid,delivery_ref['id'],delivery_ref['version'])
    summary=None
    if sealed:
        task_score=sealed.get('task_score') or {}
        insight_report=sealed.get('insight_report') or {}
        material_report=(insight_report.get('material_report') or {}) if insight_report.get('schema_version') == 'InsightBundle/1' else insight_report
        overview=(sealed['material_overview'] if header_only else
                  application.delivery.material_overview(conn,tid,sealed,as_of=cutoff))
        summary={'delivery_ref':delivery_ref,'snapshot_ref':sealed.get('snapshot_ref'),
            'records':sealed['display_counts']['records'] if header_only else len(sealed.get('measurements',[])),
            'sources':sealed['display_counts']['sources'] if header_only else len(sealed.get('sources',[])),
            'materials':overview['total'],'material_overview':overview,
            'figures':sealed['display_counts']['figures'] if header_only else len(sealed.get('figures',[])),
            'properties':sealed['definition_count'] if header_only else len(sealed.get('definitions',[])),
            'insights':len(insight_report.get('qualified_property_ids',[])),
            **({'material_summaries':sum(c.get('ready', 0) for c in material_report.get('counts', {}).values())}
               if material_report.get('schema_version') == 'MaterialSummaryReport/1'
               and material_report.get('status') != 'pending' else {}),
            'score':task_score.get('score'),'score_state':task_score.get('status'),
            'report_state':sealed.get('report_state'),'coverage_state':sealed.get('status'),
            'components':[{k:item.get(k) for k in ('key','weight','earned','state')} for item in task_score.get('components',[])],
            'comparison_checked':sealed['comparison_checked'] if header_only else
                sum(x.get('state')=='checked' for x in sealed.get('comparison_checks',[]))}
    activity=None
    if include_chat_activity:
        from .chat_activity import project
        activity=project(get,visible_jobs,events,cursor=cursor,limit=max(1,min(20,activity_limit)))
    messages=[]
    for row in conn.execute("SELECT object_id,payload FROM objects WHERE task_id=? AND kind='message' AND created_at<=? ORDER BY created_at,object_id",(tid,cutoff)):
        message=loads(row['payload'])
        message['message_id']=row['object_id']
        message['seq']=next((e['seq'] for e in events if e['committed_at']>=message.get('created_at',cutoff)),cursor)
        messages.append(message)
    return {'schema_version':'TaskPresentation/1','task_id':task_id,'source_task_id':tid,'kind':task['kind'],'cursor':cursor,
        'at':cutoff,'latest_cursor':task['last_event_seq'],'historical':not current,'lifecycle':lifecycle,
        'legacy_available':task['kind']=='legacy' and any(e['kind']=='legacy_imported' for e in events),
        'target':spec.get('target') or draft.get('target'),'properties':[
            {'property_id':b['property_id'],'name':b['definition']['name_cn'],
             'unit':(b.get('output_profile') or {}).get('unit',{}).get('canonical_symbol')} for b in bindings],
        'chat_progress':chat_progress,
        'clean_example':change_example,
        'comparison_by_property':{x['property_id']:{'state':x.get('state'),'groups':len(x.get('duplicates',[])),'differences':len(x.get('suspicions',[]))} for x in checks if x.get('property_id')},
        'records_per_property':dict(Counter(r['property_ref']['id'] for r in records if r.get('property_ref'))),
        'insight_properties':{e['payload']['property_id']:e['payload']['status'] for e in events
                              if e['kind']=='insight_unit_updated' and e['payload'].get('property_id')},
        'stages':stages,'active_stage':active,'materials':material,'material_revision':(get('material_preparation') or [{}])[-1].get('revision'),
        'material_summary_mode':material_summary,
        'unique_readable':len({w for p in pools.values() for w in p.get('acquired',[])}) if pools else None,
        'delivery_ref':delivery_ref,'insight_ref':({'id':get('insight')[-1]['report_id'],'version':1} if get('insight') and delivery_ref else None),
        'reviews':reviews,'review_receipts':receipts,'delivery_summary':summary,
        'review_events':[{'review_id':e['payload']['review_id'],'revision':e['payload'].get('revision',1),'seq':e['seq'],'at':e['committed_at']}
            for e in events if e['kind']=='review_ready'],
        **({'chat_activity':activity} if include_chat_activity else {}),
        'request':{'original_query':draft.get('original_query') or spec.get('original_query'),
            'requests':draft.get('property_requests',[]),'selection':draft.get('model_property_selection'),
            'issues':draft.get('issues',[]),'bindings':bindings,'confirmed':bool(spec),
            'preview':(draft.get('pending_question') or {}).get('preview')},
        'draft_question':({'title':draft['pending_question']['title'],'kind':draft['pending_question']['kind'],
                           'options':[{'id':b['property_id'],'name':b['definition']['name_cn']}
                                      for b in ((draft['pending_question'].get('property_catalog') or {}).get('bindings') or [])]}
            if draft.get('pending_question') else None),
        'milestones':milestones,'messages':messages,'counts':{'records':len(records),'sources':len(sources),'figures':figure_count},
        'wall_seconds':seconds(task['created_at'],wall_end) if task['kind']!='legacy' else None,
        'created_at':task['created_at'],'terminal_at':terminal_at,
        'terminal_seq':next((e['seq'] for e in reversed(events) if e['kind']=='task_state_changed' and e['payload'].get('lifecycle') in TERMINAL),None),
        'human_wait_seconds':sum(seconds(w['start'],w['end']) or 0 for w in human_wait) if human_wait else None,
        'limitations':['仅展示此时点已保存的事实；未记录的细节不补写。']}

def execution(application,task_id,at_seq=None,stage_id=None,category=None,offset=0,limit=100):
    # Compatibility shape. New clients use independently paginated sections.
    from .execution_view import project, page
    data=project(application,task_id,at_seq)
    rows=data['events']
    issues=[{**i,'category':i['recovery'],'reason':i['message'],'level':'error',
             'operation':i.get('name'),'object_id':next(iter(i['links'].values()),None)}
            for i in data['issues'] if i.get('job_id')]
    if stage_id:
        issues=[i for i in issues if i['stage_id']==stage_id]
        rows=[e for e in rows if e['stage_id']==stage_id]
    if category:issues=[i for i in issues if i['category']==category]
    p=presentation(application,task_id,data['cursor'])
    logs=[{**e,'text':e['label']} for e in page(rows,offset,limit)['items']]
    return {'schema_version':'TaskExecutionView/1','cursor':data['cursor'],
        'wall_seconds':data['wall_seconds'],'human_wait_seconds':data['human_wait_seconds'],
        'created_at':data['created_at'],'terminal_at':data['terminal_at'],
        'stages':p['stages'],'milestones':p['milestones'],'timeline':rows,
        'logs':logs,'log_total':len(rows),'issues':page(issues,offset,limit)['items'],
        'issue_total':len(issues),'log_notice':'公开执行摘要；按事件游标读取。'}
