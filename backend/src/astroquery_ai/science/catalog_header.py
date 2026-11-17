"""One production/calibration header interpreter with a shared two-call ceiling."""
from copy import deepcopy

import httpx
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from .catalog_context import MAX_HEADER_BYTES, required_fields, visible_columns, quarantine_unseen, retain_declared_errors

HEADER_VERSION = 'column-context-9'
QUANTITY_RECHECK_VERSION = 'column-quantity-recheck/1'


def unresolved_quantities(plan):
    return [m for m in plan['properties'] if m.get('quantity_match') == 'unresolved']


def merge_quantity_recheck(previous, proposed):
    """A column recheck cannot erase or rewrite an independent valid sibling.

    An omitted uncertain mapping is not proof that its measurand is different.
    Keep it unresolved unless the response explicitly resolves that same pair.
    """
    pairs = {(m['property_id'], m['value_column']): m for m in proposed['properties']}
    properties = []
    for mapping in previous['properties']:
        candidate = pairs.get((mapping['property_id'], mapping['value_column']))
        properties.append(candidate if mapping.get('quantity_match') == 'unresolved' and candidate else mapping)
    return {**previous, 'properties': properties,
            'limitations': list(dict.fromkeys([*previous['limitations'], *proposed['limitations']]))}


async def interpret_header(table, spec, targets, *, prompt_factory, validate, ask, initial=None):
    prompt = prompt_factory(table, spec, targets)
    columns = {c['name'] for c in table['columns']}
    allowed = {b['property_id'] for b in spec['properties']}
    if initial is not None:
        # The caller verifies the immutable table/property/schema hashes before
        # supplying a saved plan. A resumed job consumes only its remaining call.
        plan, gaps, resolution = (deepcopy(initial[k]) for k in ('plan', 'gaps', 'column_resolution'))
        receipt = {'attempt_id': initial['model_attempt_id']}
        preservation = deepcopy(initial['source_preservation_checks'])
        followup_used = initial['shared_followup_used']
    else:
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
    uncertain = unresolved_quantities(plan)
    quantity_recheck = {'version': QUANTITY_RECHECK_VERSION, 'attempted': False,
                        'pairs': [{'property_id': m['property_id'], 'value_column': m['value_column']} for m in uncertain]}
    if (missing or repairable or uncertain) and not followup_used:
        try:
            followup = prompt_factory(table, spec, targets, required=required_fields(plan) | repair_values)
        except DomainError as exc:
            if exc.code != 'CATALOG_CONTEXT_REQUIRES_PARTITION':
                raise
            gaps.append({'reason': 'required_context_exceeds_shared_followup_bound', 'columns': sorted(missing)})
        else:
            followup['context_completion'] = {'previous_plan': plan, 'invalid_field_groups': repairable,
                'instruction': 'Recheck proposed groups with the newly supplied full field metadata. Return the same complete JSON contract, preserving independent valid groups. This is the only shared format/context follow-up.'}
            if uncertain:
                followup['context_completion']['quantity_recheck'] = {
                    'pairs': quantity_recheck['pairs'],
                    'instruction': 'Resolve each listed source-column/requested-property pair from its complete original definition and table notes ONCE, before reading individual rows. '
                        'Same units or possible derivability do not establish the same physical measurand. For each pair explicitly retain a mapping with quantity_match=exact, different, or unresolved. '
                        'Use different only when the original definition establishes a different measurand; preserve its source unit, errors and contexts for the audit. '
                        'Leave unresolved when semantics depend on per-row content or the evidence is insufficient. Do not guess a value, convert units, invent a definition, drop an uncertain pair, or change an independent exact mapping.'}
            if len(canonical(followup)) > MAX_HEADER_BYTES:
                gaps.append({'reason': 'required_context_with_proposal_exceeds_followup_bound', 'columns': sorted(missing)})
            else:
                followup_used = True
                quantity_recheck['attempted'] = bool(uncertain)
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
                    if uncertain and not (missing or repairable):
                        checked = merge_quantity_recheck(plan, checked)
                        # Only these mappings were reconsidered. Other field
                        # roles and their original evidence remain unchanged.
                        resolution = [{**r} for r in resolution]
                        checked_resolution = resolution
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
        'metadata_visible_columns': sorted(visible_columns(prompt)), 'shared_followup_used': followup_used,
        'quantity_recheck': quantity_recheck}
