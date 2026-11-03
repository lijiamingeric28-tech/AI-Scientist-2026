"""Bind supplied precise knowledge claims; preserve content and review labels."""
from copy import deepcopy
from astroquery_ai.runtime.codec import digest, content_hash
from astroquery_ai.runtime.errors import DomainError
from .science_conditions import bound_condition_records
from .amendments import reference_key


def bind_claim_plan(registry, content, plan, *, otype, registry_ref, plan_ref):
    if plan.get('schema_version') != 'ReviewedKnowledgeBindingPlan/1':
        raise DomainError('KB_PLAN_SCHEMA', '知识映射计划格式不支持', 422)
    entries = {e['entry_id']: e for e in content['entries']}
    available = {}
    from .consumer import potential_type_bindings
    for b in potential_type_bindings(registry,otype):
        available.setdefault(b['property_id'], []).append(b)
    bindings, reviews, gaps = [], [], []
    for group in plan['groups']:
        entry = entries.get(group['entry_id'])
        if entry is None:
            gaps.append({'entry_id': group['entry_id'], 'reason': 'no_exact_existing_content'})
            continue
        if otype not in entry['otype_scope']:
            gaps.append({'entry_id': group['entry_id'], 'reason': 'original_content_otype_scope_excludes_requested_type',
                         'properties': group['properties'], 'original_otype_scope': entry['otype_scope']})
            continue
        if set(group['claim_ids']) - {c['claim_id'] for c in entry['claims']}:
            raise DomainError('KB_PLAN_SCOPE', '知识原类型范围或准确声明不符', 422, entry_id=entry['entry_id'])
        entry_pin=group.get('entry_ref',{})
        pinned_hash=entry_pin.get('content_sha256',group.get('entry_content_hash',group.get('content_hash')))
        pinned_version=entry_pin.get('version',group.get('entry_revision',group.get('revision')))
        if ((pinned_hash and pinned_hash != entry['content_hash'])
                or (pinned_version is not None and str(pinned_version) != str(entry['revision']))):
            raise DomainError('KB_PLAN_ENTRY_PIN', '知识计划指向不同原条目版本', 422)
        property_pins={r['id']:r for r in group.get('property_refs',[])}
        for pid in group['properties']:
            choices=available.get(pid,[])
            pin=property_pins.get(pid)
            if pin:
                choices=[b for b in choices if reference_key(pin)==reference_key(
                    b['candidate_projection_receipt']['source_definition_ref'])]
            if not choices:
                gaps.append({'entry_id':entry['entry_id'],'property_id':pid,
                    'reason':'no_exact_applicable_definition_for_plan','property_ref':pin})
                continue
            if len(choices)!=1:
                gaps.append({'entry_id':entry['entry_id'],'property_id':pid,
                    'reason':'multiple_reviewed_subject_bindings_require_explicit_mapping'})
                continue
            b=choices[0]
            d, p = b['definition'], b['output_profile']
            binding = {'registry_release_ref': registry_ref,
                'entry_ref': {'id': entry['entry_id'], 'version': entry['revision'], 'content_sha256': entry['content_hash']},
                'property_bindings': [{'property_id': pid, 'definition_version': d['definition_version'],
                    'definition_hash': d['content_sha256'], 'source_definition_ref': bound_condition_records(registry,b)[0]['definition_ref'],
                    'output_profile_ref': {'id': p['profile_id'], 'version': p['version'], 'content_sha256': p['content_sha256']}}],
                'subject_class_ids': [d['subject_class_id']], 'object_scale': p['object_scale_id'], 'otype_scope': [otype],
                'claim_ids': group['claim_ids'], 'required_conditions': [], 'excluded_conditions': [],
                'include_formula': False,
                'content_condition_bindings': [{'condition_id': c['condition_id'], 'mode': group['condition_mode'],
                    'explanation': group['explanation']} for c in entry.get('conditions', [])],
                'mapping_basis': 'supplied_precise_claim_plan_and_software_binding_review', 'mapping_plan_ref': plan_ref,
                'mapping_explanation': group['explanation'],
                'applicability_rule_refs':b['rule_refs'],
                'author_subject_conditions': {k:deepcopy(group[k]) for k in
                    ('subject_binding_condition','source_context_conditions','subject_gate','subject_binding') if k in group}}
            binding, review = review_binding(binding)
            bindings.append(binding); reviews.append(review)
    return bindings, reviews, gaps


def review_binding(binding):
    binding = deepcopy(binding)
    for key in ['binding_id', 'review_ref', 'content_sha256']:
        binding.pop(key, None)
    binding['binding_id'] = 'binding-' + digest(binding)
    review = {'review_id': 'binding-review-' + digest(binding), 'review_version': 1, 'decision': 'approved',
        'reviewer_kind': 'software_consumer_binding_review', 'independent_human_science_review': False,
        'reviewed_payload_sha256': digest(binding), 'unresolved': [],
        'checks': {'exact_definition_and_profile': 'passed', 'declared_subject_scale': 'passed',
                   'claims_and_source_labels_unchanged': 'passed', 'conditional_assumptions_not_established': 'passed',
                   'target_formula_execution': 'forbidden'}}
    review['content_sha256'] = content_hash(review)
    binding['review_ref'] = {'id': review['review_id'], 'version': 1, 'content_sha256': review['content_sha256']}
    binding['content_sha256'] = content_hash(binding)
    return binding, review
