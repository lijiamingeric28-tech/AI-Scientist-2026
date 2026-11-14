"""One bounded interpretation attempt before creating a NEW optional-error review.

Existing questions and human answers are protected both before dispatch and at
commit. This handler has no authority to answer or close a review.
"""
from copy import deepcopy
import re

import httpx
from pydantic import ValidationError

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, utcnow
from astroquery_ai.runtime.errors import DomainError
from ..uncertainty_interpretation import OPERATION, VERSION, available_spans, prompt, validate_response
from ..uncertainty_wire import propose_with_one_repair


def human_protected(repo, conn, tid, record, interpretation):
    mid = record['measurement_id']
    if interpretation.get('human_answer_ref'):
        return True
    for row in conn.execute('SELECT payload FROM reviews WHERE task_id=?', (tid,)):
        question = loads(row[0])
        if mid in question['scope'].get('measurement_ids', []):
            return True
        for cid in question['scope'].get('candidate_ids', []):
            candidate = repo.object(conn, tid, 'candidate', cid)
            if (candidate.get('current_measurement_ref') or {}).get('id') == mid:
                return True
    return any(d.get('answer_ref') and (d.get('measurement_ref') or {}).get('id') == mid
               for d in repo.objects(conn, tid, 'admission_disposition'))


class UncertaintyInterpretationMixin:
    def uncertainty_source_spans(self, tid, spec, evidence, interpretation, source):
        from .scientific_conditions_service import carried_science_spans
        release = self.app.registry.load(spec['registry_release']['id'])
        spans = available_spans(evidence, interpretation, source)
        existing = {s['span_id'] for s in spans}
        for span in carried_science_spans(self.app, tid, release, evidence, interpretation, source):
            if (span['span_id'] not in existing and span['origin'] == 'exact_reviewed_source_excerpt'
                    and re.search(r'\buncertaint|\berrors?\b|\bconfidence\b|\bsigma\b|σ|\brms\b', span['text'], re.I)):
                spans.append({**span, 'locator': span['evidence_ref']})
        return spans

    def source_error_details_missing(self, conn, tid, record, interpretation):
        source = self.repo.object(conn, tid, 'source', record['source_ref']['id'], record['source_ref']['version'])
        metadata = source.get('metadata', {})
        columns = {c['name']: c for c in metadata.get('columns', [])}
        parsed = (metadata.get('catalog_document') or {}).get('parsed', {})
        general = parsed.get('catalog_scope', {}).get('text', '')
        if source.get('reviewed_source_evidence_refs'):
            evidence = self.repo.object(conn, tid, 'evidence', record['evidence_refs'][0]['id'], record['evidence_refs'][0]['version'])
            carried = self.uncertainty_source_spans(tid, self.spec(conn, tid), evidence, interpretation, source)
            general += '\n' + '\n'.join(s['text'] for s in carried if s['origin'] == 'exact_reviewed_source_excerpt')
        requested = []
        for component, proposal in zip(record['uncertainty']['components'], interpretation['proposal']['errors']):
            if component['interpretation_state'] != 'parsed':
                continue  # Source-coded unknowns first need their scientific disposition.
            name = proposal['location'] if proposal['location'] in columns else proposal['location'].split('/')[0]
            local = columns.get(name, {}).get('description', '') or ''
            local += ' '.join(span['text'] for span in parsed.get('fields', {}).get(name, []))
            if component['role'] == 'unspecified' and re.search(r'\bstatistical\b|\bsystematic\b', local, re.I):
                requested.append(component['component_id'])
            elif component['level'] is None and re.search(r'\bsigma\b|σ|\bconfidence\b|\bcredible\b', local + '\n' + general, re.I):
                requested.append(component['component_id'])
        return requested

    def _error_receipt(self, conn, tid, record):
        matches = [r for r in self.repo.objects(conn, tid, 'uncertainty_interpretation_receipt')
                   if r['measurement_id'] == record['measurement_id']
                   and record['content_sha256'] in {r['input_hash'], r.get('output_hash')}]
        return matches[-1] if matches else None

    def _error_capable(self, conn, tid=None):
        if tid:
            from astroquery_ai.runtime.science_capabilities import verification_scope
            task = self.repo.task(conn, tid)
            if task['query_ref']:
                ref = loads(task['query_ref'])
                spec = self.repo.object(conn, tid, 'confirmed_query', ref['id'], ref['version'])
                scope = verification_scope(self.repo, conn, tid, spec)
                if scope and not scope.get('production_processing') and any(e['owner'] == 'M08' and e['version'] == VERSION and e['operation'] == OPERATION for e in scope.get('model_executions', [])):
                    return True
        pilot = getattr(self.app, 'pilot', None)
        if tid and pilot and getattr(pilot, 'error_interpretation_capable', lambda *args: False)(tid, VERSION):
            return True
        row = conn.execute("SELECT payload FROM settings WHERE key='profile:M08'").fetchone()
        if not row:
            return False
        setting = loads(row[0])
        if setting.get('synthetic'):
            return (self.app.registry.allow_synthetic and setting.get('state') == 'validated'
                    and setting.get('uncertainty_interpretation_enabled') is True)
        try:
            report, _ = self.app.profile_authority.load(conn, 'M08')
        except DomainError:
            return False
        executions = report.get('execution_profiles', []) if report['schema_version'].endswith('/2') else [report.get('execution', {})]
        if not isinstance(executions, list) or not all(isinstance(e, dict) for e in executions):
            return False
        return any(OPERATION in e.get('operations', []) and e.get('version') == VERSION
                   and e.get('model') == 'qwen3.8-flash' and e.get('thinking') is False
                   for e in executions)

    def defer_error_interpretation(self, conn, tid, record, interpretation, *, component_ids=None):
        if (not self._error_capable(conn, tid) or self._error_receipt(conn, tid, record)
                or human_protected(self.repo, conn, tid, record, interpretation)):
            return False
        self.repo.enqueue(conn, tid, 'M08', 'interpret_uncertainty', {
            'measurement_id': record['measurement_id'], 'source_hash': record['content_sha256'],
            **({'component_ids': component_ids} if component_ids is not None else {}),
        })
        return True

    def error_needs_review(self, conn, tid, record):
        # An optional interpretation outcome alone supplies neither a specific
        # scientific proposition nor grounded alternatives. Keep it unknown.
        # Actual source contradictions use the evidence-bound source-owner
        # review_issue route, rather than this former generic fallback.
        return False

    def error_review_details(self, conn, tid, record, unresolved):
        receipt = self._error_receipt(conn, tid, record)
        if receipt is None:
            return unresolved, ''
        questions = [o for o in receipt['outcomes'] if o['outcome'] == 'needs_review']
        ids = {o['source_component_id'] for o in questions}
        return ([c for c in unresolved if c['component_id'] in ids],
                '\n待核实：' + '\n'.join(o['reason'] for o in questions) if questions else '')

    async def interpret_uncertainty(self, job):
        tid, mid = job['task_id'], job['payload']['measurement_id']
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            record = self.repo.object(conn, tid, 'measurement', mid)
            interpretation = self.repo.object(conn, tid, 'interpretation', record['interpretation_ref']['id'], record['interpretation_ref']['version'])
            if (record['content_sha256'] != job['payload']['source_hash']
                    or human_protected(self.repo, conn, tid, record, interpretation)):
                self.repo.event(conn, tid, 'error_interpretation_not_applied', {
                    'job_id': job['job_id'], 'reason': 'source_changed_or_human_protected'})
                self.repo.enqueue(conn, tid, 'M08', 'normalize', {
                    'measurement_id': mid, 'source_hash': record['content_sha256']})
                self.repo.finish_job(conn, job)
                return
            spec = self.spec(conn, tid)
            evidence = self.repo.object(conn, tid, 'evidence', record['evidence_refs'][0]['id'], record['evidence_refs'][0]['version'])
            source = self.repo.object(conn, tid, 'source', record['source_ref']['id'], record['source_ref']['version'])
            artifact = self.app.artifacts.read_owned(tid, evidence['artifact_ref']['id'])[0]
            spans = self.uncertainty_source_spans(tid, spec, evidence, interpretation, source)
            capable = self._error_capable(conn, tid)
            component_ids = job['payload'].get('component_ids')
            from astroquery_ai.runtime.science_capabilities import verification_scope
            verification = verification_scope(self.repo, conn, tid, spec)
        response, attempt, new_proposal, parents = None, None, None, {}
        proposal_sequence = []
        outcomes = []
        status, reason = 'not_checked', 'profile_not_qualified' if not capable else 'carried_evidence_unavailable'
        if capable and spans:
            try:
                def dispatch_guard(conn, attempt):
                    current = self.repo.object(conn, tid, 'measurement', mid)
                    active = self.repo.object(conn, tid, 'interpretation', current['interpretation_ref']['id'], current['interpretation_ref']['version'])
                    if (current['content_sha256'] != record['content_sha256']
                            or human_protected(self.repo, conn, tid, current, active)):
                        raise DomainError('ERROR_INTERPRETATION_SUPERSEDED', '派发前输入已变化或已有人工审核')
                async def invoke(messages):
                    return await self.steps.model(job, task_id=tid, owner='M08', root_id=mid,
                        messages=messages,
                        profile=self.model_profile('M08', version=VERSION, operation=OPERATION,
                                                   max_output_tokens=6144, max_images=0),
                        job=job, purpose='verification' if verification is not None and not verification.get('production_processing') else 'production', root_limit=3, dispatch_guard=dispatch_guard)
                response, attempt = await propose_with_one_repair(invoke, record, interpretation, spans,
                    prompt(record, interpretation, spans, component_ids=component_ids), proposal_sequence, component_ids=component_ids)
                new_proposal, outcomes, parents = validate_response(response, record, interpretation, spans, component_ids=component_ids)
                status, reason = 'checked', None
            except (ValidationError, ValueError):
                reason = 'error_interpretation_response_schema'
            except (httpx.HTTPError, TimeoutError) as exc:
                reason = type(exc).__name__
            except DomainError as exc:
                # Lifecycle/budget/lease guards retain their existing scheduler
                # handling. Ordinary optional interpretation failures stay local.
                if not (exc.code.startswith(('ERROR_INTERPRETATION_', 'MODEL_', 'PROVIDER_', 'PROFILE_'))
                        or exc.code in {'STREAM_INCOMPLETE', 'STREAM_JSON_INVALID',
                                        'INCOMPLETE_MODEL_RESPONSE', 'INVALID_MODEL_JSON'}):
                    raise
                reason = exc.code
        receipt = {'schema_version': 'UncertaintyInterpretationReceipt/1', 'receipt_id': job['job_id'],
            'measurement_id': mid, 'input_hash': record['content_sha256'], 'input_revision': record['revision'],
            'output_hash': None, 'status': status, 'reason': reason, 'outcomes': outcomes,
            'source_evidence_refs': record['evidence_refs'], 'evidence_spans': spans,
            'proposal_hash': digest(response) if response is not None else None,
            'actual_attempt_refs': [attempt] if attempt else [], 'execution_version': VERSION,
            'proposal_sequence': proposal_sequence,
            'raw_source_replaced': False, 'human_answer_created': False, 'created_at': utcnow()}
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            # Includes failed/unknown-cost calls for which no response receipt
            # was returned. The campaign ledger remains the cost authority.
            actual = []
            for row in conn.execute('SELECT attempt_id,status,receipt FROM attempts WHERE job_id=? ORDER BY created_at,attempt_id', (job['job_id'],)):
                body = loads(row['receipt']) if row['receipt'] else {}
                actual.append({'attempt_id': row['attempt_id'], 'status': row['status'],
                               'receipt_sha256': digest(body), 'model': body.get('model')})
            if actual:
                receipt['actual_attempt_refs'] = actual
            current = self.repo.object(conn, tid, 'measurement', mid)
            current_interpretation = self.repo.object(conn, tid, 'interpretation', current['interpretation_ref']['id'], current['interpretation_ref']['version'])
            if (current['content_sha256'] != record['content_sha256']
                    or human_protected(self.repo, conn, tid, current, current_interpretation)):
                receipt.update(status='not_applied', reason='source_changed_or_human_protected')
                self.repo.put_object(conn, tid, 'uncertainty_interpretation_receipt', job['job_id'], 1, receipt)
                self.repo.enqueue(conn, tid, 'M08', 'normalize', {
                    'measurement_id': mid, 'source_hash': current['content_sha256']})
                self.repo.finish_job(conn, job)
                return
            if new_proposal and new_proposal.model_dump(mode='json') != interpretation['proposal']:
                document = new_proposal.model_dump(mode='json')
                if {k: v for k, v in document.items() if k != 'errors'} != {
                        k: v for k, v in interpretation['proposal'].items() if k != 'errors'}:
                    raise DomainError('ERROR_INTERPRETATION_MAIN_CHANGED', '误差解释不能改变主值或上下文')
                verification = deepcopy(interpretation.get('paper_verification'))
                if verification:
                    # Main semantics are immutable; retain the exact old check
                    # and explicitly bind inheritance, rather than re-querying it.
                    verification['proposal_hash'] = digest(document)
                    verification['main_admission_inherited_from'] = record['admission_receipt_ref']
                    verification['uncertainty_revision_basis'] = record['content_sha256']
                result = self.extractor.assemble(spec=spec, source=source, artifact=artifact,
                    proposal=new_proposal, owner=interpretation['producer'], batch_id=job['job_id'],
                    allowed_pages=[document['page']], matched_rows=[document['row']],
                    revision=record['revision'] + 1, measurement_id_override=mid,
                    paper_verification=verification,
                    object_binding_ref=evidence.get('object_binding_ref'),
                    component_parent_ids={location: parent for location, parent in parents.items()
                                          if list(parents.values()).count(parent) > 1})
                if result['state'] == 'admitted':
                    # Shared admission checks must also leave main semantics and
                    # references exactly intact. There is no general overwrite path.
                    updated = result['measurement']
                    protected = ('measurement_id', 'task_id', 'query_ref', 'target_ref', 'property_ref',
                                 'source_ref', 'value', 'raw_value', 'unit', 'representation', 'limit')
                    if any(updated[k] != record[k] for k in protected):
                        raise DomainError('ERROR_INTERPRETATION_MAIN_CHANGED', '复检不能改变已准入主值')
                    self.context.store_admitted(conn, tid, result)
                    receipt.update(status='applied', output_hash=updated['content_sha256'],
                        output_revision=updated['revision'], output_interpretation_ref=updated['interpretation_ref'])
                    receipt['original_components'] = record['uncertainty']['components']
                    # Full parent/child mapping includes untouched components.
                    receipt['component_lineage'] = [
                        {'parent_component_id': c['component_id'],
                         'child_component_ids': [n['component_id'] for n, error in zip(updated['uncertainty']['components'], document['errors'])
                             if parents.get(error['location'], n['component_id']) == c['component_id']]}
                        for c in record['uncertainty']['components']]
                else:
                    receipt.update(status='not_applied', reason=result.get('reason'))
            self.repo.put_object(conn, tid, 'uncertainty_interpretation_receipt', job['job_id'], 1, receipt)
            if receipt['status'] != 'applied' or any(o['outcome'] != 'parsed' for o in outcomes):
                self.repo.put_object(conn, tid, 'coverage', 'optional-error-' + job['job_id'], 1, {
                    'owner': 'M08', 'state': 'partial', 'measurement_id': mid,
                    'reason': receipt['reason'] or 'optional_error_interpretation_unresolved',
                    'input_hash': record['content_sha256'], 'outcomes': outcomes,
                    'main_value_retained': True, 'receipt_id': job['job_id']})
            self.repo.enqueue(conn, tid, 'M07', 'assess_batch', {
                'measurement_ids': [mid], 'candidate_ids': [], 'batch_id': job['job_id']})
            self.repo.event(conn, tid, 'error_interpretation_completed', {
                'measurement_id': mid, 'status': receipt['status'], 'reason': receipt['reason']})
            self.repo.finish_job(conn, job)
