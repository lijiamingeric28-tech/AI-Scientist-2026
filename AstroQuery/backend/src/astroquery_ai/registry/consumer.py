"""Immutable consumer configuration for reviewed candidates, not Dot activation."""
from copy import deepcopy

from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from .candidate import CandidateRegistry
from .models import PropertyDefinition, OutputProfile
from .projection import CandidateProjection, positive_version
from .science_conditions import condition_summary, read_science_conditions, reindex_conditions, scoped_conditions
from .compiler import compile_rules


def reviewed_compositions(config, contexts):
    """Explicit externally pinned compositions, never folder/type auto-union."""
    approved = {}
    for record in config.get('reviewed_type_compositions', []):
        payload = {k: record.get(k) for k in ('otypes', 'subject_class_id', 'bindings')}
        types, subject = payload['otypes'], payload['subject_class_id']
        receipt = record.get('review', {})
        if (not isinstance(types, list) or len(types) < 2 or len(set(types)) != len(types)
                or any((t, subject) not in contexts for t in types)
                or not isinstance(payload['bindings'], list) or not payload['bindings']
                or receipt.get('decision') != 'approved'
                or receipt.get('reviewed_payload_sha256') != digest(payload)
                or not receipt.get('checks') or not receipt.get('reviewer')):
            raise DomainError('UNREVIEWED_TYPE_COMPOSITION', '组合缺少准确审定内容和回执', 422)
        key = (tuple(sorted(types)), subject)
        if key in approved:
            raise DomainError('UNREVIEWED_TYPE_COMPOSITION', '组合审定重复', 422)
        # Reuse the full registry's exact-definition/profile conflict compiler.
        rules = []
        for index, binding in enumerate(payload['bindings']):
            rule = {'rule_id': 'composition-check-' + str(index), 'version': 1,
                'condition': {'all_of': [{'otype': t} for t in types] + [{'subject_class': subject}]},
                'definition_ref': binding['definition_ref'], 'profile_ref': binding['profile_ref'],
                'evidence_refs': [], 'review_ref': {'id': 'externally-pinned-composition-review',
                    'version': 1, 'content_sha256': digest(receipt)}, 'enabled': True}
            rule['content_sha256'] = content_hash(rule)
            rules.append(rule)
        compile_rules(rules, [])
        approved[key] = record
    return approved


def consume_candidate(package, config_path, *, manifest_sha256, config_sha256, amendment=None, consumer_protocol='reviewed-AST-context/2'):
    reader = CandidateRegistry()
    candidate = reader.inspect(package)
    if candidate["report"]["manifest_file_sha256"] != manifest_sha256:
        raise DomainError("CANDIDATE_EXTERNAL_TRUST", "候选清单不符外部接受的版本", 422)
    from .amendments import checked_reference_alignments
    aliases=checked_reference_alignments(package,candidate,amendment)
    if aliases:
        candidate['reference_aliases']=aliases
        candidate['reference_alignment_ref']={'id':amendment['amendment_id'],'version':amendment.get('revision',1),
                                            'content_sha256':amendment['content_sha256']}
    science = read_science_conditions(package, candidate, config_path, config_sha256=config_sha256,
                                      reference_aliases=aliases, reference_alignment_ref=candidate.get('reference_alignment_ref'))
    from .amendments import apply_amendments
    science = reindex_conditions(apply_amendments(science, amendment))
    candidate["science"] = science
    return compile_verified_inputs(candidate, manifest_sha256, config_sha256, amendment, consumer_protocol)


def compile_verified_inputs(candidate, manifest_sha256, config_sha256, amendment, consumer_protocol):
    """Compile the same runtime view for an audited source tree or its pinned distribution."""
    from .amendments import amend_view
    reader = CandidateRegistry(candidate)
    science = candidate["science"]
    projection = CandidateProjection(candidate)
    profiles = candidate["data"]["type_profiles"]
    contexts = {(p["otype"], p["subject_class_id"]) for p in profiles}
    # A type profile's default subject cannot hide its reviewed nuclear/member
    # rules. Add only subjects actually selected by that type's source ASTs.
    rules_for_context = candidate['data']['unapproved_aggregate_composition_and_rules']['rules']
    from .compiler import condition_variables, matches
    context_rules = [r for r in rules_for_context if 'when' in r and 'subject_class_id' in r]
    # Validate every source condition, including rules that do not add a new
    # subject. Existing contexts need no discovery evaluation; their AST/BDD
    # agreement is still checked independently below for every context.
    for rule in context_rules:
        condition_variables(rule['when'])
    for p in profiles:
        for r in context_rules:
            context = p['otype'], r['subject_class_id']
            if context not in contexts and matches(r['when'], {p['otype']}, r['subject_class_id']):
                contexts.add(context)
    compositions = reviewed_compositions(science['config'], contexts)
    views, context_bindings = {}, {}
    composition_bindings = {}
    rules = {r['rule_id']: r for r in rules_for_context}
    requested = [((otype,), subject) for otype, subject in sorted(contexts)] + list(compositions)
    for types, subject in requested:
        selected = reader.select_context(candidate, accepted_otypes=list(types), subject_class_id=subject)
        support = projection.support(selected)
        if support["gaps"]:
            raise DomainError("CANDIDATE_CONSUMER_GAPS", "审定配置存在未接通的消费视图", 422, gaps=support["gaps"])
        bindings = []
        for view in support["bindings"]:
            view = amend_view(view, amendment)
            pid = view["property_id"]
            choices=[v for v in scoped_conditions(science,pid,types)
                     if v['record']['profile_ref']['content_sha256']==view['source_binding']['output_profile']['content_sha256']]
            if not choices:
                raise DomainError("SCIENCE_BINDING_MISSING", "适用性质缺少准确科学条件绑定", 422,
                    property_id=pid,otypes=list(types),profile_ref=view['source_binding']['output_profile'],
                    available=[{'otypes':v['accepted_otypes'],'profile_ref':v['record']['profile_ref']}
                               for v in scoped_conditions(science,pid,types)])
            refs = [{"id": rid, "version": positive_version(rules[rid]["version"]), "content_sha256": rules[rid]["content_sha256"]} for rid in view["source_binding"]["active_rule_refs"]]
            branches=[{'otypes':sorted(set(v['accepted_otypes']) & set(types)),
                       'science_ref':condition_summary(v['record'])['record_ref'],
                       'science_conditions':condition_summary(v['record'])} for v in choices]
            summary=branches[0]['science_conditions']
            binding = {
                "property_id": pid, "definition": view["definition"], "output_profile": view["output_profile"],
                "rule_refs": refs,
                "dependency_refs": [*refs, *view["definition"]["evidence_refs"], view["definition"]["review_ref"], view["output_profile"]["review_ref"], view["output_profile"]["conversion_policy_ref"], summary["record_ref"]],
                "candidate_projection_receipt": view["projection_receipt"],
                "science_ref": summary["record_ref"], "science_conditions": summary,
                **({'science_branches':branches} if len(branches)>1 else {}),
            }
            binding['dependency_refs'].extend(b['science_ref'] for b in branches if b['science_ref'] not in binding['dependency_refs'])
            bindings.append(binding)
            views[(pid,view['definition']['content_sha256'],view['output_profile']['content_sha256'])] = view
        if len(types) == 1:
            context_bindings[(types[0], subject)] = bindings
        else:
            expected = compositions[(types, subject)]['bindings']
            actual = [{'definition_ref': {'id': b['property_id'],
                'version': b['definition']['definition_version'],
                'content_sha256': b['definition']['content_sha256']},
                'profile_ref': {'id': b['output_profile']['profile_id'],
                'version': b['output_profile']['version'],
                'content_sha256': b['output_profile']['content_sha256']}} for b in bindings]
            if {digest(x) for x in expected} != {digest(x) for x in actual}:
                raise DomainError('COMPOSITION_BINDING_MISMATCH', '组合实际规则结果与准确审定绑定不符', 422)
            composition_bindings[(types, subject)] = bindings
    consumer_view_hash = digest({str(k): v for k, v in context_bindings.items()})
    manifest = {
        "schema_version": "registry-candidate-consumer/1",
        "release_id": "consumer-" + manifest_sha256[:16] + "-" + consumer_view_hash[:12],
        "source_manifest_sha256": manifest_sha256,
        "science_config_sha256": config_sha256,
        "source_candidate_flags_unchanged": True,
        "runtime_capabilities": "separate_local_receipts_required",
        "projection_version": projection.version,
        "consumer_view_hash": consumer_view_hash,
    }
    if consumer_protocol:
        manifest['support_policy']=consumer_protocol
        manifest['release_id']='consumer-'+manifest_sha256[:16]+'-'+digest({'contexts':manifest['consumer_view_hash'],'support_policy':consumer_protocol})[:12]
    manifest["content_sha256"] = content_hash(manifest)
    if compositions:
        manifest['reviewed_compositions_sha256'] = digest({str(k): v for k, v in compositions.items()})
        manifest['content_sha256'] = content_hash(manifest)
    if amendment is not None:
        manifest['amendment_sha256'] = amendment['content_sha256']
        manifest['content_sha256'] = content_hash(manifest)
    objects = {}
    for role, key in (("families", "family_id"), ("subject_classes", "subject_class_id"), ("object_scales", "object_scale_id"), ("evidence", "evidence_id"), ("reviews", "review_id"), ("conversion_policies", "policy_id")):
        objects.update({o[key]: o for o in candidate["data"][role]})
    from .amendments import reference_key
    definition_views,profile_views,source_definition_refs={},{},{}
    for view in views.values():
        objects[view["property_id"]] = view["definition"]
        objects[view["output_profile"]["profile_id"]] = view["output_profile"]
        definition=PropertyDefinition.model_validate(view['definition'])
        key=reference_key({'id':definition.property_id,'version':definition.definition_version,'content_sha256':definition.content_sha256})
        definition_views[key]=definition
        source_definition_refs[key]=[view['projection_receipt']['source_definition_ref']]
        for branch in science.get('variants',{}).get(view['property_id'],[]):
            if branch['record']['profile_ref']['content_sha256']==view['source_binding']['output_profile']['content_sha256']:
                ref=branch['record']['definition_ref']
                if ref not in source_definition_refs[key]:source_definition_refs[key].append(ref)
        profile=OutputProfile.model_validate(view['output_profile'])
        profile_views[reference_key({'id':profile.profile_id,'version':profile.version,'content_sha256':profile.content_sha256})]=profile
    objects.update({r['record_id']:r for r in science.get('by_ref',{}).values()})
    return {
        "manifest": manifest, "candidate": candidate, "science": science,
        "data": {"type-profiles": profiles, "families": candidate["data"]["families"], "conversion-policies": candidate["data"]["conversion_policies"]},
        "definitions": {v['property_id']: PropertyDefinition.model_validate(v['definition']) for v in views.values()},
        "profiles": {v["output_profile"]["profile_id"]: OutputProfile.model_validate(v["output_profile"]) for v in views.values()},
        'definition_views':definition_views,'profile_views':profile_views,'source_definition_refs':source_definition_refs,
        "objects": objects, "context_bindings": context_bindings,
        'composition_bindings': composition_bindings,'consumer_amendment':amendment,
    }


def consumer_support(release, otypes, subject_class_id):
    if (release.get('manifest',{}).get('support_policy')=='reviewed-AST-context/2'
            and (tuple(sorted(otypes)),subject_class_id) not in release.get('composition_bindings',{})):
        return _ast_support(release,otypes,subject_class_id)
    # Only independently bound single-type contexts contribute properties. Other
    # SIMBAD labels stay on the target; they never add an unreviewed type union.
    matched = [(key, value) for key, value in release["context_bindings"].items() if key[0] in otypes and key[1] == subject_class_id]
    if len(matched) > 1:
        types = tuple(sorted(k[0] for k, _ in matched))
        bindings = release.get('composition_bindings', {}).get((types, subject_class_id))
        if bindings is not None:
            semantic = {'otypes': list(types), 'subject_class_id': subject_class_id, 'bindings': deepcopy(bindings)}
            return {**semantic, 'support_hash': digest(semantic), 'gaps': []}
        policy = release.get('science', {}).get('config', {}).get('accepted_type_union', {})
        if policy.get('policy') == 'exact-definition-profile-subject-union/1' and policy.get('authorized_by') == 'user':
            union,conflicts = {},{}
            for (matched_otype, _subject), group in matched:
                for binding in group:
                    pid = binding['property_id']
                    if pid in conflicts:
                        if matched_otype not in conflicts[pid]['otypes']:conflicts[pid]['otypes'].append(matched_otype)
                        candidate_version={'definition':binding['definition'],'output_profile':binding['output_profile']}
                        if candidate_version not in conflicts[pid]['versions']:conflicts[pid]['versions'].append(candidate_version)
                        continue
                    if pid in union and (union[pid]['definition'] != binding['definition']
                            or union[pid]['output_profile'] != binding['output_profile']):
                        conflicts[pid]={'property_id':pid,'reason':'reviewed_versions_conflict_in_type_composition',
                            'otypes':list(types),'name_cn':binding['definition'].get('name_cn'),
                            'versions':[{'definition':union[pid]['definition'],'output_profile':union[pid]['output_profile']},
                                        {'definition':binding['definition'],'output_profile':binding['output_profile']}],
                            'no_version_chosen':True}
                        union.pop(pid)
                        continue
                    if pid not in union:
                        union[pid] = deepcopy(binding)
                        if binding.get('science_ref'):
                            union[pid]['science_branches']=deepcopy(binding.get('science_branches') or [{
                                'otypes':[matched_otype],'science_ref':binding['science_ref'],
                                'science_conditions':binding['science_conditions']}])
                    else:
                        union[pid]['rule_refs'] = list({digest(r): r for r in [*union[pid]['rule_refs'], *binding['rule_refs']]}.values())
                        union[pid]['dependency_refs'] = list({digest(r): r for r in [*union[pid]['dependency_refs'], *binding['dependency_refs']]}.values())
                        if binding.get('science_ref'):
                            existing=union[pid]['science_branches']
                            incoming=binding.get('science_branches') or [{'otypes':[matched_otype],
                                'science_ref':binding['science_ref'],'science_conditions':binding['science_conditions']}]
                            for branch in incoming:
                                previous=next((b for b in existing if b['science_ref']==branch['science_ref']),None)
                                if previous:previous['otypes']=sorted(set(previous['otypes'])|set(branch['otypes']))
                                else:existing.append(deepcopy(branch))
            semantic = {'otypes': list(types), 'subject_class_id': subject_class_id, 'bindings': list(union.values())}
            gaps=list(conflicts.values())
            return {**semantic, 'support_hash': digest({**semantic,'gaps':gaps}) if gaps else digest(semantic), 'gaps': gaps, 'composition_check': {
                'rule': policy['policy'], 'otypes': list(types), 'subject_class_id': subject_class_id,
                'exact_conflict_check': 'passed', 'binding_hash': digest(semantic['bindings'])}}
    if len(matched) != 1:
        raise DomainError("UNREVIEWED_TYPE_COMPOSITION", "没有唯一已审定的类型配置", 422)
    (otype, _), bindings = matched[0]
    semantic = {"otypes": [otype], "subject_class_id": subject_class_id, "bindings": deepcopy(bindings)}
    return {**semantic, "support_hash": digest(semantic), "gaps": []}


def _ast_support(release,otypes,subject):
    """Evaluate approved source ASTs against the actual confirmed type set.

    This includes reviewed parent+stratum gates and exclusions. It neither
    enumerates all combinations nor promotes child scope to an untyped parent.
    """
    policy=release['science']['config'].get('accepted_type_union',{})
    if len(otypes)>1 and (policy.get('policy')!='exact-definition-profile-subject-union/1' or policy.get('authorized_by')!='user'):
        raise DomainError('UNREVIEWED_TYPE_COMPOSITION','缺少按审定规则取并集的授权',422)
    candidate=release['candidate'];known={p['otype'] for p in candidate['data']['type_profiles']}
    types=sorted(set(otypes)&known)
    selected=CandidateRegistry().select_context(candidate,accepted_otypes=types,subject_class_id=subject)
    projected=CandidateProjection(candidate).support(selected)
    from .amendments import amend_view,reference_key
    from .projection import definition_view,output_profile_view
    rules={r['rule_id']:r for r in candidate['data']['unapproved_aggregate_composition_and_rules']['rules']}
    bindings=[];gaps=list(projected['gaps'])
    for raw_view in projected['bindings']:
        view=amend_view(raw_view,release.get('consumer_amendment'))
        pid=view['property_id'];d=view['definition'];p=view['output_profile']
        if not definition_view(release,pid,d['definition_version'],d['content_sha256']) or not output_profile_view(release,{'id':p['profile_id'],'version':p['version'],'content_sha256':p['content_sha256']}):
            gaps.append({'property_id':pid,'reason':'conditional_view_not_in_exact_accepted_definitions'})
            continue
        active_rules=set(view['source_binding']['active_rule_refs'])
        active_types={t['otype'] for t in candidate['data']['type_profiles'] if t['otype'] in types
                      and active_rules & {r['id'] for r in t['include_rules']}}
        choices=[v for v in scoped_conditions(release['science'],pid,active_types) if v['record']['profile_ref']['content_sha256']==view['source_binding']['output_profile']['content_sha256']]
        if not choices:
            gaps.append({'property_id':pid,'reason':'scientific_condition_branch_missing'});continue
        refs=[{'id':rid,'version':positive_version(rules[rid]['version']),'content_sha256':rules[rid]['content_sha256']} for rid in view['source_binding']['active_rule_refs']]
        branches=[{'otypes':sorted(set(v['accepted_otypes'])&active_types),
            'science_ref':condition_summary(v['record'])['record_ref'],'science_conditions':condition_summary(v['record'])} for v in choices]
        summary=branches[0]['science_conditions']
        binding={'property_id':pid,'definition':d,'output_profile':p,'rule_refs':refs,
            'dependency_refs':[*refs,*d['evidence_refs'],d['review_ref'],p['review_ref'],p['conversion_policy_ref'],*[b['science_ref'] for b in branches]],
            'candidate_projection_receipt':view['projection_receipt'],'science_ref':summary['record_ref'],
            'science_conditions':summary,**({'science_branches':branches} if len(branches)>1 else {})}
        bindings.append(binding)
    semantic={'otypes':types,'subject_class_id':subject,'bindings':bindings}
    return {**semantic,'support_hash':digest({**semantic,'gaps':gaps}),'gaps':gaps,
            'composition_check':{'rule':'reviewed-AST-context/2','otypes':types,'subject_class_id':subject,
                                 'exact_conflict_check':'local_gaps_preserved','binding_hash':digest(bindings)}}


def potential_type_bindings(release,otype):
    """Catalogue options with their reviewed positive type prerequisites.

    These are not assertions about a target. Request support always evaluates
    its real confirmed types. This view supports precise conditional KB binding
    and package regression of explicitly confirmed physical strata.
    """
    cache=release.setdefault('_potential_type_bindings',{})
    if otype in cache:return cache[otype]
    from .compiler import matches
    candidate=release['candidate']
    profile=next(p for p in candidate['data']['type_profiles'] if p['otype']==otype)
    ids={r['id'] for r in profile['include_rules']}
    contexts={(tuple([otype]),subject) for t,subject in release['context_bindings'] if t==otype}
    def witnesses(node,subject):
        if 'otype' in node:return [{node['otype']}]
        if 'subject_class' in node:return [set()] if node['subject_class']==subject else []
        if 'not' in node:return [set()]
        if 'any_of' in node:return [s for n in node['any_of'] for s in witnesses(n,subject)]
        choices=[set()]
        for child in node.get('all_of',[]):choices=[a|b for a in choices for b in witnesses(child,subject)]
        return choices
    for rule in candidate['data']['unapproved_aggregate_composition_and_rules']['rules']:
        if rule['rule_id'] not in ids or rule['kind']!='include':continue
        subject=rule['subject_class_id']
        for types in witnesses(rule['when'],subject):
            types=types|{otype}
            if matches(rule['when'],types,subject):contexts.add((tuple(sorted(types)),subject))
    choices={}
    for types,subject in sorted(contexts):
        support=consumer_support(release,list(types),subject)
        for b in support['bindings']:
            # Other types in a witness do not donate unrelated KB properties.
            if not any(r['id'] in ids for r in b['rule_refs']):continue
            key=(b['property_id'],b['definition']['content_sha256'],b['output_profile']['content_sha256'])
            choices.setdefault(key,{**b,'applicability_type_contexts':[]})['applicability_type_contexts'].append(list(types))
    cache[otype]=list(choices.values())
    return cache[otype]


def source_files(package, candidate):
    return ["registry-handoff.json", "package-index.json", candidate["handoff"]["manifest_path"], *[f["path"] for f in candidate["manifest"]["content_files"]]]
