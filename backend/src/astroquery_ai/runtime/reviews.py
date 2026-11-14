'Persist quality questions, typed answers and separate owner applications.'

from __future__ import annotations

from typing import Literal, Annotated, Union

from pydantic import Field, model_validator

from .codec import canonical, content_hash, digest, loads, new_id, utcnow

from .errors import DomainError

from .models import Contract, Identifier, Ref, ScientificValue, TERMINAL

from astroquery_ai.science.measurements.contracts import ErrorProposal, ConditionProposal, MeasurementProposal

from astroquery_ai.registry.models import Representation

class ValueCorrection(Contract):
    type: Literal['correct_value']
    value: ScientificValue
    raw_value: str = Field(min_length=1, max_length=2048)
    evidence_ref: Ref
    quote: str = Field(min_length=1)

class UnitCorrection(Contract):
    type: Literal['correct_unit']
    unit: str = Field(min_length=1, max_length=128)
    representation: Literal['linear', 'log10', 'ln', 'magnitude']
    representation_parameters: Representation
    evidence_ref: Ref
    quote: str = Field(min_length=1)

class UncertaintyCorrection(Contract):
    type: Literal['correct_uncertainty']
    components: list[ErrorProposal]
    evidence_ref: Ref
    quote: str = Field(min_length=1)

class ContextCorrection(Contract):
    type: Literal['correct_context']
    conditions: list[ConditionProposal]
    evidence_ref: Ref
    quote: str = Field(min_length=1)

Correction = Annotated[Union[ValueCorrection, UnitCorrection, UncertaintyCorrection, ContextCorrection], Field(discriminator='type')]

def corrected_proposal(original, correction):
    """Closed typed edits. Never accept arbitrary field paths or code."""
    from copy import deepcopy
    result = deepcopy(original)
    kind = correction['type']
    if kind == 'correct_value':
        result.update(value=correction['value'], raw_value=correction['raw_value'])
    elif kind == 'correct_unit':
        result.update(unit=correction['unit'], representation=correction['representation'], representation_parameters=correction['representation_parameters'])
    elif kind == 'correct_uncertainty':
        result['errors'] = correction['components']
    elif kind == 'correct_context':
        result['conditions'] = correction['conditions']
    else:
        raise DomainError('UNAPPROVED_CORRECTION', '不允许该修改类型')
    return result

class ReviewAnswer(Contract):
    task_id: Identifier
    review_id: Identifier
    review_revision: int = Field(ge=1)
    basis_hash: str = Field(pattern='^[0-9a-f]{64}$')
    client_request_id: Identifier
    action: Literal['confirm', 'correct', 'not_supported', 'unable']
    selected_interpretation_id: str | None = None
    correction: Correction | None = None
    reason: str = Field(default='', max_length=16000)
    simulation: bool = False
    correction_measurement_id: Identifier | None = None
    comparison_outcome: Literal['different_conditions', 'unresolved'] | None = None

    @model_validator(mode='after')
    def explanation_for_decision(self):
        if self.action != 'unable' and not self.reason.strip():
            raise ValueError('作出事实判断或修正时请说明原文依据；无法判断可不填。')
        if self.comparison_outcome == 'different_conditions' and self.action != 'confirm':
            raise ValueError('不同测量条件只适用于明确保留的判断。')
        if self.comparison_outcome == 'unresolved' and self.action != 'unable':
            raise ValueError('未决结论只适用于暂不判断。')
        return self

def withdraw_paused_checks(repository, conn, task_id):
    """Withdraw unanswered engineering questions: undispatched checks or exact null-default schema migration.

    A past pause-control bug caught DISPATCH_FORBIDDEN as scientific ambiguity.
    No actual judgment/answer is overturned. M06 must independently recheck the
    saved candidate, via ordinary source reconciliation and its existing budget.
    """
    task = repository.task(conn, task_id)
    if task['science_state'] != 'open' or not task['query_ref']:
        return
    rows = conn.execute("SELECT * FROM reviews WHERE task_id=? AND status='pending' AND answer IS NULL AND application IS NULL", (task_id,)).fetchall()
    if not rows:
        return
    query_ref = loads(task['query_ref'])
    spec = repository.object(conn, task_id, 'confirmed_query', query_ref['id'], query_ref['version'])
    for row in rows:
        question = loads(row['payload'])
        ref = question.get('basis', {}).get('candidate_ref')
        if question.get('owner') != 'M06' or not ref or question['basis'].get('spec_hash') != spec['spec_hash']:
            continue
        candidate = repository.object(conn, task_id, 'candidate', ref['id'], ref['version'])
        if content_hash(candidate) != ref['content_sha256'] or candidate.get('current_measurement_ref'):
            continue
        assembly = candidate.get('assembly_context', {})
        check = assembly.get('paper_verification') or {}
        from astroquery_ai.science.measurements.admission_contracts import matches_proposal_hash
        schema_only = check.get('state') == 'passed' and check.get('proposal_hash') != digest(candidate['proposal']) and matches_proposal_hash(candidate['proposal'], check.get('proposal_hash'))
        origin_job = conn.execute('SELECT kind FROM jobs WHERE task_id=? AND job_id=?', (task_id, assembly.get('batch_id'))).fetchone()
        source_checked = any((outcome['item_ref'].get('id') == ref['id'] for report in repository.objects(conn, task_id, 'source_recheck') for outcome in report['outcomes']))
        still_reading = conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='paper_batch' AND json_extract(CAST(payload AS TEXT),'$.work_id')=? AND status IN ('ready','running','waiting_dependency') LIMIT 1", (task_id, assembly.get('source', {}).get('source_id'))).fetchone()
        premature = bool(origin_job and origin_job['kind'] == 'paper_batch' and (not source_checked) and (not still_reading))
        rebound = False
        assessment = check.get('check') or {}
        if check.get('state') == 'unresolved' and assessment.get('subject') == 'target' and (assessment.get('quantity_match') == 'exact') and (assessment.get('result_role') in {'reported_result', 'adopted_measurement'}) and check.get('attempt_id'):
            from astroquery_ai.science.measurements.admission_contracts import AdmissionCheck, normalized
            from astroquery_ai.science.paper_admission import check_local_evidence, page_blocks
            try:
                index = repository.object(conn, task_id, 'document_index', assembly['source']['source_id'])
                pages = {p['page']: p['text'] for p in index['pages']}
                anchors = [a for k in ('subject_evidence', 'role_evidence', 'quantity_evidence') for a in assessment.get(k, [])]
                supplied = [b for b in page_blocks(pages) if any((a.get('quote') and a['page'] == b['page'] and (b['block_id'] in a.get('block_ids', [])) and (normalized(b['text']) in normalized(a['quote'])) for a in anchors))]
                receipt = next((s['receipt'] for s in repository.objects(conn, task_id, 'job_step') if s.get('receipt', {}).get('attempt_id') == check['attempt_id']))
                result = check_local_evidence(MeasurementProposal.model_validate(candidate['proposal']), AdmissionCheck.model_validate(assessment), spec['target'], pages, receipt, visible_blocks=supplied, image_pages=set(), require_quantity=True)
                rebound = result['state'] == 'passed'
            except (DomainError, ValueError, KeyError, StopIteration):
                pass
        paused_before_dispatch = not (assembly.get('owner') != 'M06' or check.get('check') is not None or check.get('attempt_id') is not None or (check.get('failure') not in {'DISPATCH_FORBIDDEN', 'HTTP_DISPATCH_FORBIDDEN'}))
        if candidate.get('reason') != 'local_subject_or_result_evidence_unresolved' or not (schema_only or rebound or paused_before_dispatch or premature):
            continue
        body = {'schema_version': 'PausedVerifierQuestionWithdrawal/1', 'review_id': row['review_id'], 'candidate_ref': ref, 'source_id': assembly['source']['source_id'], 'reason': 'source_anchor_rebinding_requires_owner_recheck' if rebound else 'default_scope_schema_migration_requires_owner_recheck' if schema_only else 'whole_source_owner_check_not_yet_performed' if premature else 'verification_not_dispatched_due_to_pause', 'original_failure': 'source_anchor_binding' if rebound else 'default_scope_schema_hash_mismatch' if schema_only else 'premature_human_escalation' if premature else check['failure'], 'original_question_hash': digest(question), 'original_question_and_evidence_retained': True, 'actual_user_answer': False, 'scientific_decision_made': False}
        body['withdrawal_id'] = 'review-withdrawal-' + digest(body)
        receipt = repository.put_object(conn, task_id, 'review_withdrawal', body['withdrawal_id'], 1, body)
        conn.execute("UPDATE reviews SET status='closed_unanswered',application=? WHERE review_id=?", (canonical({'status': 'owner_recheck_required', 'withdrawal_ref': receipt, 'actor': 'system_lifecycle_recovery', 'human_answer_applied': False}), row['review_id']))
        repository.event(conn, task_id, 'review_withdrawn', {'review_id': row['review_id'], 'reason': body['reason'], 'withdrawal_ref': receipt, 'owner': 'M06'})
        repository.enqueue(conn, task_id, 'M06', 'source_reconcile', {'work_id': body['source_id'], 'items': [{'kind': 'candidate', **ref}], 'recovery_from_withdrawal_ref': receipt})

def action_choices(actions, issue_kind=None, interaction_version=1):
    """Button meanings belong to the answer protocol, not model-authored prose."""
    labels = {
        'confirm': ('确认当前解释', '保留当前解释，并由原责任模块复检；不授予新的科学权限。'),
        'correct': ('依据原件修正解释', '仅修改本题开放字段，提交现有原件依据后复检。'),
        'not_supported': ('原件不支持当前解释', '不准入本候选解释；原件和原报保留。'),
        'unable': ('无法判断，保留未决', '不猜测缺失事实，保留原件和未决状态后继续可执行工作。'),
    }
    if issue_kind == 'comparison_contradiction':
        labels['confirm'] = ('已核对，保留两项及分歧说明', '保留两项结果，不据此证明两项一致或选择最佳值。')
        labels['not_supported'] = ('原件不支持矛盾判断', '保留原测量，不根据本题排除某一项测量。')
        if interaction_version >= 2:
            labels['confirm'] = ('按不同测量条件保留', '记录本次判断为测量条件不同，保留两项；不证明两项一致，不选最佳值。')
    if interaction_version >= 2:
        labels['unable'] = ('证据不足，暂不判断', '保留未决标记和原件，继续其他可执行工作；无需填写理由。')
    return [{'action': a, 'label': labels[a][0], 'impact': labels[a][1],
        **({'comparison_outcome': 'different_conditions' if a == 'confirm' else 'unresolved'}
           if interaction_version >= 2 and issue_kind == 'comparison_contradiction' and a in {'confirm', 'unable'} else {})}
        for a in actions]


def presented_review(item):
    """Also adapt old pending questions without modifying their saved history."""
    result = dict(item)
    if item.get('choices'):
        result.setdefault('proposed_choices', item['choices'])
    result['choices'] = action_choices(item['allowed_actions'], item.get('issue_kind'), item.get('interaction_version', 1))
    return result


class ReviewService:

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _open(task):
        if task['kind'] != 'live' or task['science_state'] != 'open' or task['lifecycle'] in TERMINAL | {'cancelling', 'pausing', 'paused', 'interrupted'}:
            raise DomainError('REVIEW_CLOSED', '当前任务不能再应用审核答案')

    def register(self, conn, task_id: str, candidate: dict) -> dict:
        self._open(self.repository.task(conn, task_id))
        if candidate.get('origin') not in {'M03', 'M06', 'M08', 'M09'} or candidate.get('owner') not in {'M03', 'M06'}:
            raise DomainError('INVALID_REVIEW_OWNER', '只能审核质检中的来源语义问题', 422)
        if candidate.get('issue_kind') not in {'object_semantics', 'quantity_semantics', 'value_transcription', 'uncertainty_semantics', 'condition_semantics', 'unit_semantics', 'comparison_contradiction'}:
            raise DomainError('NOT_A_REVIEW_QUESTION', '该情况不是可供人判断的质检语义问题', 422)
        if candidate.get('issue_kind')=='comparison_contradiction':
            task=self.repository.task(conn,task_id)
            spec=self.repository.object(conn,task_id,'confirmed_query',loads(task['query_ref'])['id'])
            from .run_policy import consolidated
            if not consolidated(spec) or candidate.get('origin')!='M09':
                raise DomainError('NOT_A_REVIEW_QUESTION','对照问题必须来自本轮已冻结策略')
        if not candidate.get('evidence_refs') or not candidate.get('question') or (not candidate.get('impact')) or (not candidate.get('basis')):
            raise DomainError('INSUFFICIENT_REVIEW_EVIDENCE', '审核缺少具体命题、现成证据或影响', 422)
        if not candidate.get('scope', {}).get('candidate_ids') and (not candidate.get('scope', {}).get('measurement_ids')):
            raise DomainError('REVIEW_SCOPE_EMPTY', '审核必须指向具体候选或测量', 422)
        for ref in candidate['evidence_refs']:
            evidence = self.repository.object(conn, task_id, 'evidence', ref['id'], ref['version'])
            if digest({k: v for k, v in evidence.items() if k != 'content_sha256'}) != ref['content_sha256']:
                raise DomainError('STALE_REVIEW_EVIDENCE', '审核证据版本不一致')
        basis_hash = digest(candidate['basis'])
        key = digest({'group': candidate['group_key'], 'spec': candidate['basis']['spec_hash']}) if candidate.get('group_key') else digest({'basis': basis_hash, 'question': candidate['issue_key'], 'scope': candidate['scope']})
        old = conn.execute('SELECT * FROM reviews WHERE task_id=? AND logical_key=?', (task_id, key)).fetchone()
        if old:
            item = loads(old['payload'])
            if not candidate.get('group_key'):
                return item
            if old['status'] == 'pending' and old['answer'] is None:
                changed = False
                for scope_key, refs_key in (('candidate_ids', 'candidate_refs'), ('measurement_ids', 'measurement_refs')):
                    for cid in candidate['scope'].get(scope_key, []):
                        if cid not in item['scope'].setdefault(scope_key, []):
                            item['scope'][scope_key].append(cid)
                            item['basis'].setdefault(refs_key, {})[cid] = candidate['basis'][refs_key][cid]
                            if scope_key == 'candidate_ids':
                                item['basis'].setdefault('current_measurement_refs', {})[cid] = candidate['basis']['current_measurement_refs'][cid]
                            changed = True
                if not changed:
                    return item
                for ref in candidate['evidence_refs']:
                    if ref not in item['evidence_refs']:
                        item['evidence_refs'].append(ref)
                item['revision'] += 1
                item['basis_hash'] = digest(item['basis'])
                conn.execute('UPDATE reviews SET revision=?,basis_hash=?,payload=? WHERE review_id=?',
                             (item['revision'], item['basis_hash'], canonical(item), old['review_id']))
                return item
            # Never silently attach new candidates to an already answered basis.
            key = digest({'group': key, 'basis': basis_hash})
            prior = conn.execute('SELECT payload FROM reviews WHERE task_id=? AND logical_key=?', (task_id, key)).fetchone()
            if prior:
                return loads(prior['payload'])
        review_id = new_id()
        item = {'schema_version': 'ReviewItem/1', 'review_id': review_id, 'revision': 1, 'task_id': task_id, 'basis_hash': basis_hash, 'owner': candidate['owner'], 'question': candidate['question'], 'scope': candidate['scope'], 'basis': candidate['basis'], 'evidence_refs': candidate['evidence_refs'], 'allowed_actions': candidate.get('allowed_actions', ['confirm', 'not_supported', 'unable']), 'impact': candidate['impact'], 'status': 'pending', 'created_at': utcnow()}
        item['correction_types'] = candidate.get('correction_types', [])
        item['current_interpretation'] = candidate.get('current_interpretation')
        item['approved_conditions'] = candidate.get('approved_conditions')
        item['issue_kind'] = candidate['issue_kind']
        item['interaction_version'] = 2
        for field in ('scientific_issue', 'choices', 'group_key','record_interpretations'):
            if field in candidate:
                item[field] = candidate[field]
        if set(item['allowed_actions']) - {'confirm', 'correct', 'not_supported', 'unable'}:
            raise DomainError('INVALID_REVIEW_ACTIONS', '审核动作不允许扩充操作权限', 422)
        # Keep the original model alternatives for audit, but never display an
        # affirmative model label on a rejecting protocol action (or vice versa).
        item = presented_review(item)
        conn.execute("INSERT INTO reviews(review_id,task_id,revision,basis_hash,logical_key,status,payload) VALUES(?,?,1,?,?,'pending',?)", (review_id, task_id, basis_hash, key, canonical(item)))
        self.repository.event(conn, task_id, 'review_ready', {'review_id': review_id, 'revision': 1})
        return item

    def answer(self, answer: ReviewAnswer, *, simulation=False) -> dict:
        document = answer.model_dump(mode='json')
        if answer.correction_measurement_id is None:document.pop('correction_measurement_id')
        if answer.comparison_outcome is None:document.pop('comparison_outcome')
        simulation = simulation or answer.simulation
        if not answer.simulation:
            document.pop('simulation')
        with self.repository.transaction() as conn:
            old = self.repository.replay_operation(conn, answer.task_id, answer.client_request_id, document)
            if old is not None:
                return old
            task = self.repository.task(conn, answer.task_id)
            self._open(task)
            if simulation:
                scopes = self.repository.objects(conn, answer.task_id, 'validation_scope')
                runs = self.repository.objects(conn, answer.task_id, 'query_acceptance_run')
                fixed = any((s.get('schema_version') == 'ReviewedBaselineVerification/1' and s.get('fixed_input_only') is True for s in scopes))
                normal = any((s.get('schema_version') == 'NormalQueryAcceptance/1' and s.get('task_id') == answer.task_id and (s.get('simulation_authorized') is True) for s in runs))
                if not (fixed or normal):
                    raise DomainError('REVIEW_SIMULATION_SCOPE', '模拟审核必须绑定明确授权的验收任务')
            row = conn.execute('SELECT * FROM reviews WHERE review_id=? AND task_id=?', (answer.review_id, answer.task_id)).fetchone()
            if row is None:
                raise DomainError('REVIEW_NOT_FOUND', '审核问题不存在', 404)
            item = loads(row['payload'])
            if row['status'] != 'pending' or row['revision'] != answer.review_revision or row['basis_hash'] != answer.basis_hash:
                raise DomainError('REVIEW_STALE', '审核问题已变化，请刷新')
            if answer.action not in item['allowed_actions']:
                raise DomainError('REVIEW_ACTION_NOT_ALLOWED', '此问题不允许该操作', 422)
            if answer.comparison_outcome is not None and item['issue_kind'] != 'comparison_contradiction':
                raise DomainError('REVIEW_OUTCOME_SCOPE', '此题不接收跨测量比较结论', 422)
            if answer.action == 'correct':
                if item['issue_kind']=='comparison_contradiction' and answer.correction_measurement_id not in item['scope']['measurement_ids']:
                    raise DomainError('REVIEW_CORRECTION_SCOPE','请指定本组中实际需要修正的一条记录',422)
                if item['issue_kind']=='comparison_contradiction' and answer.correction is not None:
                    own=item['record_interpretations'][answer.correction_measurement_id]['evidence_refs']
                    if answer.correction.evidence_ref.model_dump() not in own:
                        raise DomainError('REVIEW_CORRECTION_EVIDENCE','修正依据必须属于指定记录的原件',422)
                if answer.correction is None or answer.correction.evidence_ref.model_dump() not in item['evidence_refs']:
                    raise DomainError('REVIEW_CORRECTION_EVIDENCE', '纠正必须关联本问题现有证据', 422)
                if answer.correction.type not in item['correction_types']:
                    raise DomainError('REVIEW_CORRECTION_SCOPE', '修改超出本题开放字段', 422)
            elif answer.correction is not None:
                raise DomainError('UNEXPECTED_CORRECTION', '此动作不接收替值', 422)
            if answer.correction_measurement_id and (item['issue_kind']!='comparison_contradiction' or answer.action!='correct'):
                raise DomainError('REVIEW_CORRECTION_SCOPE','此问题不接收跨记录修正目标',422)
            answer_id = new_id()
            saved = {**document, 'answer_id': answer_id, 'actor': 'simulated_test_operator' if simulation else 'local_user', **({'simulation': True, 'actual_user_answer': False} if simulation else {}), 'received_at': utcnow()}
            answer_ref = self.repository.put_object(conn, answer.task_id, 'review_answer', answer_id, 1, saved)
            saved['answer_ref'] = answer_ref
            conn.execute("UPDATE reviews SET status='accepted',answer=? WHERE review_id=?", (canonical(saved), answer.review_id))
            job_id = self.repository.enqueue(conn, answer.task_id, 'review', 'apply_review', {'review_id': answer.review_id, 'answer_id': answer_id, 'owner': item['owner']})
            if task['lifecycle'] == 'waiting_review':
                self.repository.mutate_task(conn, answer.task_id, lifecycle='queued')
            response = {'status': 'accepted', 'answer_id': answer_id, 'review_id': answer.review_id, 'application_status': 'pending', 'job_id': job_id}
            self.repository.event(conn, answer.task_id, 'answer_received', response)
            self.repository.save_operation(conn, answer.task_id, answer.client_request_id, document, response)
            return response

    def list(self, conn, task_id):
        return [{**presented_review(loads(row['payload'])), 'status': row['status'], 'answer': loads(row['answer']) if row['answer'] else None, 'application': loads(row['application']) if row['application'] else None} for row in conn.execute('SELECT * FROM reviews WHERE task_id=? ORDER BY rowid', (task_id,))]
