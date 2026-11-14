'M08 consumes carried source evidence before permitted coordinate arithmetic.'

from copy import deepcopy

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.science_capabilities import operation_eligibility, verification_scope

from ..scientific_conditions import VERSION, checked_semantics, operation_permission, semantic_prompt, merge_semantic_repair

from ..uncertainty_interpretation import available_spans

CONSUMER_REVISION = 'source-context-use-8-native-coordinate'

def carried_science_spans(app, tid, release, evidence, interpretation, source):
    if source.get('kind') == 'paper' and interpretation.get('measurement_id'):
        with app.repository.read() as conn:
            record = app.repository.object(conn, tid, 'measurement', interpretation['measurement_id'])
            current_checks = [loads(row[0]) for row in conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='source_recheck' ORDER BY created_at,version", (tid,))]
        candidates = [o['verification'] for report in current_checks for o in report['outcomes'] if o['item_ref'].get('id') == record['measurement_id'] and o['item_ref'].get('content_sha256') == record['content_sha256'] and (o.get('verification', {}).get('state') == 'passed')]
        if candidates:
            interpretation = {**interpretation, 'paper_verification': candidates[-1]}
    spans = available_spans(evidence, interpretation, source)
    if interpretation.get('human_answer_ref') and evidence.get('text_origin') == 'model_transcription':
        from astroquery_ai.science.measurements.admission_contracts import normalized
        from astroquery_ai.science.paper_admission import page_blocks
        with app.repository.read() as conn:
            try:
                index = app.repository.object(conn, tid, 'document_index', source['source_id'])
            except DomainError:
                index = None
        if index:
            blocks = page_blocks({p['page']: p['text'] for p in index['pages']})
            check = (interpretation.get('paper_verification') or {}).get('check') or interpretation['proposal'].get('local_admission') or {}
            anchors = [a for k in ('subject_evidence', 'role_evidence', 'quantity_evidence', 'unit_evidence') for a in check.get(k, [])]
            anchors.extend((a for key in ('local_evidence', 'scope_evidence', 'counter_evidence') for a in (check.get('subject_link') or {}).get(key, [])))
            for anchor in anchors:
                selected = [b for b in blocks if b['page'] == anchor['page'] and (b['block_id'] in anchor.get('block_ids', []) or (anchor.get('quote') and normalized(anchor['quote']) in normalized(b['text'])))]
                for block in selected:
                    span = {'text': block['text'], 'page': block['page'], 'locator': block['block_id'], 'origin': 'human_confirmed_owned_paper_anchor', 'answer_ref': interpretation['human_answer_ref']}
                    spans.append({'span_id': 'human-source-' + digest(span), **span})
    if evidence.get('text_origin') == 'original_cells':
        saved = loads(evidence['raw_text'])
        if isinstance(saved.get('cells'), dict):
            spans.append({'span_id': 'science-cells-' + digest(evidence['artifact_ref']), 'text': canonical(saved['cells']).decode(), 'origin': 'original_source_cells'})
    for key in ('description', 'notes', 'readme_context'):
        text = source.get('metadata', {}).get(key)
        if isinstance(text, str) and text.strip():
            spans.append({'span_id': 'science-source-' + digest({'source': source['source_id'], 'key': key, 'text': text}), 'text': text, 'origin': 'carried_source_document'})
    for ref in source.get('reviewed_source_evidence_refs', []):
        item = release['objects'].get(ref['id'])
        if not item or item['content_sha256'] != ref['content_sha256']:
            raise DomainError('SCIENCE_SOURCE_EVIDENCE', '来源语义证据引用不符', 422)
        if item.get('artifact_sha256') not in source.get('carried_document_artifact_hashes', []):
            raise DomainError('SCIENCE_SOURCE_EVIDENCE', '来源语义证据未绑定携带的原件', 422)
        app.artifacts.read_owned(tid, item['artifact_sha256'])
        spans.append({'span_id': 'reviewed-source-' + item['evidence_id'], 'text': item['excerpt'], 'origin': 'exact_reviewed_source_excerpt', 'evidence_ref': ref, 'source_url': item.get('source_url'), 'source_id': item.get('source_id'), 'source_kind': item.get('source_kind')})
    return spans

def replay_verified_response(repo, conn, old_tid, record, interpretation):
    """Explicit regression replay of real responses, never a new provider call."""
    old_records = repo.objects(conn, old_tid, 'measurement')
    matching = []
    for old in old_records:
        old_interpretation = repo.object(conn, old_tid, 'interpretation', old['interpretation_ref']['id'], old['interpretation_ref']['version'])
        if old['property_ref'] == record['property_ref'] and old['source_ref'] == record['source_ref'] and (old['target_ref'] == record['target_ref']) and (old_interpretation['proposal'] == interpretation['proposal']):
            matching.append(old)
    if len(matching) != 1:
        raise DomainError('SEMANTIC_REPLAY_INPUT_CHANGED', '真实响应回归的源、对象、定义或提案发生变化')
    old = matching[0]
    steps = [r for r in repo.objects(conn, old_tid, 'job_step') if r.get('kind') == 'model' and r.get('receipt', {}).get('operation') == 'source_conditions' and isinstance(r.get('response', {}).get('checks'), list) and all((c.get('key', '').startswith('source_') for c in r['response']['checks']))]
    if not steps:
        raise DomainError('SEMANTIC_REPLAY_AMBIGUOUS', '缺少唯一可核对的真实条件响应')
    times = {r['attempt_id']: r['created_at'] for r in conn.execute('SELECT attempt_id,created_at FROM attempts WHERE task_id=?', (old_tid,))}
    selected = max(steps, key=lambda s: times[s['receipt']['attempt_id']])
    response, receipt = (deepcopy(selected['response']), selected['receipt'])
    old_components, new_components = (old['uncertainty']['components'], record['uncertainty']['components'])
    if len(old_components) != len(new_components):
        raise DomainError('SEMANTIC_REPLAY_INPUT_CHANGED', '回归误差分量发生变化')
    ids = {a['component_id']: b['component_id'] for a, b in zip(old_components, new_components)}
    for component in response.get('uncertainty', []):
        component['component_id'] = ids[component['component_id']]
    proof = {'source_task_id': old_tid, 'response_hash': content_hash(selected), 'actual_attempt_id': receipt['attempt_id'], 'new_api_call': False, 'component_id_map': ids}
    return (response, receipt, proof)

def saved_job_proposal(repo, conn, job):
    attempts = {r['attempt_id']: r['created_at'] for r in conn.execute("SELECT attempt_id,created_at FROM attempts WHERE task_id=? AND job_id=? AND owner='M08'", (job['task_id'], job['job_id']))}
    steps = [s for s in repo.objects(conn, job['task_id'], 'job_step') if s.get('kind') == 'model' and s.get('receipt', {}).get('operation') == 'source_conditions' and (s.get('receipt', {}).get('profile') == VERSION) and (s['receipt']['attempt_id'] in attempts)]
    if not steps:
        return None
    latest = max(steps, key=lambda s: attempts[s['receipt']['attempt_id']])
    from ..scientific_conditions import expand_semantic_wire
    response=expand_semantic_wire(latest['response'],latest['bindings']) if latest.get('bindings') else latest['response']
    return (response, latest['receipt'])

class ScientificConditionsMixin:

    async def scientific_permission(self, job, spec, binding, record, interpretation, release, source_parameters):
        from astroquery_ai.registry.science_conditions import bound_condition_records, condition_summary
        candidates=bound_condition_records(release,binding)
        if not candidates:return (None,None)
        branches=binding.get('science_branches',[])
        primary=spec['target'].get('primary_otype')
        preferred={b['science_ref']['content_sha256'] for b in branches if primary in b.get('otypes',[])}
        candidates.sort(key=lambda c:(c['content_sha256'] not in preferred,c['record_id']))
        evaluated=[];first=None
        for science in candidates:
            scoped={**binding,'science_ref':condition_summary(science)['record_ref'],
                    'science_conditions':condition_summary(science)}
            permission,semantics=await self._scientific_permission_record(job,spec,scoped,record,interpretation,
                release,source_parameters,science)
            evaluated.append({'science_ref':scoped['science_ref'],'allowed':permission['allowed'],
                              'reason':permission['reason']})
            permission={**permission,'science_record_ref':scoped['science_ref']}
            if first is None:first=(permission,semantics)
            if permission['allowed']:
                permission['condition_branch_evaluations']=evaluated
                return permission,semantics
        first[0]['condition_branch_evaluations']=evaluated
        return first

    async def _scientific_permission_record(self, job, spec, binding, record, interpretation, release, source_parameters, science):
        if not release.get('science'):
            return (None, None)
        if science is None:
            return (None, None)
        tid = job['task_id']
        with self.repo.read() as conn:
            context = self.repo.object(conn, tid, 'context', record['context_ref']['id'], record['context_ref']['version'])
            source = self.repo.object(conn, tid, 'source', record['source_ref']['id'], record['source_ref']['version'])
            evidence = self.repo.object(conn, tid, 'evidence', record['evidence_refs'][0]['id'], record['evidence_refs'][0]['version'])
            admission = self.repo.object(conn, tid, 'admission', record['admission_receipt_ref']['id'], record['admission_receipt_ref']['version'])
            trial = verification_scope(self.repo, conn, tid, spec)
            bounded_call = trial is not None and (not trial.get('production_processing'))
            previous = [c for c in self.repo.objects(conn, tid, 'science_condition_check') if c['source_hash'] == record['content_sha256'] and c['science_record_hash'] == science['content_sha256']]
        artifact, _ = self.app.artifacts.read_owned(tid, evidence['artifact_ref']['id'])
        provenance = artifact['sha256'] == evidence['artifact_ref']['content_sha256'] and content_hash(context) == record['context_ref']['content_sha256'] and (content_hash(admission) == record['admission_receipt_ref']['content_sha256']) and (context['measurement_ref'] == {'id': record['measurement_id'], 'version': record['revision']}) and (context['snapshot_binding']['property'] == record['property_ref'])
        spans = carried_science_spans(self.app, tid, release, evidence, interpretation, source)
        if provenance:
            receipt = {'source_artifact': evidence['artifact_ref'], 'source': record['source_ref'], 'target': record['target_ref'], 'native_locator': evidence['locator'], 'native_unit': record['unit'], 'native_unit_declaration': record.get('unit_declaration'), 'target_unit': binding['output_profile'].get('unit'), 'scope': 'Verified saved-source identity/ownership/locator only; physical measurand and applicable scientific contexts still require original evidence. Native and target units may differ.'}
            spans.append({'span_id': 'server-binding-' + digest(receipt), 'origin': 'verified_repository_binding', 'text': canonical(receipt).decode()})
        previous = [c for c in previous if c.get('consumer_revision') == CONSUMER_REVISION and set(c.get('span_hashes', {}).values()) == {digest(s['text']) for s in spans}]
        if previous:
            semantics, attempt = (previous[-1], None)
        else:
            payload = semantic_prompt(science, binding, record, source, context, interpretation, spans)
            replay = None
            from astroquery_ai.runtime.run_policy import consolidated
            from ..quality_facts import reusable_response
            reused=reusable_response(science,record,interpretation,spans) if consolidated(spec) else None
            reused_checks={x['key']:x for x in reused['checks']} if reused else {}
            if reused:
                payload['verified_quality_facts']=reused
                payload['response_template']['checks']=[x for x in payload['response_template']['checks'] if x['key'] not in reused_checks]
                payload['requirements']=[x for x in payload['requirements'] if x['key'] not in reused_checks]
                payload['instruction']+=' Already verified_quality_facts are immutable facts of this same source/candidate; inspect ONLY missing conversion conditions. Do not repeat their admission.'

            async def request(proposal):
                from ..scientific_conditions import semantic_wire, expand_semantic_wire
                wire,bindings=semantic_wire(proposal,record)
                response,receipt=await self.steps.model(job, task_id=tid, owner='M08', root_id=record['measurement_id'] + ':science:' + science['content_sha256'][:16], messages=[{'role': 'user', 'content': canonical(wire).decode()}], bindings=bindings, profile=self.model_profile('M08', version=VERSION, operation='source_conditions', max_output_tokens=8192, max_images=0, max_input_tokens=96000), job=job, purpose='verification' if bounded_call else 'production', root_limit=3)
                response=expand_semantic_wire(response,bindings)
                if reused and isinstance(response,dict):
                    response['checks']=[*reused['checks'],*[x for x in response.get('checks',[]) if x.get('key') not in reused_checks]]
                    response['uncertainty']=reused['uncertainty']
                return response,receipt
            if trial and trial.get('replay_semantics_from'):
                with self.repo.read() as conn:
                    response, attempt, replay = replay_verified_response(self.repo, conn, trial['replay_semantics_from'], record, interpretation)
            elif reused and not payload['response_template']['checks']:
                response,attempt=reused,None
            else:
                try:
                    response, attempt = await request(payload)
                except DomainError as exc:
                    if exc.code not in {'INVALID_MODEL_JSON', 'INCOMPLETE_MODEL_RESPONSE'}:
                        raise
                    response, attempt = await request({**payload, 'format_retry': exc.code, 'retry_instruction': 'One complete compact JSON object only. Unique keys. All checks, concise evidence ID arrays, only supported contexts. No prose outside JSON, no repeated definitions, no quotation fields.'})
            format_issue = None
            degraded = None
            degraded_contexts, repair_comparison = ([], False)
            semantics = None
            try:
                semantics = checked_semantics(response, science, record, spans)
                degraded = [c['key'] for c in response['checks'] if c.get('state') == 'supported' and semantics['checks'].get(c['key'], {}).get('state') != 'supported']
                if degraded:
                    format_issue = 'Unverified anchor rendering for: ' + ', '.join(degraded)
                degraded_contexts = [i['key'] for i in response.get('contexts', []) if isinstance(i, dict) and i.get('state') in {'known', 'not_applicable'} and (semantics['contexts'].get(i.get('key'), {}).get('state') == 'unknown')]
                comparison = response.get('comparison_prerequisites') or {}
                checked_comparison = semantics['comparison_prerequisites']
                repair_comparison = comparison.get('state') == 'identified' and checked_comparison['state'] == 'unresolved' and (set(checked_comparison['missing_context_keys']) <= set(degraded_contexts))
                if degraded_contexts or repair_comparison:
                    format_issue = (format_issue or '') + '; unverified context/comparison citation'
            except DomainError as exc:
                if exc.code != 'SCIENCE_SEMANTIC_SCHEMA':
                    raise
                format_issue = exc.code
            missing_components = [c['component_id'] for c in record['uncertainty']['components'] if semantics is None or c['component_id'] not in semantics['uncertainty']]
            if missing_components:
                format_issue = (format_issue or '') + '; missing component response IDs'
            if format_issue:
                repair_keys = degraded or ([c['key'] for c in payload['response_template']['checks']] if semantics is None else [])
                template, schema = ({}, {})
                if repair_keys:
                    template['checks'] = [c for c in payload['response_template']['checks'] if c['key'] in repair_keys]
                    schema['checks'] = payload['response_schema']['checks']
                if missing_components:
                    template['uncertainty'] = [c for c in payload['response_template']['uncertainty'] if c['component_id'] in missing_components]
                    schema['uncertainty'] = payload['response_schema']['uncertainty']
                if degraded_contexts:
                    template['contexts'] = [{'key': key, 'state': 'unknown', 'value': None, 'anchors': [], 'reason': 'Recheck only this context against the actual supplied source spans'} for key in degraded_contexts]
                    schema['contexts'] = payload['response_schema']['contexts']
                if repair_comparison:
                    template['comparison_prerequisites'] = payload['response_template']['comparison_prerequisites']
                    schema['comparison_prerequisites'] = payload['response_schema']['comparison_prerequisites']
                repair_payload = {k: v for k, v in payload.items() if k not in {'response_schema', 'response_template', 'output_contract', 'instruction'}}
                repair_payload.update(format_issue=format_issue, repair_keys=repair_keys, repair_component_ids=missing_components, response_template=template, response_schema=schema, instruction='Return only requested sections and identities in response_template. Use actual supplied source span ID strings, never reported_context labels as citations. Recheck scientific facts from those spans; keep absent facts unknown. Do not change values or sibling verdicts, infer equality, or relax comparison conditions. Reasons under 180 characters.')
                repaired, repaired_attempt = await request(repair_payload)
                merged = merge_semantic_repair(response, semantics, repaired, repair_keys, missing_components, degraded_contexts, repair_comparison)
                semantics = checked_semantics(merged, science, record, spans)
                attempt = repaired_attempt
                semantics['format_repair'] = {'reason': format_issue, 'previous_response_hash': content_hash(response)}
            core = ('source_subject_quantity_evidence_verified', 'source_native_main_coordinate_evidenced', 'source_main_state_interpreted')
            if not replay and (not format_issue) and all((semantics['checks'].get(k, {}).get('state') == 'supported' for k in core)) and (semantics['checks'].get('source_required_context_verified', {}).get('state') == 'unknown'):
                retry = {**payload, 'previous_context_assessment': semantics['checks']['source_required_context_verified'], 'response_template': {'checks': [c for c in payload['response_template']['checks'] if c['key'] == 'source_required_context_verified']}, 'response_schema': {'checks': payload['response_schema']['checks']}, 'instruction': 'Return JSON. Recheck only source_required_context_verified for MAIN operation eligibility once. Return ONLY that one checks item, with actual evidence span IDs. Other verified checks, error interpretations and comparison prerequisites are retained separately. Evaluate each context using its own scope and on_missing policy. If unknown_preserves_main=true, keep that context unknown but do not treat its absence as a failed MAIN prerequisite. Unknown timing/epoch/model permitted for pure same-quantity unit scaling remains a strict-comparison limitation, not a missing unit-scaling prerequisite. If a genuinely mandatory physical context is absent, keep unknown and name that exact blocking context. Never invent a timing value, assume applicability, demand internal file hashes in the paper, or copy an old source branch. Do not return contexts/uncertainty/comparison arrays or change other verdicts.'}
                repaired, attempt = await request(retry)
                merged = merge_semantic_repair(response, semantics, repaired, ['source_required_context_verified'], [])
                semantics = checked_semantics(merged, science, record, spans)
                semantics['main_context_recheck'] = True
                semantics['main_context_recheck_scope'] = ['source_required_context_verified']
            contract = science.get('source_specific_uncertainty_contract') or {}
            declared = contract.get('reported_error') or {}
            document = source.get('metadata', {}).get('catalog_document') or {}
            evidence_ids = {ref['id'] for ref in contract.get('evidence_refs', [])}
            matching_documents = [release['objects'][key] for key in evidence_ids if key in release['objects'] and release['objects'][key].get('artifact_sha256') == document.get('artifact_ref', {}).get('content_sha256')]
            if matching_documents and contract.get('point_limit_state') == 'unresolved_from_numeric_VOTable_alone' and (interpretation['proposal'].get('column') in science.get('source_specific_raw_preservation', {}).get('source_columns', [])):
                semantics['checks']['source_main_state_interpreted'] = {'key': 'source_main_state_interpreted', 'state': 'unknown', 'reason': 'exact_reviewed_source_point_limit_selection_unresolved', 'previous_model_interpretation': semantics['checks'].get('source_main_state_interpreted'), 'contract_ref': binding['science_ref'], 'source_document_ref': document['artifact_ref']}
                semantics['source_only_limitation'] = {'reason': 'source_point_limit_selection_unresolved', 'raw_source_retained': True, 'numeric_point_admitted': False, 'contract_ref': binding['science_ref']}
            if matching_documents and declared.get('statistical_meaning') == 'reported_error' and declared.get('amplitude_unit_scale') and declared.get('source_label'):
                field = declared.get('field')
                field_spans = document.get('parsed', {}).get('fields', {}).get(field, [])
                if len(field_spans) == 1 and declared['source_label'] in field_spans[0]['text']:
                    from ..units import decimal_unit_factor
                    from decimal import Decimal
                    try:
                        same_scale = decimal_unit_factor(field_spans[0]['unit_token'], '1') == Decimal(declared['amplitude_unit_scale'])
                    except (ValueError, TypeError):
                        same_scale = False
                    proposals = interpretation['proposal']['errors']
                    for component in record['uncertainty']['components'] if same_scale else []:
                        if any((p['location'] == field and p['raw_text'] == component['raw_text'] for p in proposals)):
                            prior = semantics['uncertainty'].get(component['component_id'])
                            semantics['uncertainty'][component['component_id']] = {'disposition': 'eligible', 'reason': 'exact_reviewed_source_absolute_amplitude_contract', 'previous_model_interpretation': prior, 'contract_ref': binding['science_ref'], 'source_document_ref': document['artifact_ref'], 'field': field, 'confidence_and_role_preserved_without_default': True}
            semantics['consumer_revision'] = CONSUMER_REVISION
            semantics['check_id'] = 'science-check-' + digest({'source': record['content_sha256'], 'science': science['content_sha256'], 'execution': VERSION, 'assessment': content_hash(semantics)})
            semantics['attempt_ref'] = attempt
            if reused:
                semantics['unified_quality_reuse']=reused['unified_quality_ref']
                semantics['new_condition_model_required']=attempt is not None
            if replay:
                semantics['replayed_real_response'] = replay
            semantics['content_sha256'] = content_hash(semantics)
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                current = self.repo.object(conn, tid, 'measurement', record['measurement_id'])
                if current['content_sha256'] != record['content_sha256']:
                    raise DomainError('NORMALIZATION_SOURCE_CHANGED', '条件判断不能应用于已变化的输入')
                self.repo.put_object(conn, tid, 'science_condition_check', semantics['check_id'], 1, semantics)
        permission = operation_permission(science, binding, record, source_parameters, semantics, provenance_verified=provenance)
        if permission['allowed']:
            with self.repo.read() as conn:
                runtime = operation_eligibility(self.app, conn, tid, spec, permission['operation'], record=record)
            permission['software_eligibility'] = runtime
            if not runtime['allowed']:
                permission.update(allowed=False, reason=runtime['reason'])
        return (permission, semantics)
