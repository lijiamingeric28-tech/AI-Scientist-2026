"""Dot author-format inspection and exact binding; never scientific approval."""
from pathlib import Path
from urllib.parse import urlparse
from astroquery_ai.runtime.codec import digest,loads
from astroquery_ai.runtime.errors import DomainError


def _rows(path):
    return [loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def inspect_author_package(directory,inventory,*,registry_ref,expected_registry_ref,partial=False):
    directory=Path(directory).resolve()
    if registry_ref!=expected_registry_ref:raise DomainError('AUTHOR_REGISTRY_VERSION','写作库存对应的科学库版本不匹配')
    data={name:_rows(directory/(name+'.jsonl')) for name in ('entries','sources','coverage')}
    fields={'entries':{'entry_id','title','otypes','property_topics','conditions','blocks'},
        'sources':{'source_id','title','url','verification','locator','support_note'},
        'coverage':{'item_id','otype','property_id','entry_ids','status','reason'}}
    indices={}
    for name,rows in data.items():
        key={'entries':'entry_id','sources':'source_id','coverage':'item_id'}[name];index={}
        for row in rows:
            if not isinstance(row,dict) or fields[name]-row.keys() or not isinstance(row[key],str) or not row[key] or row[key] in index:
                raise DomainError('AUTHOR_PACKAGE_SCHEMA','作者包缺字段或存在重复身份',file=name)
            index[row[key]]=row
        indices[name]=index
    for source in data['sources']:
        if source['verification'] not in {'read_this_task','reused_existing_evidence','reference_only'} or urlparse(source['url']).scheme not in {'http','https'}:
            raise DomainError('AUTHOR_SOURCE_SCHEMA','知识来源标签或URL格式不正确')
        if source['verification']!='reference_only' and (not source['locator'] or not source['support_note']):
            raise DomainError('AUTHOR_SOURCE_SUPPORT','已核读来源必须保留位置和支持说明')
    for entry in data['entries']:
        if any(not isinstance(entry[k],list) for k in ('otypes','property_topics','conditions','blocks')) or not entry['blocks']:
            raise DomainError('AUTHOR_ENTRY_SCHEMA','知识卡数组或正文不完整')
        for block in entry['blocks']:
            if (set(block)!={'role','text','basis','source_ids'} or block['role'] not in
                {'meaning','method','interpretation','uncertainty','limitation','relationship'} or
                block['basis'] not in {'author_knowledge','source_checked'} or not isinstance(block['text'],str) or not block['text'].strip() or
                not isinstance(block['source_ids'],list) or set(block['source_ids'])-indices['sources'].keys()):
                raise DomainError('AUTHOR_BLOCK_SCHEMA','知识段落、角色或来源引用不正确')
            if block['basis']=='source_checked' and (not block['source_ids'] or any(
                indices['sources'][sid]['verification']=='reference_only' for sid in block['source_ids'])):
                raise DomainError('AUTHOR_UNCHECKED_SOURCE','进一步阅读不能冒充已核读依据')
    by_item={i['item_id']:i for i in inventory};bindings=[]
    if len(by_item)!=len(inventory):raise DomainError('AUTHOR_INVENTORY_DUPLICATE','写作库存身份重复')
    for row in data['coverage']:
        item=by_item.get(row['item_id'])
        if not item or any(row[k]!=item[k] for k in ('otype','property_id')):
            raise DomainError('AUTHOR_INVENTORY_BINDING','作者覆盖未绑定准确库存项')
        if row['status'] not in {'covered','partial','missing'} or not isinstance(row['entry_ids'],list) or set(row['entry_ids'])-indices['entries'].keys():
            raise DomainError('AUTHOR_COVERAGE_SCHEMA','覆盖状态或知识卡引用错误')
        if row['status']=='missing' and (row['entry_ids'] or not row['reason']) or row['status']!='missing' and not row['entry_ids']:
            raise DomainError('AUTHOR_COVERAGE_SCHEMA','缺口与实质解释状态不一致')
        if any(row['otype'] not in indices['entries'][eid]['otypes'] for eid in row['entry_ids']):
            raise DomainError('AUTHOR_OTYPE_BINDING','知识卡没有声明适用该具体类型')
        bindings.append({**row,'definition_ref':item['definition_ref'],'output_profile_ref':item['output_profile_ref'],
            'applicability_rule_refs':item.get('applicability_rule_refs',[]),'item_hash':digest(item)})
    if not partial and indices['coverage'].keys()!=by_item.keys():raise DomainError('AUTHOR_COVERAGE_INCOMPLETE','完整作者包须逐项记录覆盖或缺口')
    return {'schema_version':'DotAuthorPackageInspection/1','registry_ref':registry_ref,'entries':data['entries'],
        'sources':data['sources'],'bindings':bindings,'missing_inventory_items':sorted(by_item.keys()-indices['coverage'].keys()),
        'content_hash':digest(data),'inventory_hash':digest(inventory),'runtime_authorized':False,
        'scientific_review_claimed':False,'partial':partial,'format':'dot-insight-authoring-input/1'}


def verified_types(spec):
    target=spec['target'];types={target['primary_otype']} if '?' not in target['primary_otype'] else set()
    for a in target.get('classification_assertions',[]):
        subject=a.get('subject_identity_ref');subject=subject.get('id') if isinstance(subject,dict) else subject
        if a.get('state')=='current_verified' and subject==target['target_id'] and a.get('evidence_refs') and a.get('canonical_otype'):
            types.add(a['canonical_otype'])
    return types


def assemble_insight_input(delivery,package,*,spec=None):
    """Exact candidate assembly; semantic card selection belongs to M11.

    spec=None is the historical inspection-only interface. New runtime calls
    always supply the frozen task and enforce concrete type/active rules.
    """
    props={b['property_id']:b for b in delivery['definitions']};knowledge=[];inapplicable=[]
    for binding in package['bindings']:
        selected=props.get(binding['property_id'])
        if selected is None:continue
        definition=selected['definition'];profile=selected['output_profile']
        expected={'id':definition['property_id'],'version':str(definition.get('definition_version',definition.get('version'))),'content_sha256':definition['content_sha256']}
        actual={k:str(v) if k=='version' else v for k,v in binding['definition_ref'].items() if k in expected}
        expected_profile={'id':profile['profile_id'],'version':str(profile['version']),'content_sha256':profile['content_sha256']}
        projection=selected.get('candidate_projection_receipt')
        if projection:
            if projection['definition_view_hash']!=definition['content_sha256'] or projection['profile_view_hash']!=profile['content_sha256']:
                raise DomainError('AUTHOR_PROJECTION_CHANGED','冻结消费视图与原定义映射不符')
            expected={k:str(v) if k=='version' else v for k,v in projection['source_definition_ref'].items()}
            expected_profile={k:str(v) if k=='version' else v for k,v in projection['source_profile_ref'].items()}
        actual_profile={k:str(v) if k=='version' else v for k,v in binding['output_profile_ref'].items() if k in expected_profile}
        if actual!=expected or actual_profile!=expected_profile:
            inapplicable.append({'item_id':binding['item_id'],'reason':'different_exact_definition_or_profile_version'})
            continue
        if spec is not None:
            if binding['otype'] not in verified_types(spec):
                inapplicable.append({'item_id':binding['item_id'],'reason':'different_verified_otype'});continue
            key=lambda r:(r['id'],str(r['version']),r['content_sha256'])
            established={key(r) for r in selected.get('rule_refs',[])}
            if not {key(r) for r in binding['applicability_rule_refs']}.intersection(established):
                inapplicable.append({'item_id':binding['item_id'],'reason':'applicability_rule_not_established'});continue
        knowledge.append({**binding,'cards':[e for e in package['entries'] if e['entry_id'] in binding['entry_ids']]})
    return {'schema_version':'FactsAndAuthorKnowledge/1','snapshot_ref':delivery['snapshot_ref'],
        'facts':{'measurements':delivery['measurements'],'derived':delivery['derived'],'contexts':delivery['contexts'],
            'evidence':delivery['evidence_index']},'knowledge_candidates':knowledge,'sources':package['sources'],
            'inapplicable_bindings':inapplicable,
            'generation_enabled':False,'selection_rule':'Use model semantic selection on exact-bound cards with actual facts; '
            'unknown conditions allow only conditional background, never claim the task source used that method. '
            'No fixed top-three, invented measurements, best-value ranking or knowledge condition rulebook.'}


def disabled_report(delivery):
    return {'schema_version':'InsightReport/2','report_id':'insight-'+delivery['delivery_id'],
        'delivery_id':delivery['delivery_id'],'snapshot_ref':delivery['snapshot_ref'],'status':'disabled_pending_content',
        'reason':'新洞察待知识内容接入，本轮未启用','units':[],'paragraphs':[],'facts':[],'theory':[],
        'model_calls':0,'generation_enabled':False,'complete_data_preserved':True,
        'author_interface':'dot-insight-authoring-input/1','knowledge_release_ref':None}
