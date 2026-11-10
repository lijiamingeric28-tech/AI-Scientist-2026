"""Normal M11 job: property-wide explanation, local repair, source recheck.

The repository/checkpoint gateway owns execution and resumes. No new scheduler,
retrieval path, scientific score or measurement storage is introduced here.
"""
import asyncio
from copy import deepcopy

from astroquery_ai.runtime.calls import input_upper_bound
from astroquery_ai.runtime.codec import canonical, digest, loads
from astroquery_ai.runtime.errors import DomainError
from . import property_insights as cards
from . import author_insights as author
from .insight_inputs import explanation_wire
from .insight_recheck import recheck, STOP


def checkpoint(repo, conn, tid, key, body):
    old = conn.execute("SELECT version,payload FROM objects WHERE task_id=? AND kind='property_insight_checkpoint' AND object_id=? ORDER BY version DESC LIMIT 1", (tid,key)).fetchone()
    if old and canonical(loads(old['payload'])) == canonical(body): return
    repo.put_object(conn,tid,'property_insight_checkpoint',key,(old['version']+1) if old else 1,body)


def plan(current, delivery, spec):
    """Initial capacity grouping by source, not first-N sampling or retries."""
    packed, bindings = cards.model_input(current, delivery, spec)
    if input_upper_bound([{'role':'user','content':canonical(packed).decode()}]) <= cards.INPUT_LIMIT:
        return [{'unit':current,'input':packed,'bindings':bindings}], False
    by_source = {}
    for row in current['measurements']:
        by_source.setdefault(row['source']['source_id'],[]).append(row)
    groups=[];pending=[];pieces=[]
    for source_rows in by_source.values():
        source_unit=author.unit(delivery,current['property_id'],source_rows,current['claims'])
        source_body,_=cards.model_input(source_unit,delivery,spec)
        if input_upper_bound([{'role':'user','content':canonical(source_body).decode()}])<=cards.INPUT_LIMIT:
            pieces.append(source_rows);continue
        # Only an initially oversized source is grouped more finely. Each row
        # retains its complete original/header/context and independent errors.
        chunk=[]
        for row in source_rows:
            trial=author.unit(delivery,current['property_id'],[*chunk,row],current['claims'])
            trial_body,_=cards.model_input(trial,delivery,spec)
            if chunk and input_upper_bound([{'role':'user','content':canonical(trial_body).decode()}])>cards.INPUT_LIMIT:
                pieces.append(chunk);chunk=[]
            chunk.append(row)
        if chunk:pieces.append(chunk)
    # A complete record/error/context never gets trimmed to fit. If one record
    # is itself too large, its failure remains explicit in batch coverage.
    for source_rows in pieces:
        trial=author.unit(delivery,current['property_id'],[*pending,*source_rows],current['claims'])
        body,wire=cards.model_input(trial,delivery,spec)
        if pending and input_upper_bound([{'role':'user','content':canonical(body).decode()}])>cards.INPUT_LIMIT:
            unit=author.unit(delivery,current['property_id'],pending,current['claims'])
            body,wire=cards.model_input(unit,delivery,spec);groups.append({'unit':unit,'input':body,'bindings':wire})
            pending=[]
        pending.extend(source_rows)
    if pending:
        unit=author.unit(delivery,current['property_id'],pending,current['claims'])
        body,wire=cards.model_input(unit,delivery,spec);groups.append({'unit':unit,'input':body,'bindings':wire})
    return groups, True


def synthesis_input(current, delivery, spec, batch_cards, batch_coverage=()):
    body=cards.prompt(current,delivery,spec)
    body['original_materials']=[{k:v for k,v in e.items() if k!='raw_text'} for e in body['original_materials']]
    body['batch_notes']=[{'measurement_ids':b['measurement_ids'],'sections':b['sections'],
                         'findings':b['findings'],'field_states':b['field_states'],
                         'recommendations':b.get('recommendations',{})} for b in batch_cards]
    body['batch_coverage']=deepcopy(list(batch_coverage))
    body['instruction'] += (' 这是按来源上下文读完后的性质综合。使用全量简明科学行和已验证引用的批内短条目，'
        '只合成一张卡，不重复批次开头。原文已由各批读取，本次只保留位置索引，不把大原文拼回来。'
        '不要把引用存在当科学结论获证，不能新增批内和知识都没有支持的断言。')
    _,bindings=cards.model_input(current,delivery,spec)
    return cards.pack_materials(explanation_wire(body,bindings)),bindings


async def explain(service,job,current,delivery,spec,packed,bindings,*,key):
    repo=service.repo;tid=job['task_id']
    signature=digest([cards.PROTOCOL,packed,delivery['snapshot_ref']])
    with repo.read() as conn:
        saved=[p for p in repo.objects(conn,tid,'property_insight_checkpoint') if p.get('key')==key]
    if saved:
        if saved[0]['input_hash']!=signature:raise DomainError('INSIGHT_PLAN_CHANGED','恢复输入与已有检查点不同')
        return saved[0]
    state={'key':key,'input_hash':signature,'property_id':current['property_id'],
           'measurement_ids':[r['measurement_id'] for r in current['measurements']],
           'snapshot_ref':delivery['snapshot_ref'],'actual_model':None,'actual_attempt_ref':None}
    if not current['measurements']:
        state.update(status='not_applicable',reason='no_frozen_records')
        with repo.transaction() as conn:
            repo.validate_lease(conn,job,scientific=False);checkpoint(repo,conn,tid,key,state)
        return state
    messages=[{'role':'user','content':canonical(packed).decode()}]
    try:
        if input_upper_bound(messages)>cards.INPUT_LIMIT:
            raise DomainError('INSIGHT_INPUT_CAPACITY','完整来源上下文超过本次已验证输入范围')
        response,receipt=await service.steps.model(job,task_id=tid,owner='M11',root_id=key+':primary',
            messages=messages,bindings=bindings,
            profile=service.model_profile('M11','qwen3.8-max',version=cards.PROTOCOL,
                max_input_tokens=cards.INPUT_LIMIT,max_output_tokens=cards.OUTPUT_LIMIT,
                max_images=0,wall_seconds=240,inactivity_seconds=90),job=job,purpose='production',root_limit=2)
        state.update(raw_response=response,actual_model=receipt['model'],actual_attempt_ref=receipt['attempt_id'])
        state['card']=cards.validate_reply(response,current,bindings)
        # One local repair only. It receives the bad entries and necessary
        # existing material, never another complete-property paid pass.
        if state['card']['validation_issues']:
            local,slots=cards.repair_input(response,state['card'],current,delivery,spec,bindings)
            local_messages=[{'role':'user','content':canonical(local).decode()}]
            if input_upper_bound(local_messages)<=cards.INPUT_LIMIT:
                try:
                    fixed,local_receipt=await service.steps.model(job,task_id=tid,owner='M11',root_id=key+':local',
                        messages=local_messages,bindings=bindings,
                        profile=service.model_profile('M11','qwen3.8-max',version=cards.PROTOCOL,
                            max_input_tokens=cards.INPUT_LIMIT,max_output_tokens=cards.OUTPUT_LIMIT,
                            max_images=0,wall_seconds=240,inactivity_seconds=90),job=job,purpose='production',root_limit=1)
                    updated,card=cards.apply_repairs(response,fixed,slots,current,bindings)
                    state.update(card=card,local_repair={'attempt_ref':local_receipt['attempt_id'],
                        'initial_issues':state['card']['validation_issues'],'response':fixed},repaired_response=updated)
                except DomainError as exc:
                    if exc.code in STOP:raise
                    state['local_repair']={'state':'not_completed','reason':exc.code}
            else:state['local_repair']={'state':'not_completed','reason':'local_material_exceeds_validated_capacity'}
        state['status']='generated' if state['card']['sections']['found'] else 'partial'
    except DomainError as exc:
        if exc.code in STOP:raise
        state.update(status='not_completed',reason=exc.code,details=exc.details)
    with repo.transaction() as conn:
        repo.validate_lease(conn,job,scientific=False)
        checkpoint(repo,conn,tid,key,state)
        repo.event(conn,tid,'insight_unit_updated',{'unit_id':current['unit_id'],
            'property_id':current['property_id'],'status':state['status']})
    return state


async def generate(service,job):
    tid=job['task_id'];repo=service.repo
    with repo.read() as conn:
        delivery=service.app.delivery.get(conn,tid,job['payload']['delivery_id'])
        task=repo.task(conn,tid);q=loads(task['query_ref'])
        spec=repo.object(conn,tid,'confirmed_query',q['id'],q['version'])
    reference=spec.get('knowledge_release')
    if not reference:raise DomainError('INSIGHT_KB_PIN_MISSING','性质解释未绑定准确知识版本')
    release=service.app.knowledge.load(reference)
    if 'author' not in release:raise DomainError('INSIGHT_AUTHOR_RELEASE_REQUIRED','不能回退旧模板库')
    units=cards.property_units(delivery,spec,release)
    plan_body={'protocol':cards.PROTOCOL,'snapshot_ref':delivery['snapshot_ref'],'knowledge_ref':reference,
        'units':[{'unit_id':u['unit_id'],'property_id':u['property_id'],'claims':u['claims'],
                  'measurement_ids':[m['measurement_id'] for m in u['measurements']]} for u in units]}
    with repo.transaction() as conn:
        repo.validate_lease(conn,job,scientific=False)
        existing=repo.objects(conn,tid,'property_insight_plan')
        if existing and existing[0]!=plan_body:raise DomainError('INSIGHT_PLAN_CHANGED','性质解释计划与冻结输入不一致')
        if not existing:repo.put_object(conn,tid,'property_insight_plan',delivery['delivery_id'],1,plan_body)
    checkpoints={};semaphore=asyncio.Semaphore(2)
    async def one(current):
        async with semaphore:
            groups,needs_synthesis=plan(current,delivery,spec)
            if not needs_synthesis:
                result=await explain(service,job,current,delivery,spec,groups[0]['input'],groups[0]['bindings'],key=current['unit_id'])
            else:
                batch_results=[]
                for group in groups:
                    batch_results.append(await explain(service,job,group['unit'],delivery,spec,
                        group['input'],group['bindings'],key=current['unit_id']+':batch:'+group['unit']['unit_id']))
                valid=[r['card'] for r in batch_results if r.get('card')]
                batch_coverage=[{k:r[k] for k in ('key','measurement_ids','status')} for r in batch_results]
                packed,bindings=synthesis_input(current,delivery,spec,valid,batch_coverage)
                result=await explain(service,job,current,delivery,spec,packed,bindings,key=current['unit_id'])
                result['batch_coverage']=batch_coverage
                with repo.transaction() as conn:
                    repo.validate_lease(conn,job,scientific=False);checkpoint(repo,conn,tid,current['unit_id'],result)
            checkpoints[current['unit_id']]=result
    from astroquery_ai.runtime.async_scope import gather_scoped
    await gather_scoped(*(one(u) for u in units))
    with repo.read() as conn:
        repo.validate_lease(conn,job,scientific=False)
        if repo.task(conn,tid)['lifecycle'] not in {'running','queued'}:
            raise DomainError('DISPATCH_FORBIDDEN','洞察已暂停，保留检查点并等待恢复')
    findings=[f for r in checkpoints.values() for f in r.get('card',{}).get('findings',[])]
    owner_rechecks=await recheck(service,job,delivery,spec,findings)
    with repo.transaction() as conn:
        repo.validate_lease(conn,job,scientific=False)
        if repo.task(conn,tid)['lifecycle'] not in {'running','queued'}:
            raise DomainError('DISPATCH_FORBIDDEN','等待恢复后再发布，不把暂停变为完成')
        count=conn.execute("SELECT count(*) FROM attempts WHERE task_id=? AND owner='M11' AND status<>'not_dispatched'",(tid,)).fetchone()[0]
        report=cards.final_report(delivery,spec,reference,units,checkpoints,owner_rechecks=owner_rechecks,calls=count)
        repo.finish_job(conn,job)
        service.app.delivery.finish_insights(conn,tid,report)


def unfinished_report(repo,conn,tid,delivery,spec,reason):
    # No new model calls or library load on failure/cancel. Reconstruct only
    # available cards; all data remain in their original science snapshot.
    from .insight_inputs import measurement_input
    plans=repo.objects(conn,tid,'property_insight_plan')
    checkpoints={p['key']:p for p in repo.objects(conn,tid,'property_insight_checkpoint')}
    units=[]
    for binding in spec['properties']:
        own=[measurement_input(delivery,r) for r in delivery['measurements'] if r['property_ref']['id']==binding['property_id']]
        plan_unit=next((u for p in plans for u in p['units'] if u['property_id']==binding['property_id']),None)
        unit=author.unit(delivery,binding['property_id'],own,plan_unit.get('claims',[]) if plan_unit else [])
        if plan_unit:unit['unit_id']=plan_unit['unit_id']
        units.append(unit)
    checks=[d for c in repo.objects(conn,tid,'insight_owner_recheck_checkpoint') for d in c['dispositions']]
    count=conn.execute("SELECT count(*) FROM attempts WHERE task_id=? AND owner='M11' AND status<>'not_dispatched'",(tid,)).fetchone()[0]
    report=cards.final_report(delivery,spec,spec.get('knowledge_release'),units,checkpoints,owner_rechecks=checks,calls=count)
    report.update(status='partial',reason=reason)
    return report
