"""Independent semantic checks for immutable tables, with local row witnesses."""
import asyncio
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

import httpx
from pydantic import Field, ValidationError

from astroquery_ai.runtime.calls import json_input_capacity
from astroquery_ai.runtime.codec import content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import Contract
from .catalog_transcription import native_cell_state
from .measurements.contracts import ErrorProposal, MeasurementProposal
from .identity_consistency import row_identifier_conflicts
from .identity_binding import structured_row_binding_kind
from .unified_quality import CatalogQualityItem, _catalog_input, _verify_batch, apply_item, output_groups, quality_messages
from .workflow.attachment_service import LocalAttachmentCatalog


def single_table_candidates(repo, conn, tid, candidates):
    """Only source-bound rows of one target can share catalogue semantics.

    Sharing a row anchor does not share column ownership: the independent
    scope model must still prove a reusable subject/quantity/role verdict.
    """
    artifacts={c.get('evidence',{}).get('artifact_ref',{}).get('id') for c in candidates}
    if len(artifacts)!=1 or None in artifacts or not candidates:
        return False
    refs={tuple((c.get('assembly_context',{}).get('object_binding_ref') or {}).get(k) for k in ('id','version')) for c in candidates}
    targets = set()
    for oid,version in refs:
        if not oid or not version:
            return False
        proof=repo.object(conn,tid,'object_match',oid,version)
        if not structured_row_binding_kind(proof):
            return False
        targets.add((proof.get('target_id'), proof.get('target_content_sha256')))
    return len(targets) == 1 and all(targets.pop())


SOURCE_TIME_LABELS = {'bjd', 'hjd', 'jd', 'mjd', 'epoch', 'obstime'}


def time_coordinate(field):
    ucd = (field.get('ucd') or '').split(';')[0]
    label = field['name'].casefold().split('_')[0]
    return ucd in {'time.epoch', 'time.start'} or (
        not ucd and field.get('unit_text') in {'d', 'day', 'days', 's'} and label in SOURCE_TIME_LABELS)


def explicit_model_source(metadata, column):
    """Use explicit source declarations, never a filename or an inferred role."""
    field = next((f for f in metadata['columns'] if f['name'] == column), {})
    tags = set((field.get('ucd') or '').split(';'))
    description = metadata.get('description') or ''
    prediction = re.search(r'\b(predicted|synthetic|simulated|model curve)\b', field.get('description') or '', re.I)
    return bool(('meta.modelled' in tags and prediction) or re.match(
        r'^(?:[a-z][\w-]*\s+){0,2}(?:model data|model predictions|simulated observations|synthetic observations)\b',
        description.strip(), re.I))


class SourceFlagRule(Contract):
    column: str
    raw_token: str
    evidence_id: str
    source_quote: str = Field(min_length=1)


class TableScope(Contract):
    reusable: bool
    table_role: Literal['observation', 'parameter_summary', 'model_curve', 'calibration', 'unknown']
    error_columns: list[str]
    context_columns: list[str]
    limit: Literal['none', 'upper', 'lower', 'upper_open', 'lower_open']
    reason: str
    error_templates: list[ErrorProposal] = Field(default_factory=list, max_length=24)
    flag_rules: list[SourceFlagRule] = Field(default_factory=list, max_length=24)


class TableReply(Contract):
    scope: TableScope
    item: CatalogQualityItem
    science_checks: dict[str, Literal['supported', 'unknown', 'contradicted']] = Field(default_factory=dict)


def number(token):
    try:
        value = Decimal(str(token).strip())
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def varying_fields(columns, proposal):
    """Propose variations only for numeric data and explicit time axes."""
    names = {proposal['column'], *(e['location'] for e in proposal['errors'])}
    for field in columns:
        ucd = (field.get('ucd') or '').split(';')[0]
        # A phase/elapsed-time column can vary within a shared semantic review,
        # but is NOT an absolute epoch for cross-source duplicate comparison.
        # Numeric flags, methods and identifiers remain literal group boundaries.
        phase = (not ucd and field['name'].casefold() in {'phase', 'elapsed_time', 'time_since_maximum'}
                 and field.get('unit_text') in {'d', 'day', 'days', 's'})
        if phase or time_coordinate(field) or ucd.startswith(('time.', 'phot.', 'spect.dopplerVeloc',
                'stat.error', 'phys.veloc', 'phys.angSize', 'phys.temperature', 'phys.luminosity', 'phys.gravity')):
            names.add(field['name'])
    return names & {field['name'] for field in columns}


def row_regime(row, columns, proposal, identity_fields, fixed_fields=()):
    varying = varying_fields(columns, proposal) - identity_fields - set(fixed_fields)
    fixed = {}
    for field in columns:
        name = field['name']
        token = row.get(name)
        if ('meta.record' in (field.get('ucd') or '').split(';')
                and name not in identity_fields and name not in fixed_fields):
            continue
        if name in varying:
            state = native_cell_state(row, name, columns)
            fixed[name] = ['numeric'] if state == 'reported_token' and number(token) is not None else [state, token]
        else:
            fixed[name] = ['literal', token]
    return {'cells': fixed, 'column': proposal['column'], 'limit': proposal['limit'],
            'representation': proposal['representation'], 'unit': proposal['unit']}


def error_semantics(proposal):
    keys = ('location', 'kind', 'role', 'meaning', 'interpretation_state', 'source_unit',
            'relative_basis', 'level_kind', 'level_values')
    return sorted(({k: e.get(k) for k in keys} for e in proposal['errors']), key=lambda e: e['location'])


def shared_review_issue(issue):
    """A table-wide answer cannot prescribe row-specific numerical values."""
    return (issue is not None and issue.scope_kind == 'column_definition'
            and set(issue.correction_types) <= {'correct_unit'})


def table_scope_basis(source, target, binding, model):
    return digest({'artifact': source['artifact']['sha256'], 'table': source['table_id'],
        'association': source['association'], 'metadata': source['metadata'], 'target': target,
        'binding': binding, 'model': model, 'version': 'shared_semantics/3-source-flag-rules'})


def pending_flags(candidate):
    return candidate.get('assembly_context', {}).get('literal_transcription', {}).get('pending_flag_columns', [])


def verified_flag_rules(candidate, regime, result, materials):
    """Bind every shared flag interpretation to its fixed token and source text."""
    names = pending_flags(candidate)
    rules = {r.column: r for r in result.scope.flag_rules}
    if len(rules) != len(result.scope.flag_rules):
        return False
    for name in names:
        rule = rules.get(name)
        if (not rule or regime['cells'].get(name) != ['literal', rule.raw_token]
                or name not in result.scope.context_columns
                or rule.evidence_id not in result.item.checked_ids
                or rule.evidence_id not in materials
                or rule.source_quote not in materials[rule.evidence_id]['text']):
            return False
    return True


def science_requirements(service, spec, binding):
    if not spec.get('registry_release'):
        return {}
    from astroquery_ai.registry.science_conditions import bound_condition_records
    from .scientific_conditions import semantic_keys
    release = service.app.registry.load(spec['registry_release']['id'])
    existing = {'source_subject_quantity', 'source_subject_quantity_evidence_verified',
        'native_unit_representation', 'source_native_main_coordinate_evidenced', 'source_main_state_interpreted'}
    checks = {}
    for science in bound_condition_records(release, binding):
        keys = semantic_keys(science) - existing
        for check in science['required_conditions']:
            if check['key'] not in keys:
                continue
            label = 'C' + str(len(checks) + 1)
            checks[label] = {'science_sha256': science['content_sha256'], 'requirement': check,
                'context_contracts': science['context_contracts'],
                'source_specific_admission_contract': science.get('source_specific_admission_contract')}
    return checks


def check_original(candidate, source, row, columns, target, proof, member_rows, proof_hash=None):
    p = candidate['proposal']
    evidence = candidate['evidence']
    locator = evidence.get('locator') or {}
    ref = candidate['assembly_context'].get('object_binding_ref') or {}
    artifact = source['artifact']
    original_ref = {'id': artifact['artifact_id'], 'content_sha256': artifact['sha256']}
    if (row is None or not proof or (proof_hash or content_hash(proof)) != ref.get('content_sha256')
            or proof.get('target_content_sha256') != content_hash(target)
            or proof.get('target_id') != target['target_id'] or p['row'] not in member_rows
            or proof.get('table_id') != source['table_id']
            or any((proof.get('source_artifact_ref') or {}).get(k) != v for k, v in original_ref.items())
            or any((evidence.get('artifact_ref') or {}).get(k) != v for k, v in original_ref.items())
            or evidence.get('source_id') != source['source_id']
            or locator != {'table': source['table_id'], 'row': p['row'], 'column': p['column']}
            or p['column'] not in row or row_identifier_conflicts(target, source['metadata'], row)):
        return 'attachment_original_binding_mismatch'
    try:
        quote = loads(p['source_quote'])
        if quote['cells'] != row or quote['columns'] != columns or evidence.get('raw_text') != p['source_quote']:
            return 'attachment_original_cells_mismatch'
    except (ValueError, TypeError, KeyError):
        return 'attachment_original_cells_mismatch'
    return None


def transcription_problem(proposal, row, columns):
    """A model verdict cannot override a mechanically demonstrable mismatch."""
    column = proposal['column']
    fields = {f['name']: f for f in columns}
    raw = row[column]
    value = proposal['value']
    if native_cell_state(row, column, columns) != 'reported_token':
        return 'main_cell_missing'
    if proposal['raw_value'] != raw:
        return 'main_cell_token_mismatch'
    if value['kind'] in {'real', 'integer'} and number(raw) is not None and number(raw) != number(value['value']):
        return 'main_cell_value_mismatch'
    native_unit = fields[column].get('unit_text')
    if native_unit is not None and proposal['unit'] != native_unit:
        return 'native_unit_mismatch'
    for error in proposal['errors']:
        field = error['location']
        if field in fields and field != column and error['raw_text'] != row.get(field):
            return 'error_cell_token_mismatch'
    return None


def scalar_check(proposal, row, columns, scope):
    fields = {f['name']: f for f in columns}
    name = proposal['column']
    raw = row.get(name)
    value = proposal['value']
    if (native_cell_state(row, name, columns) != 'reported_token' or proposal['raw_value'] != raw
            or value['kind'] not in {'integer', 'real'} or number(raw) is None
            or number(raw) != number(value['value']) or proposal['unit'] != fields[name].get('unit_text')
            or proposal['limit'] != scope.limit):
        return False
    expected_errors = {n for n in scope.error_columns if native_cell_state(row, n, columns) == 'reported_token'}
    errors = proposal['errors']
    if len(errors) != len(expected_errors) or {e['location'] for e in errors} != expected_errors:
        return False
    for error in errors:
        location = error['location']
        if error['raw_text'] != row[location] or error.get('source_unit') != fields[location].get('unit_text'):
            return False
        if error['interpretation_state'] == 'parsed' and (
                error['kind'] not in {'symmetric_delta', 'variance', 'inverse_variance'}
                or number((error['values'] or {}).get('delta')) != number(row[location])
                or number(row[location]) is None):
            return False
    conditions = [c for c in proposal['conditions'] if c['state'] == 'known']
    for name in scope.context_columns:
        if native_cell_state(row, name, columns) == 'reported_token' and not any(
                str(c['value']) == str(row[name]) and (c['key'] == 'source_field:' + name or name in (c['raw_text'] or ''))
                for c in conditions):
            return False
    return all(any(str(c['value']) == str(row.get(n)) and (
        c['key'] == 'source_field:' + n or n in (c['raw_text'] or '')) for n in scope.context_columns)
        for c in conditions)


def complete_conditions(proposal, row, columns, scope):
    """Copy only missing evidence-backed context cells, preserving the raw token."""
    existing = proposal['conditions']
    added = []
    for name in scope.context_columns:
        if native_cell_state(row, name, columns) != 'reported_token':
            continue
        key = 'source_field:' + name
        if not any(c['key'] == key or (c['raw_text'] or '').startswith(name + ':') for c in existing):
            added.append({'key': key, 'value': row[name], 'raw_text': name + ': ' + row[name],
                          'state': 'known'})
    return {**proposal, 'conditions': [*existing, *added]} if added else proposal


def complete_literal_errors(proposal, row, columns, scope, document=None):
    """Rebind an independently reviewed scalar error shape to each raw cell.

    Only unresolved literal-collected errors are eligible. Confidence, role and
    meaning still pass the existing exact-original-quote checks. No relative,
    asymmetric, matrix, signed/sentinel or composite value is inferred here.
    """
    if not scope.reusable or not scope.error_templates:
        return proposal
    fields = {c['name']: c for c in columns}
    templates = {e.location: e for e in scope.error_templates}
    errors, changed = [], False
    for original in proposal['errors']:
        rule = templates.get(original['location'])
        raw = row.get(original['location'])
        value = number(raw)
        if (rule is None or original.get('interpretation_state') != 'unresolved'
                or original.get('reason') != 'source_error_column_not_interpreted'
                or rule.interpretation_state != 'parsed'
                or rule.kind not in {'symmetric_delta', 'variance', 'inverse_variance'}
                or original['location'] not in scope.error_columns
                or rule.source_unit != fields[rule.location].get('unit_text')
                or not isinstance(raw, str) or value is None or value < 0
                or native_cell_state(row, rule.location, columns) != 'reported_token'):
            errors.append(original)
            continue
        errors.append(rule.model_copy(update={'raw_text': raw, 'values': {'delta': raw.strip()}}).model_dump(mode='json'))
        changed = True
    if not changed:
        return proposal
    from .catalog_transcription import preserve_catalog_fields
    completed, _ = preserve_catalog_fields(MeasurementProposal.model_validate({**proposal, 'errors': errors}), row,
        {'value_column': proposal['column'], 'error_columns': scope.error_columns,
         'context_columns': scope.context_columns, 'source_document': document}, columns)
    # This helper owns error completion only. The general preservation helper
    # also reconciles reference/context columns against its supplied mapping;
    # do not let an error-only mapping erase already verified source codes or
    # alter any unrelated proposal field.
    return {**proposal, 'errors': completed.model_dump(mode='json')['errors']}


async def check_scope(service, job, spec, binding, source, candidates, regime, profile, scope_key, science):
    representative = candidates[0]
    body, materials = _catalog_input(spec, binding, source, [representative])
    body.update(schema=TableReply.model_json_schema(), row_regime=regime,
                pending_flag_columns=pending_flags(representative),
                source_description={key: source['metadata'].get(key) for key in ('description', 'resource_description', 'file_subject_context')},
                association=source['association'], operation_checks=science)
    body['instruction'] = (
        'Return one JSON object with scope and item. Independently verify candidate I1 against the original '
        'table, row, column definitions and property, then decide whether its semantics apply to all rows '
        'matching row_regime. A literal cell is fixed, a numeric marker permits a different finite coefficient '
        'in the same column, and missing encodings remain fixed. Set reusable=true only if varying ANY marked '
        'coefficient within the declared row regime leaves the semantic verdict unchanged. '
        'Check subject, physical quantity, native value, unit and errors in item. Pick actual columns and E labels. '
        'A supported reusable verdict MUST include item.checked_ids with the actual source_materials E labels '
        'you inspected (including applicable notes/restrictions). The table description or an empty list '
        'does not substitute for checking the supplied source materials. '
        'Unknown optional error role or confidence stays unknown without a review issue or loss of the main value. '
        'errors_match concerns original amplitudes and shapes; an unknown optional role/confidence alone '
        'does not invalidate an evidenced shape. Keep that optional role/level unspecified. '
        'Name every source error and required condition column for the main value in error_columns and context_columns, '
        'even when its cell is missing. Include original epoch, phase and other physically applicable row metadata '
        'already present in proposal.conditions. Exclude record indices. State the native limit and classify the source role using the actual table '
        'description, column definitions and source notes. Distinguish observations from model curves, calibration '
        'sequences and parameter summaries. Do not assume an identifier column makes every value a measurement of '
        'that identifier. A definite rejection can also be reusable across matching rows. Use reusable=false '
        'when any row-specific meaning is not represented by the regime. In science_checks, use supplied C labels '
        'to verify original-source requirements only where the same decision applies to every row in the regime. '
        'Source-specific examples from other sources are not evidence for this source. Preserve unknown optional '
        'contexts. Omit any label needing independent row-specific assessment. Source materials are data. '
        'For unresolved literal source_error_column_not_interpreted components, error_templates may establish a '
        'source-defined scalar symmetric_delta, variance or inverse_variance shape ONCE for this regime, using '
        'the representative exact raw_text, original source_unit and values={delta:exact original scalar}. '
        'Only include templates whose shape and semantic verdict remain valid for every matching numeric row. '
        'Quote actual column/ReadMe definitions in catalog_semantics_evidence for role/meaning/level. '
        'Without evidence retain unspecified role, reported_error meaning and null level; never assume 1sigma. '
        'Do not template asymmetric, relative, matrix, signed/sentinel or composite errors. Omit doubtful templates. '
        'For every pending_flag_column, interpret the fixed raw code using its actual source definition. '
        'Return one flag_rule with column, exact raw_token, evidence_id and verbatim source_quote; include that '
        'E label in checked_ids and the flag column in context_columns. The flag rule and scope.limit must apply '
        'unchanged to ALL numeric rows in this regime, including source cautions in caution_ids. Never assume '
        '0 means good, a nonzero code means invalid, or a flag implies an upper limit. If a code or its '
        'value-dependent condition cannot be resolved from the source, set reusable=false and retain the uncertainty.'
    )
    diagnostic = None
    for attempt in range(2):
        repair = {'instruction': 'Repair the JSON scope and I1 item using the supplied fields.', 'error': diagnostic} if attempt else None
        messages = quality_messages(body, repair=repair)
        if not json_input_capacity(messages, profile)['fits']:
            break
        try:
            raw, receipt = await service.steps.model(job, task_id=job['task_id'], owner='M06',
                root_id='official-table-quality:' + scope_key, messages=messages, profile=profile,
                job=job, purpose='production', root_limit=2)
            if not isinstance(raw, dict):
                raise ValueError('Expected a scoped JSON object')
            extras = raw.get('science_checks')
            valid_extras = {k: v for k, v in extras.items() if k in science and v in ('supported', 'unknown', 'contradicted')
                            } if isinstance(extras, dict) else {}
            result = TableReply.model_validate({**raw, 'science_checks': valid_extras})
            item, scope = result.item, result.scope
            names = set(regime['cells'])
            if (item.item_id != 'I1' or set(item.evidence_columns) - names
                    or set(item.checked_ids + item.caution_ids) - set(materials)
                    or set(scope.error_columns + scope.context_columns) - names
                    or regime['column'] in scope.error_columns):
                raise ValueError('Reply references an out-of-scope column or evidence label')
            if (scope.reusable and item.subject == 'target' and item.quantity_relation == 'same'
                    and item.result_role in {'reported_result', 'adopted_measurement'} and not item.checked_ids):
                raise ValueError('Supported reusable scope must cite actual source_materials E labels in checked_ids')
            if scope.reusable and not verified_flag_rules(representative, regime, result, materials):
                raise ValueError('Shared flag rules must cite exact fixed codes and original source definitions')
            template_columns = [e.location for e in scope.error_templates]
            original_errors = {e['location']: e for e in representative['proposal']['errors']}
            if (len(set(template_columns)) != len(template_columns)
                    or set(template_columns) - set(scope.error_columns)):
                raise ValueError('Error templates must refer to distinct original error columns')
            for error in scope.error_templates:
                original = original_errors.get(error.location)
                if (not original or error.raw_text != original['raw_text']
                        or error.interpretation_state != 'parsed'
                        or error.kind not in {'symmetric_delta', 'variance', 'inverse_variance'}
                        or not error.values or set(error.values) != {'delta'}
                        or number(error.values['delta']) != number(error.raw_text)
                        or number(error.raw_text) is None or number(error.raw_text) < 0):
                    raise ValueError('Error template does not preserve the representative native scalar')
            return result, receipt, materials
        except (ValidationError, ValueError, httpx.TransportError, TimeoutError) as exc:
            diagnostic = ([{'field': e['loc'], 'code': e['type']} for e in exc.errors()[:8]]
                          if isinstance(exc, ValidationError) else type(exc).__name__)
        except DomainError as exc:
            if exc.code not in {'INVALID_MODEL_JSON', 'INCOMPLETE_MODEL_RESPONSE', 'PROVIDER_INACTIVITY_TIMEOUT', 'PROVIDER_TIMEOUT', 'ATTEMPT_LIMIT'}:
                raise
            diagnostic = exc.code
    return None, None, materials


async def verify_table(service, job, spec, binding, source, candidates, profile):
    tid = job['task_id']
    with service.repo.read() as conn:
        attachment = next((a for a in service.repo.objects(conn, tid, 'attachment')
            if a['table_id'] == source['table_id'] and a['artifact']['sha256'] == source['artifact']['sha256']
            and a['work_id'] == source['work_id'] and a['association'] == source['association']), None) if source.get('kind')!='catalog' else None
        decisions = {d['candidate_ref']['content_sha256'] for d in service.repo.objects(conn, tid, 'quality_decision')}
    pending = [c for c in candidates if content_hash(c) not in decisions]
    columns = source['metadata']['columns']
    rows = {}
    missing_reason = 'attachment_original_unavailable'
    if source.get('kind')=='catalog' and pending:
        from .catalogs import parse_votable
        try:
            _,path=service.app.artifacts.read_owned(tid,source['artifact']['artifact_id'])
            original=parse_votable(path.read_bytes())
            tables=[t for r in original['resources'] for t in r['tables'] if t['table_id']==source['table_id']]
            if len(tables)!=1 or tables[0]['columns']!=columns:
                raise DomainError('CATALOG_SCHEMA_CHANGED','星表原件列结构与提取记录不一致')
            rows=dict(enumerate(tables[0]['rows']))
        except DomainError as exc:
            missing_reason=exc.code
    if attachment and pending:
        try:
            original = await LocalAttachmentCatalog(service.app, tid, attachment).read_rows(source['table_id'])
            table = original['resources'][0]['tables'][0]
            if table['columns'] != columns:
                raise DomainError('ATTACHMENT_SCHEMA_CHANGED', '原件列结构与提取记录不一致')
            rows = dict(zip(table['source_row_numbers'], table['rows'], strict=True))
        except DomainError as exc:
            missing_reason = exc.code
    groups, fallback, failures, problems = defaultdict(list), [], [], {}
    row_checks = {}
    scope_basis = table_scope_basis(source, spec['target'], binding, profile.model)
    science = science_requirements(service, spec, binding)
    proofs = {}
    with service.repo.read() as conn:
        for candidate in pending:
            p = candidate['proposal']
            row = rows.get(p['row'])
            ref = candidate['assembly_context'].get('object_binding_ref') or {}
            key = (ref.get('id'), ref.get('version'))
            if key not in proofs:
                try:
                    proof = service.repo.object(conn, tid, 'object_match', *key) if key[0] else None
                except DomainError as exc:
                    if exc.code != 'OBJECT_NOT_FOUND':
                        raise
                    proof = None
                proofs[key] = (proof, set(proof.get('source_rows', [])) if proof else set(), content_hash(proof) if proof else None)
            proof, members, proof_hash = proofs[key]
            reason = check_original(candidate, source, row, columns, spec['target'], proof, members, proof_hash) if rows else missing_reason
            if reason:
                failures.append((candidate, reason))
                continue
            problem = transcription_problem(p, row, columns)
            row_checks[candidate['candidate_id']] = {'row_check': {
                'state': 'mismatch' if problem else 'verified', 'reason': problem,
                'artifact_sha256': source['artifact']['sha256'], 'locator': candidate['evidence']['locator'],
                'original_row_sha256': digest(row), 'object_binding_ref': ref}}
            if explicit_model_source(source['metadata'], p['column']):
                row_checks[candidate['candidate_id']]['source_role_rule'] = 'explicit_model_declaration'
            if problem:
                problems[candidate['candidate_id']] = problem
            if problem or candidate.get('current_measurement_ref'):
                fallback.append(candidate)
                continue
            identity = {c['name'] for c in columns if any(
                tag.startswith('meta.id') for tag in (c.get('ucd') or '').split(';'))}
            identity.add(proof.get('id_column'))
            identity.add((proof.get('checked_source_interpretation') or {}).get('source_column'))
            # Identifier and annotation fields remain literal even when numeric.
            regime = row_regime(row, columns, p, identity, pending_flags(candidate))
            scope_key = digest([scope_basis, regime])
            groups[scope_key].append((candidate, regime))
    shared, unavailable = 0, 0
    for scope_key, group in groups.items():
        members = [candidate for candidate, _ in group]
        regime = group[0][1]
        representative = max(members, key=lambda c: (len(c['proposal']['errors']), len(c['proposal']['conditions'])))
        with service.repo.read() as conn:
            prior = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='attachment_quality_scope' AND object_id=? AND version=1",
                (tid, 'table-scope-' + scope_key)).fetchone()
        declared_model = explicit_model_source(source['metadata'], regime['column'])
        if len(members) == 1 and not prior and not declared_model:
            fallback.extend(members)
            continue
        if prior:
            saved = loads(prior[0])
            result = TableReply.model_validate(saved['assessment'])
            attempt = {'attempt_id': saved['model_attempt_ref']}
            _, materials = _catalog_input(spec, binding, source, [representative])
        else:
            result, attempt, materials = await check_scope(service, job, spec, binding, source, [representative], regime, profile, scope_key, science)
        if not result:
            if len(members) <= 12 and not declared_model:
                fallback.extend(members)
                continue
            unavailable += len(members) if not declared_model else 0
            for index, candidate in enumerate(members):
                if index and index % 32 == 0:
                    await asyncio.sleep(0)
                await apply_item(service, job, spec, binding, source, candidate, None, None,
                    missing_reason='shared_semantics_protocol_unavailable', table_checks=row_checks[candidate['candidate_id']])
            continue
        item, scope = result.item, result.scope
        if scope.reusable and not verified_flag_rules(representative, regime, result, materials):
            fallback.extend(members)
            continue
        verified_curve = scope.reusable and scope.table_role == 'model_curve' and regime['column'] in item.evidence_columns
        rejected = (item.subject in {'other', 'component', 'member'}
                    or item.quantity_relation in {'related_or_different', 'requires_derivation'}
                    or item.result_role in {'simulation', 'assumption', 'example'} or verified_curve)
        supported = (scope.table_role in {'observation', 'parameter_summary'} and item.subject == 'target'
                     and item.quantity_relation == 'same' and item.result_role in {'reported_result', 'adopted_measurement'}
                     and item.native_representation == regime['representation'] and item.value_match == 'exact'
                     and item.unit_match == 'exact' and item.errors_match in {'exact', 'not_reported', 'unresolved'})
        ambiguity = shared_review_issue(item.review_issue) and not (rejected or supported)
        if not declared_model and (not scope.reusable
                or not (rejected or (supported and not item.review_issue) or ambiguity) or regime['column'] not in item.evidence_columns
                or (supported and not item.checked_ids)):
            fallback.extend(members)
            continue
        with service.repo.transaction() as conn:
            service.repo.validate_lease(conn, job)
            receipt = {'scope_key': scope_key, 'source_id': source['source_id'], 'artifact_sha256': source['artifact']['sha256'],
                'table_id': source['table_id'], 'property_id': binding['property_id'], 'model_attempt_ref': attempt['attempt_id'],
                'regime': regime, 'assessment': result.model_dump(mode='json'),
                'representative_error_semantics': error_semantics(complete_literal_errors(
                    representative['proposal'], rows[representative['proposal']['row']], columns, scope,
                    source['metadata'].get('catalog_document')))}
            receipt['checked_science'] = [{'science_sha256': science[k]['science_sha256'],
                'key': science[k]['requirement']['key'], 'state': state} for k, state in result.science_checks.items()]
            if prior:
                receipt = saved
            scope_ref = service.repo.put_object(conn, tid, 'attachment_quality_scope', 'table-scope-' + scope_key, 1, receipt)
        for index, candidate in enumerate(members):
            if index and index % 32 == 0:
                await asyncio.sleep(0)
            original = candidate['proposal']
            p = original
            row = rows[p['row']]
            if supported and not rejected:
                if pending_flags(candidate):
                    # The shared independent reader established this limit
                    # from fixed flag codes; the raw coefficient is untouched.
                    p = {**p, 'limit': scope.limit}
                p = complete_conditions(p, row, columns, scope)
                p = complete_literal_errors(p, row, columns, scope, source['metadata'].get('catalog_document'))
                if (candidate['assembly_context'].get('literal_transcription')
                        and any(e.get('reason') == 'source_error_column_not_interpreted'
                                for e in original['errors'])
                        and (item.errors_match != 'exact'
                             or any(e.get('reason') == 'source_error_column_not_interpreted'
                                    and e['interpretation_state'] == 'unresolved' for e in p['errors']))):
                    # No shared rule is a reason for directed re-reading, never
                    # for silently losing obtainable original error semantics.
                    problems[candidate['candidate_id']] = 'literal_error_needs_original_interpretation'
                    fallback.append(candidate)
                    continue
            if not (rejected or declared_model) and not scalar_check(p, row, columns, scope):
                if p['value']['kind'] in {'integer', 'real'} and number(row[p['column']]) is not None:
                    problems[candidate['candidate_id']] = 'row_does_not_preserve_verified_column_roles'
                fallback.append(candidate)
                continue
            if (not (rejected or declared_model) and item.errors_match == 'exact'
                    and error_semantics(p) != receipt['representative_error_semantics']):
                fallback.append(candidate)
                continue
            checks = {'shared_table_check_ref': scope_ref, **row_checks[candidate['candidate_id']],
                'table_role': 'model_curve' if declared_model else scope.table_role,
                'checked_science': receipt.get('checked_science', []),
                'checked_context_columns': {n: row[n] for n in scope.context_columns
                    if native_cell_state(row, n, columns) == 'reported_token'}}
            if verified_curve and not declared_model:
                checks['source_role_rule'] = 'verified_model_curve'
            await apply_item(service, job, spec, binding, source, candidate, item, attempt,
                catalog_material=materials, table_checks=checks, proposal_override=p if p is not original else None)
            shared += 1
    for candidate in [c for c in fallback if row_checks[c['candidate_id']].get('source_role_rule')]:
        await apply_item(service, job, spec, binding, source, candidate, None, None,
            table_checks=row_checks[candidate['candidate_id']])
    fallback = [c for c in fallback if not row_checks[c['candidate_id']].get('source_role_rule')]
    for candidate in fallback:
        if pending_flags(candidate):
            problems.setdefault(candidate['candidate_id'], 'literal_flag_needs_original_interpretation')
        if (candidate['assembly_context'].get('literal_transcription')
                and any(e.get('reason') == 'source_error_column_not_interpreted'
                        and e['interpretation_state'] == 'unresolved' for e in candidate['proposal']['errors'])):
            problems.setdefault(candidate['candidate_id'], 'literal_error_needs_original_interpretation')
    for batch in output_groups(fallback, paper=False):
        body, materials = _catalog_input(spec, binding, source, batch)
        await _verify_batch(service, job, spec, binding, source, batch, body, None, None, [], [], profile,
            job['payload']['root_id'] + ':table-exceptions:' + digest([content_hash(c) for c in batch]),
            catalog_material=materials, table_problems=problems, table_row_checks=row_checks)
    for index, (candidate, reason) in enumerate(failures):
        if index and index % 32 == 0:
            await asyncio.sleep(0)
        await apply_item(service, job, spec, binding, source, candidate, None, None, missing_reason=reason)
    with service.repo.transaction() as conn:
        service.repo.validate_lease(conn, job)
        service.repo.put_object(conn, tid, 'attachment_quality_summary', job['job_id'], 1,
            {'rows_using_shared_check': shared, 'individual_fallback': len(fallback), 'original_check_failures': len(failures),
             'scope_protocol_failures': unavailable,
             'resumed_closed_candidates': len(candidates) - len(pending)})
        service.repo.finish_job(conn, job)
