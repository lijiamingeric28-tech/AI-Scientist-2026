"""Read exact reviewed condition data using an independently accepted trust pin.

This module reads JSON, never executes a candidate's Python modules. Scientific
permission is separate from the local software capability receipts.
"""
from hashlib import sha256
from collections import defaultdict
from copy import deepcopy

from jsonschema import Draft202012Validator

from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from .candidate import load_record, local_file


def read_science_conditions(package, release, config_path, *, config_sha256,
                            reference_aliases=None, reference_alignment_ref=None):
    from .amendments import reference_key
    reference_aliases=reference_aliases or {}
    raw = config_path.read_bytes()
    if sha256(raw).hexdigest() != config_sha256:
        raise DomainError("SCIENCE_CONFIG_TRUST", "科学配置与外部接受的哈希不符", 422)
    config = load_record(config_path)
    if config.get("format") != "candidate-science-verification-config/1":
        raise DomainError("SCIENCE_CONFIG_SCHEMA", "科学配置格式不支持", 422)
    root = package / release["manifest"]["paths"]["build"] / "selection-inputs"
    indexed = {x["path"]: x["file_sha256"] for x in release["manifest"]["content_files"]}
    parsed_files={}

    def pinned(pin, prefix=''):
        relative_pin = prefix + pin['path']
        path = local_file(root, relative_pin)
        relative = release["manifest"]["paths"]["build"] + "/selection-inputs/" + relative_pin
        if indexed.get(relative) != pin["file_sha256"]:
            raise DomainError("SCIENCE_MANIFEST_BINDING", "科学附件未被原清单准确固定", 422)
        key=(relative,pin['file_sha256'])
        if key in parsed_files:return parsed_files[key]
        if sha256(path.read_bytes()).hexdigest() != pin["file_sha256"]:
            raise DomainError("SCIENCE_FILE_HASH", "科学附件原字节不符", 422)
        value=load_record(path);parsed_files[key]=value;return value

    for name in ("validator", "gate"):
        pin = config[name]
        path = local_file(root, pin["path"])
        if sha256(path.read_bytes()).hexdigest() != pin["file_sha256"]:
            raise DomainError("SCIENCE_TOOL_PIN", "科学校验工具引用不符", 422)
    index = pinned(config["index"])
    if index.get("format") != "reviewed-science-conditions-index/1":
        raise DomainError("SCIENCE_INDEX_SCHEMA", "科学条件索引格式不支持", 422)
    trusted = set(config["trusted_receipt_hashes"])
    records, receipts, validators = {}, {}, {}
    originals=defaultdict(list)
    objects = {}
    for role, key, version in (
        ("definitions", "property_id", "definition_version"),
        ("output_profiles", "profile_id", "version"),
        ("conversion_policies", "policy_id", "version"),
    ):
        for obj in release["data"][role]:
            objects[(obj[key], str(obj[version]), obj["content_sha256"])] = obj
    rules_by_property=defaultdict(list)
    for rule in release['data']['unapproved_aggregate_composition_and_rules']['rules']:
        rules_by_property[rule['definition_ref']['id']].append(rule)
    for entry in index["entries"]:
        if entry["independent_receipt"]["file_sha256"] not in trusted:
            raise DomainError("SCIENCE_RECEIPT_TRUST", "候选不能自行授信科学回执", 422)
        prefix = entry.get('path_prefix', '')
        record, receipt = pinned(entry["record"], prefix), pinned(entry["independent_receipt"], prefix)
        native_review = entry.get('review_protocol') == 'candidate-review-array/1'
        if native_review:
            selected = entry['record_selector']
            records_in_file = record if isinstance(record, list) else [record]
            matched = [r for r in records_in_file if r.get('record_id') == selected['id']
                       and str(r.get('version')) == str(selected['version']) and r.get('content_sha256') == selected['content_sha256']]
            if len(matched) != 1:
                raise DomainError('SCIENCE_RECORD_SELECTOR', '科学记录选择器不是准确唯一版本', 422)
            record = matched[0]
            matches = [r for r in receipt if r.get('candidate_ref', {}).get('id') == record['record_id']
                       and str(r.get('candidate_ref', {}).get('version')) == str(record['version'])
                       and r.get('candidate_content_hash') == record['content_sha256']]
            if len(matches) != 1:
                raise DomainError('SCIENCE_RECEIPT_BINDING', '数组回执未准确审核本条件版本', 422)
            receipt = matches[0]
            if (receipt.get('decision') != 'approved' or content_hash(receipt) != receipt.get('content_sha256')
                    or not receipt.get('checks') or any(v != 'passed' for v in receipt['checks'].values())):
                raise DomainError('SCIENCE_RECEIPT_BINDING', '独立科学审核未通过或哈希不符', 422)
        schema_hash = entry["schema"]["file_sha256"]
        if schema_hash not in validators:
            schema = pinned(entry["schema"], prefix)
            Draft202012Validator.check_schema(schema)
            validators[schema_hash] = Draft202012Validator(schema)
        validators[schema_hash].validate(record)
        rp = receipt.get("record_file_ref", {})
        if not native_review and (
            {k: rp.get(k) for k in ("path", "file_sha256")} != entry["record"]
            or rp.get("record_content_sha256") != record["content_sha256"]
            or receipt.get("schema_file_ref") != entry["schema"]
            or not str(receipt.get("decision", "")).startswith("approved_with_conditions")
            or content_hash(record) != record["content_sha256"]
        ):
            raise DomainError("SCIENCE_RECEIPT_BINDING", "独立科学回执不对应准确条件记录", 422)
        if content_hash(record) != record.get('content_sha256'):
            raise DomainError('SCIENCE_RECORD_HASH', '条件原记录哈希不符', 422)
        for name in ("definition_ref", "profile_ref", "conversion_policy_ref"):
            ref = record[name]
            if name=='profile_ref':ref=reference_aliases.get(reference_key(ref),ref)
            if (ref["id"], str(ref["version"]), ref["content_sha256"]) not in objects:
                raise DomainError("SCIENCE_TARGET_BINDING", "科学许可未绑定准确性质、输出及政策", 422)
        pid = record["definition_ref"]["id"]
        keys = {c["key"] for c in record["required_conditions"]}
        if any(not set(op.get("requires", [])) <= keys for op in record["operations"]):
            raise DomainError("SCIENCE_UNDEFINED_PREDICATE", "操作引用了未定义条件", 422)
        types=entry.get('accepted_otypes')
        if types is None:
            # Legacy single-package indexes had no explicit type selector.
            # Only its own reviewed source ASTs supply that association.
            from .compiler import matches
            rules=rules_by_property[pid]
            types=sorted({profile['otype'] for profile in release['data']['type_profiles']
                for rule in rules if rule['definition_ref']['id']==pid
                and reference_key(reference_aliases.get(reference_key(rule['profile_ref']),rule['profile_ref']))
                    ==reference_key(reference_aliases.get(reference_key(record['profile_ref']),record['profile_ref']))
                and matches(rule['when'],{profile['otype']},rule['subject_class_id'])})
        if not isinstance(types,list) or not types or any(not isinstance(t,str) or not t for t in types):
            raise DomainError('SCIENCE_TYPE_SCOPE','科学条件缺少已审类型作用域',422)
        origin={'record_ref':{'id':record['record_id'],'version':record['version'],'content_sha256':record['content_sha256']},
                'path_prefix':prefix,'record':entry['record'],'independent_receipt':entry['independent_receipt'],
                'receipt':receipt,'accepted_otypes':sorted(set(types))}
        originals[(record['record_id'],str(record['version']))].append((record,origin))
    variants=defaultdict(list)
    for (record_id,version),items in sorted(originals.items()):
        semantic=[]
        for record,_ in items:
            payload=deepcopy(record)
            payload['profile_ref']=reference_aliases.get(reference_key(record['profile_ref']),record['profile_ref'])
            semantic.append({k:v for k,v in payload.items() if k not in {'independent_review_refs','content_sha256'}})
        if len({digest(p) for p in semantic})!=1:
            raise DomainError('SCIENCE_ID_CONFLICT','同条件ID版本存在实质科学差异，不能覆盖或合并',422,record_id=record_id)
        origin_list=list({digest(o):o for _,o in items}.values())
        origin_list.sort(key=digest)
        record=deepcopy(items[0][0]);original_hashes={r['content_sha256'] for r,_ in items}
        aligned=reference_key(record['profile_ref']) in reference_aliases
        if len(original_hashes)>1 or aligned:
            record['record_id']='consumer-science-'+digest({'origins':origin_list,'alignment':reference_alignment_ref if aligned else None})[:28]
            record['version']=1
            record['profile_ref']=reference_aliases.get(reference_key(record['profile_ref']),record['profile_ref'])
            record['independent_review_refs']=list({digest(ref):ref for r,_ in items for ref in r.get('independent_review_refs',[])}.values())
            record['consumer_view_format']='reviewed-condition-provenance-view/1'
            record['original_condition_refs']=[o['record_ref'] for o in origin_list]
            record['original_receipt_origins']=origin_list
            if aligned:record['consumer_reference_alignment_ref']=reference_alignment_ref
            record['content_sha256']=content_hash(record)
        variant={'record':record,'accepted_otypes':sorted({t for o in origin_list for t in o['accepted_otypes']}),
                 'origins':origin_list}
        variants[record['definition_ref']['id']].append(variant)
    # Legacy direct lookup is available only for unambiguous quantities.
    # Shared quantities retain independent type-scoped records, never last-wins.
    for pid,choices in variants.items():
        if len(choices)==1:
            records[pid]=choices[0]['record']
            origin=choices[0]['origins'][0]
            receipts[pid]={**origin,'origins':choices[0]['origins']}
    result={"config_sha256":config_sha256,"config":config,"records":records,"receipts":receipts,'variants':dict(variants)}
    return reindex_conditions(result)


def reindex_conditions(science):
    from .amendments import reference_key
    variants=science.get('variants',{})
    for pid,choices in variants.items():
        if len(choices)==1 and pid in science['records']:
            choices[0]['record']=science['records'][pid]
    values=[v['record'] for choices in variants.values() for v in choices] if variants else list(science['records'].values())
    science['by_ref']={reference_key({'id':r['record_id'],'version':r['version'],'content_sha256':r['content_sha256']}):r for r in values}
    return science


def scoped_conditions(science, property_id, otypes):
    choices=science.get('variants',{}).get(property_id)
    if choices is None:
        record=science.get('records',{}).get(property_id)
        return [{'record':record,'accepted_otypes':list(otypes)}] if record else []
    return [v for v in choices if set(v['accepted_otypes']) & set(otypes)]


def binding_condition_refs(binding):
    return [b['science_ref'] for b in binding.get('science_branches',[])] or ([binding['science_ref']] if binding.get('science_ref') else [])


def binding_condition_hashes(binding):
    return {r['content_sha256'] for r in binding_condition_refs(binding)}


def bound_condition_records(release, binding):
    from .amendments import reference_key
    science=release.get('science',{})
    refs=binding_condition_refs(binding)
    if science.get('by_ref'):
        result=[science['by_ref'].get(reference_key(ref)) for ref in refs]
        if any(r is None for r in result):
            raise DomainError('SCIENCE_FROZEN_BINDING','冻结科学分支不属于准确库版本',422)
        return result
    record=science.get('records',{}).get(binding['property_id'])
    return [record] if record else []


def condition_summary(record):
    """Only the current quantity's semantic requirements, without audit history."""
    return {
        "record_ref": {"id": record["record_id"], "version": int(record["version"]), "content_sha256": record["content_sha256"]},
        "predicates": [{k: c[k] for k in ("key", "expected", "applies_to", "on_missing", "evidence_requirement", "applies_when") if k in c} for c in record["required_conditions"]],
        "contexts": [{k: c[k] for k in ("key", "value_type", "required", "required_scope", "on_missing", "meaning") if k in c} for c in record["context_contracts"]],
        "operations": [{k: op[k] for k in ("operation", "applies_to", "requires", "scientific_decision") if k in op} for op in record["operations"]],
    }
