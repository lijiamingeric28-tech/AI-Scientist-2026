"""Sparse source-owner rechecks requested by evidence-backed insight findings.

Uses the existing independent source review and local evidence verifier. The
result is a version-bound disposition/report annotation, never re-extraction,
a scientific snapshot edit, or a new human question.
"""
from collections import defaultdict
from copy import deepcopy

from pydantic import ValidationError
import httpx
from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from .measurements.contracts import MeasurementProposal
from .paper_admission import check_local_evidence, page_blocks
from .unified_quality import _paper_input, paper_item_wire, PaperQualityItem
from . import insight_boundary as boundary

STOP = {'DISPATCH_FORBIDDEN', 'HTTP_DISPATCH_FORBIDDEN', 'STALE_GENERATION', 'STALE_LEASE',
        'TASK_DELETED', 'TASK_NOT_FOUND'}


def measurement_ref(record):
    return {'id': record['measurement_id'], 'version': record['revision'],
            'content_sha256': record['content_sha256']}


def prepared_records(delivery, findings):
    records = {r['measurement_id']: r for r in delivery['measurements']}
    by_record = defaultdict(list)
    for finding in findings:
        if finding['classification'] == 'ordinary_difference': continue
        for mid in finding['measurement_ids']:
            if mid not in records:
                raise DomainError('INSIGHT_RECHECK_SCOPE', '疑点记录不属于当前科学快照')
            by_record[mid].append(finding)
    groups = defaultdict(list)
    for mid, own in by_record.items():
        record = records[mid]
        groups[(record['source_ref']['id'], record['property_ref']['id'])].append((record, own))
    return groups


def owner_status(verification):
    # These states are produced by the already existing source-evidence
    # verifier, not inferred from prose or the insight model's confidence.
    return {'rejected': 'not_supported', 'passed': 'passed'}.get(verification['state'], 'unresolved')


async def recheck(service, job, delivery, spec, findings):
    tid = job['task_id']; repo = service.repo
    results = []
    interpretations = {(i['interpretation_id'], i['revision']): i
                       for i in delivery.get('provenance_bundle', {}).get('interpretations', [])}
    sources = {s['source_id']: s for s in delivery['sources']}
    for (sid, pid), full_group in prepared_records(delivery, findings).items():
        source = sources[sid]
        for offset in range(0, len(full_group), 24):
            group = full_group[offset:offset + 24]
            key = 'insight-owner-' + digest(['read-only-owner/5', delivery['snapshot_ref'], sid, pid,
                [measurement_ref(r) for r, _ in group],
                sorted({f['finding_id'] for _, fs in group for f in fs})])
            with repo.read() as c:
                saved = [x for x in repo.objects(c, tid, 'insight_owner_recheck_checkpoint') if x['key'] == key]
            if saved:
                results.extend(saved[0]['dispositions']); continue
            if source['kind'] != 'paper':
                dispositions = [{'measurement_id': r['measurement_id'], 'measurement_ref': measurement_ref(r),
                    'finding_id': f['finding_id'], 'status': 'unresolved', 'snapshot_ref': delivery['snapshot_ref'],
                    'reason': 'this_read_only_owner_protocol_not_validated_for_source_format'}
                    for r, fs in group for f in fs]
                with repo.transaction() as c:
                    repo.validate_lease(c, job, scientific=False)
                    repo.put_object(c, tid, 'insight_owner_recheck_checkpoint', key, 1,
                                    {'key': key, 'dispositions': dispositions})
                results.extend(dispositions); continue
            binding = next(b for b in spec['properties'] if b['property_id'] == pid)
            candidates = []
            with repo.read() as c:
                index = repo.object(c, tid, 'document_index', sid)
            blocks_by_page = defaultdict(list)
            for block in page_blocks({p['page']: p['text'] for p in index['pages']}):
                blocks_by_page[block['page']].append(block)
            note_pages = {a['locator']['page'] for _, fs in group for f in fs for a in f['anchors']
                          if isinstance(a.get('locator'), dict) and isinstance(a['locator'].get('page'), int)}
            notes = [b for page in sorted(note_pages) for b in blocks_by_page[page]]
            for record, own in group:
                interpretation = interpretations[(record['interpretation_ref']['id'], record['interpretation_ref']['version'])]
                candidates.append({'proposal': deepcopy(interpretation['proposal']),
                    'comparison_problem': {'scope': 'read_only_report_owner_recheck',
                        'findings': [{'classification': f['classification'], 'issue': f['issue'],
                            'reason': f['paragraph']['text'], 'original_locations': f['anchors']} for f in own],
                        'instruction': 'Check the actual original, not the prior eligibility label. The hypothesis may be wrong. Do not create human questions or new values.'}})
            body, pages, blocks, visual = _paper_input(spec, binding, index, candidates, notes)
            compact=all(f['issue'] in {'subject','result_role'} for _,fs in group for f in fs)
            body['read_only_recheck_priority'] = {
                'requested_target':{k:spec['target'].get(k) for k in ('main_id','aliases')},
                'instruction':('Check each local reported value against this requested target, not the main object '
                    'of the paper title or the neighbouring items. A comparison/adoption can legitimately report '
                    'the requested target inside a paper about another object. Conversely a comparison star is '
                    'not the requested target merely because the article also mentions it. Determine each '
                    'numerical referent from its actual local text. Distinguish parameters held fixed/input '
                    'assumptions from fitted/estimated results even when both appear in a results table: '
                    'use the existing assumption/calibration_constant role for a fixed input, rather than '
                    'calling it a fitted result merely because it is printed. Cite actual contiguous source '
                    'text or the provided physical page; do not use ellipses as invented quotations. '
                    'Existing human answers are preserved; this review annotates the report only.')}
            if compact:body=boundary.request(body,group,candidates)
            images = []
            if visual:
                import base64
                for page in visual:
                    png = await service.app.parse_owned(tid, source['artifact']['artifact_id'], 'page_image', page=page)
                    images.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}})
            checked = {}; diagnostics = []
            original_items = body['items']
            for repair in range(2):
                body['items'] = [item for i, item in enumerate(original_items) if i not in checked]
                if not body['items']: break
                if repair: body['repair'] = {'errors': diagnostics, 'instruction': 'Repair only these unresolved protocol items against the same actual source. No new candidates.'}
                # Bind the actual gateway messages, including its required JSON
                # instruction. If that instruction is inserted after the scope
                # hash, the sealed-science guard must (correctly) reject it.
                messages = [{'role':'system','content':'Return one complete JSON object matching the requested schema.'},
                    {'role': 'user', 'content': [{'type': 'text', 'text': canonical(body).decode()}, *images] if images else canonical(body).decode()}]
                root = key + ':' + job['job_id'] + ':paper_admission'
                scope = {'job_id': job['job_id'], 'root_id': root, 'delivery_id': delivery['delivery_id'],
                    'snapshot_ref': delivery['snapshot_ref'], 'property_id': pid, 'source_id': sid,
                    'measurement_refs': [measurement_ref(r) for r, _ in group],
                    'finding_ids': sorted({f['finding_id'] for _, fs in group for f in fs}),
                    'messages_sha256': digest(messages), 'purpose': 'read_only_source_owner_recheck'}
                with repo.transaction() as c:
                    repo.validate_lease(c, job, scientific=False)
                    repo.put_object(c, tid, 'insight_owner_recheck_request', 'owner-request-' + digest(scope), 1, scope)
                try:
                    reply, receipt = await service.steps.model(job, task_id=tid, owner='M06', root_id=key,
                        messages=messages, profile=service.model_profile('M06', 'qwen3.7-plus',
                            operation='paper_admission', version=boundary.PROTOCOL if compact else 'unified-paper-quality-12', source_format='pdf',
                            max_input_tokens=96000, max_output_tokens=8192, max_images=4 if images else 0,
                            wall_seconds=480, inactivity_seconds=120), job=job, purpose='production', root_limit=2)
                    raw_items = reply.get('items', []) if isinstance(reply, dict) else []
                    if not isinstance(raw_items, list): raw_items = []
                    seen = set()
                    for raw in raw_items:
                        label = raw.get('item_id') if isinstance(raw, dict) else None
                        labels = {'I' + str(i + 1): i for i in range(len(group))}
                        if label not in labels or label in seen: continue
                        seen.add(label); i = labels[label]
                        if i in checked: continue
                        try:
                            if compact:verification=boundary.verify(raw,blocks)
                            else:
                                normalized = paper_item_wire(raw, i, visible_blocks=blocks,
                                                             proposed_unit=candidates[i]['proposal'].get('unit'))
                                item = PaperQualityItem.model_validate(normalized)
                                proposal = MeasurementProposal.model_validate(candidates[i]['proposal'])
                                verification = check_local_evidence(proposal, item.assessment, spec['target'], pages, receipt,
                                    visible_blocks=blocks, image_pages=visual, require_quantity=True,
                                    require_units=True, property_binding=binding)
                            checked[i] = {'verification': verification, 'receipt': receipt}
                        except (DomainError, ValidationError) as exc:
                            diagnostics.append({'item': label, 'code': getattr(exc, 'code', 'SOURCE_RECHECK_PROTOCOL'),
                                                'details': getattr(exc, 'details', {})})
                except DomainError as exc:
                    if exc.code in STOP: raise
                    diagnostics.append({'code': exc.code, 'details': exc.details})
                    if not exc.code.startswith(('INSIGHT_', 'INVALID_MODEL_JSON', 'INCOMPLETE_MODEL_RESPONSE', 'PROVIDER_')): break
                except (httpx.TransportError, TimeoutError) as exc:
                    diagnostics.append({'code':type(exc).__name__})
            outcomes = []
            for i, (record, _) in enumerate(group):
                verified = checked.get(i, {})
                outcomes.append({'item_ref': {'kind': 'measurement', **measurement_ref(record)},
                    'state': verified.get('verification', {}).get('state', 'not_verified'),
                    'verification': verified.get('verification', {'state': 'unresolved', 'reason': 'source_owner_check_not_completed'}),
                    'attempt_id': verified.get('receipt', {}).get('attempt_id')})
            report = {'schema_version': 'SourceRecheck/1', 'source_id': sid, 'outcomes': outcomes,
                'same_results': [], 'limitations': diagnostics, 'snapshot_ref': delivery['snapshot_ref'],
                'origin': 'insight_requested_read_only_owner_recheck', 'new_source_requests': 0}
            with repo.transaction() as c:
                repo.validate_lease(c, job, scientific=False)
                ref = repo.put_object(c, tid, 'source_recheck', key, 1, report)
                dispositions = []
                for (record, own), outcome in zip(group, outcomes):
                    interpretation = interpretations[(record['interpretation_ref']['id'], record['interpretation_ref']['version'])]
                    protected = bool(interpretation.get('human_answer_ref'))
                    status = owner_status(outcome['verification'])
                    for finding in own:
                        disposition = {'measurement_id': record['measurement_id'], 'measurement_ref': measurement_ref(record),
                            'finding_id': finding['finding_id'], 'status': status, 'snapshot_ref': delivery['snapshot_ref'],
                            'reason': outcome['verification']['reason'], 'source_recheck_ref': ref,
                            'actual_attempt_ref': outcome['attempt_id'], 'human_question_created': False,
                            'existing_human_answer_preserved':protected,'report_only':True}
                        disposition['disposition_id'] = 'disposition-' + digest(disposition)
                        repo.put_object(c, tid, 'admission_disposition', disposition['disposition_id'], 1, disposition)
                        repo.put_object(c, tid, 'post_delivery_validation', disposition['disposition_id'], 1, disposition)
                        dispositions.append(disposition)
                repo.put_object(c, tid, 'insight_owner_recheck_checkpoint', key, 1,
                                {'key': key, 'dispositions': dispositions, 'source_recheck_ref': ref})
            results.extend(dispositions)
    return results
