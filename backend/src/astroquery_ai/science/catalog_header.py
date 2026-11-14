"""One production/calibration header interpreter with a shared two-call ceiling."""
import httpx
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from .catalog_context import MAX_HEADER_BYTES, required_fields, visible_columns, quarantine_unseen, retain_declared_errors

HEADER_VERSION = 'column-context-9'


async def interpret_header(table, spec, targets, *, prompt_factory, validate, ask):
    prompt = prompt_factory(table, spec, targets)
    followup_used = False
    try:
        raw, receipt = await ask(prompt)
    except (DomainError, httpx.TransportError, TimeoutError) as exc:
        if isinstance(exc, DomainError) and exc.code not in {
            'INCOMPLETE_MODEL_RESPONSE', 'MODEL_PROGRESS_TIMEOUT', 'PROVIDER_HTTP_ERROR',
            'PROVIDER_RESPONSE_LIMIT', 'INVALID_MODEL_JSON',
        }:
            raise
        # Transport/JSON failure consumes the SAME one remaining header call;
        # it must not acquire a third format/context attempt or a fresh root.
        raw, receipt = await ask(prompt)
        followup_used = True
    columns = {c['name'] for c in table['columns']}
    allowed = {b['property_id'] for b in spec['properties']}
    try:
        plan, gaps, resolution = validate(raw, columns, allowed, targets)
    except DomainError as exc:
        if exc.code != 'CATALOG_PLAN_INVALID':
            raise
        if followup_used:
            raise
        repair = {**prompt, 'previous_invalid_plan':
            {k: type(v).__name__ for k, v in raw.items()} if isinstance(raw, dict) else type(raw).__name__,
            'format_error': exc.code,
            'repair_instruction': 'Repair the JSON envelope only. Use the complete stated contract, including column_resolution for target batches. No invented columns, units or expanded property scope.'}
        raw, receipt = await ask(repair)
        followup_used = True
        plan, gaps, resolution = validate(raw, columns, allowed, targets)
    plan, preservation = retain_declared_errors(plan, table)
    missing = required_fields(plan) - visible_columns(prompt)
    repairable = [g for g in gaps if g.get('reason') in {'column_mapping_schema', 'source_representation_schema',
        'linked_column_not_available', 'limit_column_not_available'}]
    repair_values = {m['value_column'] for g in repairable if isinstance(m := g.get('raw_mapping'), dict)
                     and isinstance(m.get('value_column'), str) and m['value_column'] in columns}
    if (missing or repairable) and not followup_used:
        try:
            followup = prompt_factory(table, spec, targets, required=required_fields(plan) | repair_values)
        except DomainError as exc:
            if exc.code != 'CATALOG_CONTEXT_REQUIRES_PARTITION':
                raise
            gaps.append({'reason': 'required_context_exceeds_shared_followup_bound', 'columns': sorted(missing)})
        else:
            followup['context_completion'] = {'previous_plan': plan, 'invalid_field_groups': repairable,
                'instruction': 'Recheck proposed groups with the newly supplied full field metadata. Return the same complete JSON contract, preserving independent valid groups. This is the only shared format/context follow-up.'}
            if len(canonical(followup)) > MAX_HEADER_BYTES:
                gaps.append({'reason': 'required_context_with_proposal_exceeds_followup_bound', 'columns': sorted(missing)})
            else:
                followup_used = True
                try:
                    proposed, next_receipt = await ask(followup)
                    checked, checked_gaps, checked_resolution = validate(proposed, columns, allowed, targets)
                except (DomainError, httpx.TransportError, TimeoutError) as exc:
                    code = getattr(exc, 'code', type(exc).__name__)
                    if isinstance(exc, DomainError) and code not in {'CATALOG_PLAN_INVALID', 'PROVIDER_HTTP_ERROR', 'MODEL_PROGRESS_TIMEOUT',
                        'PROVIDER_RESPONSE_LIMIT', 'INCOMPLETE_MODEL_RESPONSE', 'INVALID_MODEL_JSON', 'MODEL_INPUT_LIMIT'}:
                        raise
                    gaps.append({'reason': 'shared_context_followup_failed', 'failure': code,
                        'affected_columns': sorted(missing), 'independent_initial_groups_retained': True})
                else:
                    plan, more_checks = retain_declared_errors(checked, table)
                    preservation.extend(c for c in more_checks if c not in preservation)
                    gaps, resolution, prompt, receipt = checked_gaps, checked_resolution, followup, next_receipt
    plan, unseen = quarantine_unseen(plan, visible_columns(prompt))
    gaps.extend(unseen)
    invalid_values = {g['value_column'] for g in unseen}
    resolution = [{**r, 'role': 'unresolved', 'reason': 'required_field_metadata_not_read'}
                  if r['column'] in invalid_values else r for r in resolution]
    return {'plan': plan, 'gaps': gaps, 'column_resolution': resolution, 'receipt': receipt,
        'source_preservation_checks': preservation,
        'metadata_visible_columns': sorted(visible_columns(prompt)), 'shared_followup_used': followup_used}
