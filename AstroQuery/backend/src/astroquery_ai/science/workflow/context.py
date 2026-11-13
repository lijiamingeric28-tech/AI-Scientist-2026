'Frozen inputs and atomic source batches; no second task state.'

from __future__ import annotations

from astroquery_ai.runtime.calls import ModelProfile

from astroquery_ai.runtime.codec import digest, loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.science.measurements.assembly import EvidenceExtractor

from astroquery_ai.science.measurements.contracts import evidence_ref

class ScienceContext:

    def __init__(self, app):
        self.app, self.repo = (app, app.repository)
        from astroquery_ai.runtime.checkpoints import JobSteps
        self.steps, self.extractor = (JobSteps(app), EvidenceExtractor(app))

    def spec(self, conn, tid):
        task = self.repo.task(conn, tid)
        self.repo.guard_definitions(conn, task)
        reference = loads(task['query_ref'])
        result = self.repo.object(conn, tid, 'confirmed_query', reference['id'], reference['version'])
        if result['spec_hash'] != digest({k: v for k, v in result.items() if k != 'spec_hash'}):
            raise DomainError('FROZEN_SPEC_CORRUPT', '冻结规格哈希不匹配')
        return result

    def model_profile(self, owner, model='qwen3.8-flash', **kwargs):
        kwargs.setdefault('operation', {'M03': 'catalog_header', 'M06': 'paper_batch', 'M08': 'same_quantity', 'M11': 'insights'}.get(owner, 'unspecified'))
        kwargs.setdefault('source_format', {'M03': 'votable', 'M06': 'pdf', 'M08': 'typed_measurement', 'M11': 'science_snapshot'}.get(owner, 'unspecified'))
        return ModelProfile(model=model, thinking=False, state=self.app._profile_state(owner), **kwargs)

    def commit_candidates(self, conn, tid, results, batch_id):
        admitted, candidates, legacy_candidates = ([], [], [])
        for result in results:
            if result['state'] == 'rejected':
                rejection = {**result, 'batch_id': batch_id, 'raw_evidence_retained': True}
                self.repo.put_object(conn, tid, 'rejection', 'source-negative-' + digest(rejection), 1, rejection)
                continue
            if result['state'] == 'admitted':
                record = result['measurement']
                prior = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='measurement' AND object_id=? ORDER BY version DESC LIMIT 1", (tid, record['measurement_id'])).fetchone()
                if prior:
                    old = loads(prior[0])
                    base=result.get('quality_recheck_base_ref')
                    quality=result['interpretation'].get('quality_verification',{})
                    authorized_recheck=False
                    if base and quality.get('state')=='supported' and quality.get('model_attempt_ref'):
                        old_interp=self.repo.object(conn,tid,'interpretation',old['interpretation_ref']['id'],old['interpretation_ref']['version'])
                        candidate_ref=quality.get('candidate_ref',{})
                        checked=self.repo.object(conn,tid,'candidate',candidate_ref['id'],candidate_ref['version'])
                        from astroquery_ai.runtime.codec import content_hash
                        authorized_recheck=(base=={'id':old['measurement_id'],'version':old['revision'],'content_sha256':old['content_sha256']}
                            and record['revision']==old['revision']+1 and not old_interp.get('human_answer_ref')
                            and checked.get('current_measurement_ref')==base and checked.get('comparison_problem')
                            and content_hash(checked)==candidate_ref['content_sha256'])
                    if (result['interpretation'].get('human_answer_ref') and record['revision'] == old['revision'] + 1) or authorized_recheck:
                        pass
                    else:
                        old_interpretation = self.repo.object(conn, tid, 'interpretation', old['interpretation_ref']['id'], old['interpretation_ref']['version'])

                        def semantic(proposal):
                            value = {k: v for k, v in proposal.items() if k not in {'page', 'row', 'column', 'location_label', 'source_quote', 'ambiguity', 'local_admission', 'source_quality', 'quantity_match', 'catalog_quantity_evidence'}}
                            value.setdefault('source_references', [])
                            return value
                        if semantic(old_interpretation['proposal']) == semantic(result['interpretation']['proposal']):
                            evidence = result['evidence']
                            self.repo.put_object(conn, tid, 'evidence', evidence['evidence_id'], 1, evidence)
                            interpretation = result['interpretation']
                            self.repo.put_object(conn, tid, 'interpretation', interpretation['interpretation_id'], interpretation['revision'], interpretation)
                            check = {**result['source_check'], 'measurement_version': old['revision'], 'measurement_content_sha256': old['content_sha256']}
                            check.pop('check_id', None)
                            check['check_id'] = 'source-check-' + digest(check)
                            self.repo.put_object(conn, tid, 'source_check', check['check_id'], 1, check)
                            for statement in result.get('source_statements', []):
                                self.repo.put_object(conn, tid, 'source_statement', statement['statement_id'], 1, statement)
                            mention = {'measurement_id': old['measurement_id'], 'current_measurement_hash': old['content_sha256'], 'batch_id': batch_id, 'evidence_ref': evidence_ref(evidence, 'evidence_id'), 'relation': 'same_source_same_interpretation', 'interpretation_ref': evidence_ref(interpretation, 'interpretation_id'), 'source_statement_refs': [evidence_ref(s, 'statement_id') for s in result.get('source_statements', [])]}
                            self.repo.put_object(conn, tid, 'source_mention', 'mention-' + digest(mention), 1, mention)
                            continue
                        assembly = dict(result['assembly_context'])
                        assembly.update(revision=old['revision'] + 1, measurement_id_override=old['measurement_id'])
                        result = {'state': 'review_candidate', 'reason': '同一来源位置存在不同解释，请依据原件核对；不会覆盖已有解释。', 'proposal': result['interpretation']['proposal'], 'evidence': result['evidence'], 'evidence_ref': evidence_ref(result['evidence'], 'evidence_id'), 'assembly_context': assembly, 'current_measurement_ref': {'id': old['measurement_id'], 'version': old['revision'], 'content_sha256': old['content_sha256']}}
            if result['state'] == 'admitted':
                self.store_admitted(conn, tid, result)
                admitted.append(result['measurement']['measurement_id'])
            else:
                cid = 'candidate-' + digest({'batch': batch_id, 'proposal': result['proposal']})
                self.repo.put_object(conn, tid, 'candidate', cid, 1, {**result, 'candidate_id': cid})
                from astroquery_ai.runtime.run_policy import consolidated
                if consolidated(result.get('assembly_context',{}).get('spec',{})):
                    from astroquery_ai.runtime.codec import content_hash
                    candidate={**result,'candidate_id':cid}
                    root=result.get('quality_root_id') or cid
                    current_ref={'id':cid,'version':1,'content_sha256':content_hash(candidate)}
                    self.repo.put_object(conn,tid,'quality_candidate_link',cid,1,
                        {'candidate_ref':current_ref,'root_id':root,'parent_ref':result.get('quality_parent_candidate_ref')})
                    if not conn.execute("SELECT 1 FROM objects WHERE task_id=? AND kind='quality_candidate_root' AND object_id=?",
                                        (tid, root)).fetchone():
                        assembly=result['assembly_context']
                        self.repo.put_object(conn,tid,'quality_candidate_root',root,1,{'root_id':root,'initial_ref':current_ref,
                            'source_id':assembly['source']['source_id'],'property_id':result['proposal']['property_id'],
                            'initial_batch_id':batch_id,'required':True})
                else:
                    legacy_candidates.append(cid)
                if result.get('evidence'):
                    evidence = result['evidence']
                    self.repo.put_object(conn, tid, 'evidence', evidence['evidence_id'], 1, evidence)
                assembly = result.get('assembly_context', {})
                origin = conn.execute('SELECT kind FROM jobs WHERE task_id=? AND job_id=?', (tid, assembly.get('batch_id'))).fetchone()
                if assembly.get('owner') == 'M06' and origin and (origin['kind'] == 'paper_batch') and (not result.get('current_measurement_ref')):
                    from astroquery_ai.runtime.codec import content_hash
                    candidate = {**result, 'candidate_id': cid}
                    pending = {'candidate_id': cid, 'candidate_ref': {'id': cid, 'version': 1, 'content_sha256': content_hash(candidate)}, 'owner': 'M06', 'source_id': assembly['source']['source_id'], 'reason': 'whole_source_owner_check_before_human'}
                    self.repo.put_object(conn, tid, 'candidate_pre_review_pending', cid, 1, pending)
                candidates.append(cid)
        # Unified candidates already belong to the source/property quality
        # planner. Legacy assessment deliberately ignores them. Enqueuing it
        # anyway creates one empty job per initial batch ahead of real checks.
        # Admitted records still use this handler to enqueue normalization.
        if admitted or legacy_candidates:
            self.repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': admitted, 'candidate_ids': legacy_candidates, 'batch_id': batch_id})
        self.repo.event(conn, tid, 'batch_committed', {'batch_id': batch_id, 'admitted_count': len(admitted), 'candidate_count': len(candidates)})

    def store_admitted(self, conn, tid, result):
        """Storage only; callers must pass admission and revision authority checks."""
        record = result['measurement']
        old_row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='measurement' AND object_id=? ORDER BY version DESC LIMIT 1", (tid, record['measurement_id'])).fetchone()
        if old_row and result['source_check']['state'] != 'checked':
            old = loads(old_row[0])
            original = self.repo.object(conn, tid, 'interpretation', old['interpretation_ref']['id'], old['interpretation_ref']['version'])
            old_evidence = self.repo.object(conn, tid, 'evidence', old['evidence_refs'][0]['id'], old['evidence_refs'][0]['version'])

            def main_semantics(proposal):
                return {k: v for k, v in proposal.items() if k not in {'errors', 'source_quality', 'local_admission', 'quantity_match', 'catalog_quantity_evidence'}}
            unchanged = record['source_ref'] == old['source_ref'] and record['property_ref'] == old['property_ref'] and (main_semantics(original['proposal']) == main_semantics(result['interpretation']['proposal'])) and all((old_evidence[k] == result['evidence'][k] for k in ('artifact_ref', 'locator', 'raw_text')))
            if unchanged:
                prior = [loads(row[0]) for row in conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='source_check' ORDER BY created_at,version", (tid,))]
                prior = [c for c in prior if c['measurement_id'] == old['measurement_id'] and c['measurement_version'] == old['revision'] and (c['state'] == 'checked')]
                if prior:
                    checked = prior[-1]
                    from astroquery_ai.runtime.codec import content_hash
                    successor = {**checked, 'measurement_version': record['revision'], 'interpretation_ref': record['interpretation_ref'], 'evidence_refs': record['evidence_refs'], 'unchanged_source_information_ref': {'id': checked['check_id'], 'version': 1, 'content_sha256': content_hash(checked)}, 'reuse_reason': 'only_error_interpretation_changed; identical_source_main_context_and_original_evidence'}
                    successor.pop('check_id', None)
                    successor['check_id'] = 'source-check-' + digest(successor)
                    result['source_check'] = successor
        objects = [('evidence', 'evidence', 'evidence_id'), ('interpretation', 'interpretation', 'interpretation_id'), ('source_unit', 'unit', 'unit_id'), ('uncertainty_record', 'uncertainty', 'uncertainty_id'), ('admission', 'admission', 'receipt_id'), ('context', 'context', 'context_id'), ('measurement', 'measurement', 'measurement_id'), ('source_check', 'source_check', 'check_id')]
        for field, kind, key in objects:
            obj = result[field]
            self.repo.put_object(conn, tid, kind, obj[key], obj.get('revision', 1), obj)
        for obj in result['component_units']:
            self.repo.put_object(conn, tid, 'unit', obj['unit_id'], 1, obj)
        for obj in result['error_bases']:
            self.repo.put_object(conn, tid, 'error_basis', obj['basis_id'], 1, obj)
        for obj in result.get('reported_references', []):
            self.repo.put_object(conn, tid, 'reported_source_ref', obj['reference_id'], 1, obj)
        for obj in result.get('source_statements', []):
            self.repo.put_object(conn, tid, 'source_statement', obj['statement_id'], 1, obj)

class ModuleService:

    def __init__(self, context):
        self.context = context
        self.app, self.repo = (context.app, context.repo)
        self.steps, self.extractor = (context.steps, context.extractor)

    def spec(self, conn, tid):
        return self.context.spec(conn, tid)

    def model_profile(self, *args, **kwargs):
        return self.context.model_profile(*args, **kwargs)

    def commit_candidates(self, *args, **kwargs):
        return self.context.commit_candidates(*args, **kwargs)
