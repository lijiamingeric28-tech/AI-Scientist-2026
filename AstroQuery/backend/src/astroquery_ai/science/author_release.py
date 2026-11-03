"""Installable wrapper for immutable Dot author files; not scientific approval."""
from pathlib import Path
import hashlib
from astroquery_ai.runtime.codec import canonical,content_hash,digest,loads
from astroquery_ai.runtime.errors import DomainError
from .author_knowledge import inspect_author_package

SCHEMA='insight-knowledge/3'
MODE='dot_author/1'
VERSION='insight-integration/2'


def enabled(spec):
    return spec.get('run_policy',{}).get('insights',{}).get('mode')==MODE


def build_release(package_root,destination,registry_ref,*,synthetic=False):
    source=Path(package_root).resolve();destination=Path(destination).resolve()
    inventory=loads((source/'inputs/property-inventory.json').read_bytes())
    inspected=inspect_author_package(source/'output',inventory,registry_ref=registry_ref,expected_registry_ref=registry_ref)
    files=[]
    for name in ('entries.jsonl','sources.jsonl','coverage.jsonl'):
        files.append(('output/'+name,source/'output'/name))
    for name in ('property-inventory.json','type-index.json'):
        files.append(('inputs/'+name,source/'inputs'/name))
    content_files=[{'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for name,path in files]
    manifest={'schema_version':SCHEMA,'release_id':'dot-author-'+digest([registry_ref,content_files])[:24],
        'status':'ready_to_import','registry_release_ref':registry_ref,'content_files':content_files,
        'author_format':'dot-insight-authoring-input/1','counts':{
            'entries':len(inspected['entries']),'blocks':sum(len(e['blocks']) for e in inspected['entries']),
            'sources':len(inspected['sources']),'bindings':len(inspected['bindings']),
            'otypes':len({b['otype'] for b in inspected['bindings']})},
        'synthetic':synthetic,'scientific_review_claimed':False,'author_labels_preserved':True}
    manifest['content_sha256']=content_hash(manifest)
    if destination.exists() and any(destination.iterdir()):
        old=loads((destination/'manifest.json').read_bytes())
        if old!=manifest:raise DomainError('KB_IMMUTABLE_RELEASE','不能覆盖不同作者知识发布')
    destination.mkdir(parents=True,exist_ok=True)
    for name,path in files:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_bytes()!=path.read_bytes():raise DomainError('KB_CONTENT_HASH','既有发布原文改变')
        target.write_bytes(path.read_bytes())
    (destination/'manifest.json').write_bytes(canonical(manifest))
    return manifest


def validate_release(directory,manifest,registry):
    directory=Path(directory).resolve()
    expected={'output/entries.jsonl','output/sources.jsonl','output/coverage.jsonl',
              'inputs/property-inventory.json','inputs/type-index.json'}
    if len(manifest['content_files'])!=len(expected) or {f['path'] for f in manifest['content_files']}!=expected:
        raise DomainError('KB_FILES_MISSING','作者发布必须包含完整正文、来源、覆盖和输入库存')
    for item in manifest['content_files']:
        path=(directory/item['path']).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise DomainError('KB_CONTENT_HASH','作者知识原文hash或路径不符')
    inventory=loads((directory/'inputs/property-inventory.json').read_bytes())
    author=inspect_author_package(directory/'output',inventory,registry_ref=manifest['registry_release_ref'],
                                  expected_registry_ref=manifest['registry_release_ref'])
    # Import all reviewed conditional associations, including those requiring
    # multiple verified types. A singleton runtime projection is NOT the input
    # inventory (e.g. a parent type with conditional physical strata). Actual
    # applicability is enforced again from the frozen task's active rules.
    data=registry['candidate']['data']
    def refkey(r):return (r['id'],str(r['version']),r['content_sha256'])
    definitions={(r['property_id'],str(r['definition_version']),r['content_sha256']) for r in data['definitions']}
    profiles={(r['profile_id'],str(r['version']),r['content_sha256']) for r in data['output_profiles']}
    rules={refkey({'id':r['rule_id'],'version':r['version'],'content_sha256':r['content_sha256']}):r
        for r in data['unapproved_aggregate_composition_and_rules']['rules']}
    types={p['otype']:{refkey(r) for r in p['include_rules']} for p in data['type_profiles']}
    alignments={refkey(a['old_ref']):refkey(a['new_ref'])
        for a in (registry.get('consumer_amendment') or {}).get('reference_alignments',[])}
    for binding in author['bindings']:
        if refkey(binding['definition_ref']) not in definitions or refkey(binding['output_profile_ref']) not in profiles:
            raise DomainError('AUTHOR_EXACT_BINDING','作者库存与审定原定义/输出版本不一致',item_id=binding['item_id'])
        wanted={refkey(r) for r in binding['applicability_rule_refs']}
        if not wanted or not wanted<=rules.keys() or not wanted<=types.get(binding['otype'],set()):
            raise DomainError('AUTHOR_RULE_BINDING','知识类型/适用规则引用不可核验',item_id=binding['item_id'])
        for key in wanted:
            rule=rules[key]
            if (alignments.get(refkey(rule['definition_ref']),refkey(rule['definition_ref']))!=refkey(binding['definition_ref']) or
                alignments.get(refkey(rule['profile_ref']),refkey(rule['profile_ref']))!=refkey(binding['output_profile_ref'])):
                raise DomainError('AUTHOR_RULE_BINDING','适用规则并未指向该准确性质/输出；只能消费既有审定引用修订',item_id=binding['item_id'])
    actual={'entries':len(author['entries']),'blocks':sum(len(e['blocks']) for e in author['entries']),
        'sources':len(author['sources']),'bindings':len(author['bindings']),'otypes':len({b['otype'] for b in author['bindings']})}
    if manifest.get('counts')!=actual:raise DomainError('KB_COVERAGE','知识发布数量清单与完整内容不符')
    return {'manifest':manifest,'author':author,'entries':{e['entry_id']:e for e in author['entries']},
            'sources':{s['source_id']:s for s in author['sources']},'data':{'bindings':author['bindings']}}
