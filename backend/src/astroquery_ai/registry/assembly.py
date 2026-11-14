"""Mechanical assembly of frozen reviewed inputs, retaining their original bytes.

This creates candidate/consumer inputs, never scientific approval or runtime
capabilities. A replacement is selected by an externally pinned file index.
"""
from collections import defaultdict
from copy import deepcopy
import csv
from hashlib import sha256
from pathlib import Path
import shutil
import os

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError
from .candidate import CandidateRegistry, local_file, load_record
from .compiler import condition_variables, matches
from .amendments import reference_key


IDENTITIES = {'definitions': ('property_id', 'definition_version'), 'output_profiles': ('profile_id', 'version'),
              'conversion_policies': ('policy_id', 'version'), 'subject_classes': ('subject_class_id', 'version'),
              'object_scales': ('object_scale_id', 'version'), 'families': ('family_id', 'version'),
              'evidence': ('evidence_id', 'version'), 'reviews': ('review_id', 'version'),
              'type_profiles': ('type_profile_id', 'version'), 'rules': ('rule_id', 'version')}


def finite_support(rules, reference_aliases=None):
    """Shared reduced decision nodes; never enumerate all type combinations.

    Every partition still receives an independent source-AST check at use time.
    Review-only reference alignment is an explicit caller-provided derivation,
    not a scientific preference or name-based property merge.
    """
    reference_aliases = reference_aliases or {}
    grouped = defaultdict(list)
    for r in rules:
        grouped[r['definition_ref']['id'], r['subject_class_id']].append(r)
    tables = []
    for (pid, subject), group in sorted(grouped.items()):
        variables = sorted({v.split(':', 1)[1] for r in group for v in condition_variables(r['when']) if v.startswith('otype:')})
        if any(r['kind'] != 'include' for r in group):
            raise DomainError('ASSEMBLY_RULE_DIALECT', '当前装配不能完整核验此规则组合', 422, property_id=pid)
        nodes, unique, binary_cache, negated = {}, {}, {}, {0:1,1:0}
        variable_index = {name:i for i,name in enumerate(variables)}

        def node(index, low, high):
            if low == high:return low
            key=(index,low,high)
            if key not in unique:
                if len(nodes)>=50000:
                    raise DomainError('ASSEMBLY_SYMBOLIC_SIZE','符号条件超出本次可核验资源范围',422,property_id=pid)
                number=len(nodes)+2;unique[key]=number
                nodes[number]={'id':number,'variable_index':index,'low':low,'high':high}
            return unique[key]

        def combine(op,left,right):
            if left>right:left,right=right,left
            key=(op,left,right)
            if key in binary_cache:return binary_cache[key]
            if op=='and':
                if left==0:return 0
                if left==1:return right
                if left==right:return left
            else:
                if left==0:return right
                if left==1:return 1
                if left==right:return left
            index=min(nodes[left]['variable_index'],nodes[right]['variable_index'])
            a,b=nodes[left],nodes[right]
            low=combine(op,a['low'] if a['variable_index']==index else left,b['low'] if b['variable_index']==index else right)
            high=combine(op,a['high'] if a['variable_index']==index else left,b['high'] if b['variable_index']==index else right)
            result=node(index,low,high);binary_cache[key]=result;return result

        def negate(root):
            if root not in negated:
                current=nodes[root]
                negated[root]=node(current['variable_index'],negate(current['low']),negate(current['high']))
            return negated[root]

        def compile_condition(condition):
            op,value=next(iter(condition.items()))
            if op=='otype':return node(variable_index[value],0,1)
            if op=='subject_class':return int(value==subject)
            if op=='not':return negate(compile_condition(value))
            result=1 if op=='all_of' else 0
            for child in value:result=combine('and' if op=='all_of' else 'or',result,compile_condition(child))
            return result

        profiles, activation = {}, {}
        for rule in group:
            ref=reference_aliases.get(reference_key(rule['profile_ref']),rule['profile_ref'])
            key=digest(ref);profiles[key]=ref
            activation[key]=combine('or',activation.get(key,0),compile_condition(rule['when']))
        states={():1}
        for key,active in sorted(activation.items()):
            following={}
            for choices,root in states.items():
                for selected,branch in ((choices,combine('and',root,negate(active))),
                                        ((*choices,key),combine('and',root,active))):
                    if branch:following[selected]=combine('or',following.get(selected,0),branch)
            states=following
            if len(states)>1024:
                raise DomainError('ASSEMBLY_SYMBOLIC_SIZE','不同输出配置组合超出核验范围',422,property_id=pid)
        partitions=[]
        for selected,root in sorted(states.items()):
            choices=[profiles[key] for key in selected]
            partitions.append({'root':root,'candidate_profile_refs':choices,
                'outcome': 'no_active' if not choices else 'resolved' if len(choices) == 1 else 'conflict',
                'winner_profile_ref': choices[0] if len(choices) == 1 else None})
        tables.append({'property_id': pid, 'subject_class_id': subject, 'variables': variables,
                       'nodes':list(nodes.values()),'partitions':partitions})
    return {'format': 'mechanical-finite-symbolic-support/1', 'tables': tables,
            'runtime_authorized': False, 'scientific_profile_validated': False}


def assemble(base_consumer, batch_root, selection_file, *, selection_sha256, destination,
             reference_amendment=None, reference_amendment_sha256=None):
    base_consumer, batch_root, destination = map(lambda p: Path(p).resolve(), (base_consumer, batch_root, destination))
    index_raw = Path(selection_file).read_bytes()
    if sha256(index_raw).hexdigest() != selection_sha256:
        raise DomainError('ASSEMBLY_SELECTION_PIN', '有效文件索引与外部批准的哈希不符', 422)
    source = base_consumer / 'origin'
    baseline = CandidateRegistry().inspect(source)
    data = deepcopy(baseline['data'])
    collections = {role: list(data.get(role, [])) for role in IDENTITIES}
    collections['rules'] = list(data['unapproved_aggregate_composition_and_rules']['rules'])
    selected = list(csv.DictReader(index_raw.decode('utf-8-sig').splitlines(), delimiter='\t'))
    rows_by_type, science_files = defaultdict(list), []
    for row in selected:
        raw = local_file(batch_root, row['chosen_file']).read_bytes()
        if sha256(raw).hexdigest() != row['sha256']:
            raise DomainError('ASSEMBLY_EFFECTIVE_HASH', '有效替换文件哈希不符', 422, path=row['chosen_file'])
        rows_by_type[row['otype']].append(row)
        name = row.get('role') or Path(row['logical_source_file']).stem.replace('-', '_')
        if name in IDENTITIES:
            objects = load_record(local_file(batch_root, row['chosen_file']))
            if not isinstance(objects, list):
                raise DomainError('ASSEMBLY_COLLECTION', '科学对象输入必须是数组', 422, path=row['chosen_file'])
            collections[name].extend(objects)
        if 'science' in name and 'schema' not in name and (name.startswith('science') or '/science-conditions/' in row['logical_source_file']):
            science_files.append(row)
        elif '/science-conditions/' in row['logical_source_file']:
            science_files.append(row)
    merged = {}
    for role, objects in collections.items():
        identity, version = IDENTITIES[role]
        unique, id_versions = {}, {}
        for obj in objects:
            if obj.get('content_sha256') != content_hash(obj):
                raise DomainError('ASSEMBLY_OBJECT_HASH', '原科学对象哈希不符', 422, role=role, object_id=obj.get(identity))
            key = (obj[identity], str(obj[version]))
            if key in unique and unique[key] != obj:
                raise DomainError('ASSEMBLY_ID_CONFLICT', '同ID版本存在不同原记录，不能覆盖', 422, role=role, object_id=key)
            # Different exact reviewed versions can serve different type scopes.
            # Same-ID/version conflicting payloads are still rejected above.
            unique[key], id_versions[obj[identity]] = obj, key
        merged[role] = [unique[k] for k in sorted(unique)]
    if destination.exists():
        raise DomainError('ASSEMBLY_DESTINATION_EXISTS', '装配输出目录已存在；使用新目录保留旧结果', 409)
    if os.name == 'nt' and not str(destination).startswith('\\\\?\\'):
        destination = Path('\\\\?\\' + str(destination))
    destination.mkdir(parents=True)
    inputs = destination / 'build/selection-inputs'
    inputs.mkdir(parents=True)
    # Retain complete original relative contexts; no author's build scripts run.
    from .consumer import source_files
    for relative in source_files(source, baseline):
        target = inputs / 'psr-source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file(source, relative), target)
    source_prefixes=sorted({r.get('source_prefix','') for r in selected})
    if '' in source_prefixes and len(source_prefixes)>1:
        raise DomainError('ASSEMBLY_SOURCE_ROOTS','不能混合整根复制与分包复制',422)
    for source_prefix in source_prefixes:
        if any(p in {'..','.'} for p in Path(source_prefix).parts) or ':' in source_prefix or '\\' in source_prefix:
            raise DomainError('ASSEMBLY_SOURCE_PATH','输入包根路径不安全',422)
        directory=(batch_root/source_prefix).resolve()
        if not directory.is_dir() or not directory.is_relative_to(batch_root):
            raise DomainError('ASSEMBLY_SOURCE_PATH','输入包根越界或不存在',422)
        io_directory=Path('\\\\?\\'+str(directory)) if os.name=='nt' and not str(directory).startswith('\\\\?\\') else directory
        for original in io_directory.rglob('*'):
            if not original.is_file():continue
            if original.is_symlink() or not original.resolve().is_relative_to(io_directory):
                raise DomainError('ASSEMBLY_SOURCE_PATH', '输入包包含越界文件', 422)
            target=inputs/'dot-source'/source_prefix/original.relative_to(io_directory)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original,target)
    config = loads((base_consumer / 'accepted-science-config.json').read_bytes())
    base_inputs = baseline['manifest']['paths']['build'] + '/selection-inputs/'
    prefix = 'psr-source/' + base_inputs
    original_index = load_record(local_file(source / base_inputs, config['index']['path']))
    from .science_conditions import read_science_conditions
    prior_science=read_science_conditions(source,baseline,base_consumer/'accepted-science-config.json',
        config_sha256=sha256((base_consumer/'accepted-science-config.json').read_bytes()).hexdigest())
    entries=[]
    for entry in original_index['entries']:
        selector=entry.get('record_selector',{})
        types={t for choices in prior_science['variants'].values() for v in choices for o in v['origins']
            if o['record']==entry['record'] and o.get('path_prefix','')==entry.get('path_prefix','')
            and (not selector or (o['record_ref']['id']==selector['id'] and o['record_ref']['content_sha256']==selector['content_sha256']))
            for t in o['accepted_otypes']}
        if not types:raise DomainError('ASSEMBLY_BASE_SCOPE','已接受基线的科学类型作用域不能重建',422)
        entries.append({**entry,'path_prefix':prefix+entry.get('path_prefix',''),'accepted_otypes':sorted(types)})
    schema_relative = 'work/materials/input/registry-dot/schemas/science-conditions.schema.v4.json'
    def pin(relative):
        p = local_file(inputs, relative)
        return {'path': relative, 'file_sha256': sha256(p.read_bytes()).hexdigest()}
    for row in science_files:
        value = load_record(local_file(batch_root, row['chosen_file']))
        records = value if isinstance(value, list) else [value]
        review_files=list(dict.fromkeys(r['chosen_file'] for r in rows_by_type[row['otype']]
            if (r.get('role') or Path(r['logical_source_file']).stem)=='reviews'
            and r.get('source_prefix','')==row.get('source_prefix','')))
        for record in records:
            matched=[]
            for review_file in review_files:
                reviewers=load_record(local_file(batch_root,review_file))
                if any(r.get('candidate_ref',{}).get('id')==record['record_id']
                    and str(r.get('candidate_ref',{}).get('version'))==str(record['version'])
                    and r.get('candidate_content_hash')==record['content_sha256'] for r in reviewers):
                    matched.append(review_file)
            if not matched:
                raise DomainError('ASSEMBLY_SCIENCE_RECEIPT','科学条件未找到准确独立回执',422,record_id=record['record_id'])
            review_file=matched[0]
            entries.append({'review_protocol': 'candidate-review-array/1',
                'record': pin('dot-source/' + row['chosen_file']),
                'record_selector': {'id': record['record_id'], 'version': record['version'], 'content_sha256': record['content_sha256']},
                'independent_receipt': pin('dot-source/' + review_file),
                'accepted_otypes':[row['otype']],
                'schema': pin('dot-source/' + (row.get('schema_file') or schema_relative))})
    # The same shared reviewed condition can occur in multiple type folders.
    entries=list({digest(e):e for e in entries}.values())
    index_path = inputs / 'reviewed-index.json'
    index_path.write_bytes(canonical({'format': 'reviewed-science-conditions-index/1', 'entries': entries}))
    for name in ['validator', 'gate']:
        config[name] = pin(prefix + config[name]['path'])
    config['index'] = pin('reviewed-index.json')
    config['trusted_receipt_hashes'] = sorted({e['independent_receipt']['file_sha256'] for e in entries})
    config['assembly_selection_sha256'] = selection_sha256
    config['accepted_type_union'] = {'policy': 'exact-definition-profile-subject-union/1', 'authorized_by': 'user',
        'decision': '审定规则取并集；同一科学ID必须具有准确相同的定义、输出和主体，冲突不按名称合并'}
    data.update({k: v for k, v in merged.items() if k != 'rules'})
    data['unapproved_aggregate_composition_and_rules'] = {'rules': merged['rules'], 'aggregate_approval_granted': False}
    amendment=base_consumer/'consumer-amendment.json'
    amendment_value=loads(amendment.read_bytes()) if amendment.exists() else None
    if reference_amendment is not None:
        raw=Path(reference_amendment).read_bytes()
        if sha256(raw).hexdigest()!=reference_amendment_sha256:
            raise DomainError('ASSEMBLY_AMENDMENT_PIN','引用修订文件未匹配外部接受的哈希',422)
        amendment_value=loads(raw)
        from .amendments import validate_amendment
        validate_amendment(amendment_value)
    aliases={reference_key(e['old_ref']):e['new_ref'] for e in (amendment_value or {}).get('reference_alignments',[])}
    data['build_only_symbolic_support'] = finite_support(merged['rules'],aliases)
    files = []
    for role, body in sorted(data.items()):
        relative = 'build/data/' + role + '.json'
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical(body))
        files.append({'path': relative, 'role': role})
    manifest = {'package_id': 'reviewed-assembly-' + selection_sha256[:16], 'paths': {'build': 'build'},
                'data_files': files, 'content_files': [], 'runtime_authorized': False,
                'source_selection_sha256': selection_sha256, 'source_baseline_manifest_sha256': baseline['report']['manifest_file_sha256']}
    for p in sorted(destination.rglob('*')):
        if p.is_file():
            raw = p.read_bytes()
            manifest['content_files'].append({'path': p.relative_to(destination).as_posix(), 'file_sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
    manifest['content_sha256'] = content_hash(manifest)
    (destination / 'manifest.json').write_bytes(canonical(manifest))
    manifest_sha = sha256((destination / 'manifest.json').read_bytes()).hexdigest()
    handoff = {'format': 'registry-candidate-handoff/1', 'package_id': manifest['package_id'], 'active': False,
               'ready_to_import': False, 'manifest_path': 'manifest.json', 'manifest_file_sha256': manifest_sha,
               'compiled_support_format': data['build_only_symbolic_support']['format']}
    (destination / 'registry-handoff.json').write_bytes(canonical(handoff))
    (destination / 'package-index.json').write_bytes(canonical({'format': 'mechanical-assembly-index/1', 'selection': selected}))
    config_path = destination / 'accepted-science-config.json'
    config_path.write_bytes(canonical(config))
    if amendment_value is not None:
        (destination/'consumer-amendment.json').write_bytes(canonical(amendment_value))
    report = {'manifest_sha256': manifest_sha, 'config_sha256': sha256(config_path.read_bytes()).hexdigest(),
              'type_associations': {t: sum(len(load_record(local_file(batch_root, r['chosen_file']))) for r in selected if r['otype'] == t and Path(r['logical_source_file']).stem.replace('-', '_') == 'rules') for t in rows_by_type},
              'counts': {role: len(v) for role, v in merged.items()}, 'science_records': len(entries),
              'original_bytes_retained': True, 'scientific_approval_created': False, 'runtime_capabilities_granted': False}
    (destination / 'assembly-report.json').write_bytes(canonical(report))
    return report
