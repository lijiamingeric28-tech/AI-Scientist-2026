"""Versioned consumer amendments; originals and their review grades stay intact."""
from copy import deepcopy

from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.errors import DomainError


def reference_key(ref):
    return digest({'id':ref['id'],'version':str(ref['version']),'content_sha256':ref['content_sha256']})


def validate_amendment(amendment):
    if (amendment.get('schema_version') != 'ConsumerScienceAmendment/1'
            or amendment.get('authorized_by') != 'user'
            or content_hash(amendment) != amendment.get('content_sha256')
            or not amendment.get('decision_text') or type(amendment.get('revision',1)) is not int
            or amendment.get('revision',1)<1):
        raise DomainError('SCIENCE_AMENDMENT_INVALID','科学修订缺少准确版本或用户决定',422)


def checked_reference_alignments(package, candidate, amendment):
    """Review-metadata-only reference repair; original objects stay immutable.

    Both source versions, their exact files and the new independent approval
    must be present. This cannot grant a mathematical/scientific permission.
    """
    if amendment is None:return {}
    validate_amendment(amendment)
    from hashlib import sha256
    from .candidate import local_file,load_record
    indexed={r['path']:r['file_sha256'] for r in candidate['manifest']['content_files']}
    outputs={reference_key({'id':p['profile_id'],'version':p['version'],'content_sha256':p['content_sha256']}):p
             for p in candidate['data']['output_profiles']}
    aliases={}
    for entry in amendment.get('reference_alignments',[]):
        old,new=entry['old_ref'],entry['new_ref']
        if old['id']!=new['id'] or str(old['version'])!=str(new['version']) or old['content_sha256']==new['content_sha256']:
            raise DomainError('REFERENCE_ALIGNMENT_SCOPE','引用修订只允许同ID版本的审核元数据对齐',422)
        records=[]
        for name,ref in (('old_record_pin',old),('new_record_pin',new)):
            pin=entry[name];path=local_file(package,pin['path'])
            if indexed.get(pin['path'])!=pin['file_sha256'] or sha256(path.read_bytes()).hexdigest()!=pin['file_sha256']:
                raise DomainError('REFERENCE_ALIGNMENT_PIN','引用修订原件不在准确包清单中',422)
            value=load_record(path);value=value if isinstance(value,list) else [value]
            selected=[r for r in value if r.get('profile_id')==ref['id'] and str(r.get('version'))==str(ref['version'])
                      and r.get('content_sha256')==ref['content_sha256']]
            if len(selected)!=1 or content_hash(selected[0])!=ref['content_sha256']:
                raise DomainError('REFERENCE_ALIGNMENT_RECORD','原配置引用不能唯一核验',422)
            records.append(selected[0])
        scientific=[{k:v for k,v in record.items() if k not in {'review_ref','content_sha256'}} for record in records]
        if scientific[0]!=scientific[1] or reference_key(new) not in outputs:
            raise DomainError('REFERENCE_ALIGNMENT_SCIENCE_CHANGED','引用修订不能改变科学配置或选择未接受对象',422)
        review_ref=records[1].get('review_ref',{})
        approvals=[r for r in candidate['data']['reviews'] if r['review_id']==review_ref.get('review_id')
                   and str(r['version'])==str(review_ref.get('version')) and r.get('candidate_content_hash')==new['content_sha256']
                   and r.get('candidate_ref',{}).get('id')==new['id'] and r.get('decision')=='approved'
                   and content_hash(r)==r.get('content_sha256')]
        if len(approvals)!=1:
            raise DomainError('REFERENCE_ALIGNMENT_APPROVAL','新配置缺少准确独立审核',422)
        key=reference_key(old)
        if key in aliases and aliases[key]!=new:
            raise DomainError('REFERENCE_ALIGNMENT_CONFLICT','同一旧引用存在相互矛盾的修订',422)
        aliases[key]=new
    return aliases


def apply_amendments(science, amendment):
    if amendment is None:
        return science
    validate_amendment(amendment)
    result = deepcopy(science)
    for item in amendment.get('changes',[]):
        record = result['records'].get(item['property_id'])
        if not record or record['content_sha256'] != item['base_science_sha256']:
            raise DomainError('SCIENCE_AMENDMENT_BASE', '科学修订与原条件版本不符', 422)
        contexts = {c['key']: c for c in record['context_contracts']}
        for key, patch in item.get('context_updates', {}).items():
            if key not in contexts or set(patch) - {'on_missing', 'meaning', 'required_scope'}:
                raise DomainError('SCIENCE_AMENDMENT_FIELD', '修订不能隐式扩大操作或来源权限', 422)
            contexts[key].update(patch)
            if contexts[key].get('source_contract'):
                contexts[key]['source_contract'].update(
                    missing_action=contexts[key]['on_missing'], meaning=contexts[key]['meaning'],
                    main_mapping_effect='consumer_amendment_preserves_unknown_without_confirming_identity')
        record['consumer_amendment_ref'] = {'id': amendment['amendment_id'], 'version': amendment.get('revision', 1),
                                            'content_sha256': amendment['content_sha256']}
        record['version'] = int(record['version']) + amendment.get('revision', 1)
        record['content_sha256'] = content_hash(record)
    return result


def amend_view(view, amendment):
    if amendment is None:
        return view
    item = next((c for c in amendment.get('changes',[]) if c['property_id'] == view['property_id']), None)
    if item is None:
        return view
    result = deepcopy(view)
    definition, profile = result['definition'], result['output_profile']
    if definition['content_sha256'] != item['base_definition_sha256']:
        raise DomainError('SCIENCE_AMENDMENT_BASE', '定义修订与投影基线不符', 422)
    definition['definition_version'] += amendment.get('revision', 1)
    definition['description'] = item['definition_description']
    definition['content_sha256'] = content_hash(definition)
    profile['definition_version'] = definition['definition_version']
    profile['version'] += amendment.get('revision', 1)
    profile['content_sha256'] = content_hash(profile)
    result['projection_receipt'].update(consumer_amendment_ref={
        'id': amendment['amendment_id'], 'version': amendment.get('revision', 1), 'content_sha256': amendment['content_sha256']},
        definition_view_hash=definition['content_sha256'], profile_view_hash=profile['content_sha256'])
    return result
