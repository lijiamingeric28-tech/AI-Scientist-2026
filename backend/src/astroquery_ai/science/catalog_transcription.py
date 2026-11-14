'Verify literal table fields without interpreting scientific error semantics.'

from decimal import Decimal, InvalidOperation

import re

from astroquery_ai.science.measurements.contracts import ErrorProposal, ReportedReferenceProposal, ConditionProposal

def native_cell_state(row, name, columns):
    """Only the actual cell and its declared null code establish missingness."""
    field = next((c for c in columns if c['name'] == name), None)
    if field is None or name not in row:
        return 'absent_field'
    value = row[name]
    if value is None or (isinstance(value, str) and (not value.strip())):
        return 'empty_cell'
    if isinstance(value, str) and field.get('null') is not None and (value.strip() == field['null']):
        return 'declared_null'
    return 'reported_token'

def declared_uncertainty_relation(column):
    description = column.get('description') or ''
    ucds = set((column.get('ucd') or '').split(';'))
    if 'stat.covariance' in ucds or re.search('covariance.*(?:uncertaint|errors)', description, re.I):
        return 'covariance'
    if 'stat.correlation' in ucds or re.search('correlation coefficient.*(?:uncertaint|errors)', description, re.I):
        return 'correlation'
    return None

def reported_uncertainty_context(source, doc, evidence, evref):
    """Separate literal row fields; association with particular axes is unknown.

    This survives an omitted model header mapping without claiming a new
    measurement, covariance matrix, confidence level or independence.
    """
    from astroquery_ai.runtime.codec import canonical, digest, loads
    try:
        cells = loads(doc['source_quote'])['cells']
    except (ValueError, TypeError, KeyError):
        return []
    result = []
    for column in source.get('metadata', {}).get('columns', []):
        name, value = (column['name'], cells.get(column['name']))
        if not declared_uncertainty_relation(column) or not isinstance(value, str) or (not value.strip()):
            continue
        if value.strip() == column.get('null'):
            continue
        field_id = 'source-field-' + digest({'artifact': evidence['artifact_ref'], 'source': source['source_id'], 'row': doc['row'], 'column': name})
        result.append({'source_field_id': field_id, 'kind': 'source_reported_table_uncertainty_context', 'column': name, 'row': doc['row'], 'reported_value': value, 'reported_relation_kind': declared_uncertainty_relation(column), 'source_column_metadata': column, 'axis_binding_state': 'unresolved', 'text': name + '=' + value + ': ' + (column.get('description') or name) + '；源表相关字段已独立保存，具体误差轴及适用关系尚未核实，不能据此假定独立。', 'raw_quote': canonical({'column': name, 'cell': value, 'metadata': column}).decode(), 'artifact_ref': evidence['artifact_ref'], 'evidence_refs': [evref], 'origin': 'server_preserved_original_table_context', 'transcription_state': 'literal_verified_row_and_column', 'eligible_for_comparison': False, 'grants_retrieval': False})
    return result

def preserve_catalog_fields(proposal, row, mapping, columns):
    """Retain omitted source fields; malformed optional errors never erase the value."""
    metadata = {column['name']: column for column in columns}
    document = mapping.get('source_document') or {}
    role_checks, resolved_context = ([], {})
    mapping={**mapping,'error_columns':list(mapping.get('error_columns',[])),
             'reference_columns':list(mapping.get('reference_columns',[])),
             'quality_columns':list(mapping.get('quality_columns',[]))}
    main_column = mapping.get('value_column', proposal.column)
    try:
        plain_numeric_main = Decimal(str(row.get(main_column, '')).strip()).is_finite()
    except InvalidOperation:
        plain_numeric_main = False
    if plain_numeric_main and main_column in mapping['error_columns']:
        mapping = {**mapping, 'error_columns': [n for n in mapping['error_columns'] if n != main_column]}
        role_checks.append({'field': main_column, 'state': 'plain_numeric_main_not_its_own_uncertainty'})
    for interpretation in proposal.catalog_field_roles:
        column = metadata.get(interpretation.column)
        if (not column or interpretation.column not in row or interpretation.column == main_column
                or interpretation.column not in mapping.get('provided_auxiliary_columns',metadata)):
            continue
        from .catalog_document import document_view
        view = document_view(document, [interpretation.column], list(metadata))
        source_texts = [column.get('description') or '']
        source_texts += [s['text'] for values in view['field_descriptions'].values() for s in values]
        source_texts += [s['text'] for values in view['notes'].values() for s in values]
        if not any((interpretation.source_quote in text for text in source_texts)):
            role_checks.append({'field': interpretation.column, 'state': 'unbound_field_role_not_applied'})
        elif interpretation.role == 'uncertainty':
            if interpretation.column not in mapping['error_columns']:
                mapping['error_columns'].append(interpretation.column)
                role_checks.append({'field':interpretation.column,'state':'source_evidenced_auxiliary_plan_amendment',
                                    'interpretation':interpretation.model_dump(mode='json')})
        elif interpretation.role == 'reference':
            mapping['reference_columns']=list(dict.fromkeys([*mapping['reference_columns'],interpretation.column]))
            role_checks.append({'field':interpretation.column,'state':'source_evidenced_reference_plan_amendment'})
        elif interpretation.role in {'quality','limit'}:
            resolved_context[interpretation.column]=interpretation
            role_checks.append({'field':interpretation.column,'state':'source_evidenced_auxiliary_context',
                                'interpretation':interpretation.model_dump(mode='json')})
        elif interpretation.role == 'context':
            resolved_context[interpretation.column] = interpretation
            role_checks.append({'field': interpretation.column, 'state': 'source_evidenced_context_not_uncertainty', 'interpretation': interpretation.model_dump(mode='json')})
    if resolved_context:
        mapping = {**mapping, 'error_columns': [n for n in mapping['error_columns'] if n not in resolved_context], 'context_columns': list(dict.fromkeys([*mapping.get('context_columns', []), *resolved_context]))}
        conditions = list(proposal.conditions)
        for name, role in resolved_context.items():
            if row.get(name) is not None and (not any((c.state == 'known' and str(c.value) == str(row[name]) and (name in (c.raw_text or '')) for c in conditions))):
                conditions.append(ConditionProposal(key=role.context_key or 'source_field:' + name, value=row[name], state='known', raw_text=name + ': ' + str(row[name])))
        proposal = proposal.model_copy(update={'errors': [e for e in proposal.errors if e.location not in resolved_context], 'conditions': conditions})

    def unknown_code(name):
        if document.get('parsed', {}).get('state') != 'table_layout_identified' or not document.get('artifact_ref'):
            return None
        spans = document['parsed'].get('fields', {}).get(name, [])
        if len(spans) != 1:
            return None
        match = re.search('(?:^|\\s)\\?=([^\\s,;]+)', spans[0]['text'])
        if not match or not isinstance(row.get(name), str):
            return None
        token, value = (match[1], row[name].strip())
        try:
            agrees = Decimal(token).is_finite() and Decimal(value).is_finite() and (Decimal(token) == Decimal(value))
        except InvalidOperation:
            agrees = token == value
        return token if agrees else None

    def present(name):
        value = row.get(name)
        return isinstance(value, str) and bool(value.strip()) and (value.strip() != metadata.get(name, {}).get('null'))

    def locator(label, names, raw):
        if label in names and row.get(label) == raw:
            return label
        candidates = [name for name in names if row.get(name) == raw and re.search('(?<![\\w])' + re.escape(name) + '(?![\\w])', label)]
        return candidates[0] if len(candidates) == 1 else None
    errors, checks = ([], role_checks)
    for error in proposal.errors:
        if plain_numeric_main and error.location == main_column:
            checks.append({'field': main_column, 'state': 'plain_numeric_main_not_its_own_uncertainty', 'model_proposal': error.model_dump(mode='json')})
            continue
        # Multiple native endpoint columns remain one reported interval, not
        # two invented symmetric uncertainties. Both cells must be explicit.
        endpoint_columns=[a.column for a in error.catalog_semantics_evidence
                          if a.column in mapping['error_columns']]
        interval_bound=False
        if error.kind=='interval_endpoints' and error.interpretation_state=='parsed' and error.values:
            endpoints=[error.values.get(k) for k in ('lower','upper') if error.values.get(k) is not None]
            interval_bound=bool(endpoints) and all(any(str(v)==str(row.get(n)) for n in endpoint_columns) for v in endpoints)
            if interval_bound:
                raw='; '.join(n+'='+str(row[n]) for n in dict.fromkeys(endpoint_columns))
                error=error.model_copy(update={'raw_text':raw,'location':','.join(dict.fromkeys(endpoint_columns))})
                checks.append({'field':error.location,'state':'native_interval_endpoint_cells_bound',
                               'columns':list(dict.fromkeys(endpoint_columns))})
        resolved = locator(error.location, [*mapping['error_columns'], mapping.get('value_column', proposal.column)], error.raw_text)
        if resolved is None:
            value_column = mapping.get('value_column', proposal.column)
            main_cell = row.get(value_column, '')
            try:
                Decimal(main_cell.strip())
            except (InvalidOperation, AttributeError):
                if isinstance(main_cell, str) and error.raw_text in main_cell and re.search('(?<![\\w])' + re.escape(value_column) + '(?![\\w])', error.location):
                    resolved = value_column
        if resolved is None and error.location not in mapping['error_columns'] and not interval_bound:
            checks.append({'field': error.location, 'state': 'unverified_error_not_admitted', 'model_proposal': error.model_dump(mode='json')})
            continue
        if resolved is not None and resolved != error.location:
            checks.append({'field': resolved, 'state': 'descriptive_locator_verified_against_exact_field_and_cell', 'original_locator': error.location})
            error = error.model_copy(update={'location': resolved})
        actual_error_unit = metadata.get(error.location, {}).get('unit_text')
        if actual_error_unit is not None:
            error = error.model_copy(update={'source_unit': actual_error_unit})
        quotes = {}
        for anchor in error.catalog_semantics_evidence:
            description = metadata.get(anchor.column, {}).get('description') or ''
            from .catalog_document import document_view
            view = document_view(document, [error.location], list(metadata))
            document_spans = [span['text'] for spans in view['field_descriptions'].values() for span in spans]
            document_spans += [span['text'] for spans in view['notes'].values() for span in spans]
            if view.get('catalog_scope'):
                document_spans.append(view['catalog_scope']['text'])
            if anchor.column == error.location and (anchor.quote in description or any((anchor.quote in text for text in document_spans))):
                quotes.setdefault(anchor.aspect, []).append(anchor.quote)
        updates = {}
        if error.role != 'unspecified' and (not quotes.get('role')):
            updates['role'] = 'unspecified'
        if error.meaning not in {'reported_error', 'unspecified'}:
            meaning = ' '.join(quotes.get('meaning', []))
            standard = re.search('\\bstandard (?:uncertaint|deviation)|\\b1\\s*[- ]?sigma\\b|\\bone[- ]sigma\\b|标准(?:差|不确定度)', meaning, re.I)
            if not meaning or (error.meaning == 'standard_uncertainty' and (not standard)):
                updates['meaning'] = 'reported_error'
        if error.level_kind is not None and (not quotes.get('level') or not error.level_raw_text or (not any((error.level_raw_text in quote for quote in quotes['level'])))):
            updates.update(level_kind=None, level_values=[], level_raw_text=None)
        if updates:
            checks.append({'field': error.location, 'state': 'unsupported_error_semantics_not_promoted', 'original_role': error.role, 'original_meaning': error.meaning, 'original_level_kind': error.level_kind})
            error = error.model_copy(update=updates)
        code = unknown_code(error.location)
        if code is not None:
            error = error.model_copy(update={'kind': 'other_reported', 'values': None, 'interpretation_state': 'unresolved', 'reason': 'source_declared_unknown_code'})
            checks.append({'field': error.location, 'state': 'source_declared_unknown_code', 'raw_text': error.raw_text, 'declared_code': code, 'document_ref': document['artifact_ref']})
        if error.location in mapping['error_columns']:
            actual = row.get(error.location)
            if not present(error.location) or error.raw_text != actual:
                checks.append({'field': error.location, 'state': 'model_error_transcription_replaced_with_source_raw'})
                continue
            if error.interpretation_state == 'parsed' and error.kind in {'symmetric_delta', 'variance', 'inverse_variance'}:
                try:
                    source_number = Decimal(actual.strip())
                except InvalidOperation:
                    pass
                else:
                    candidate = (error.values or {}).get('delta')
                    try:
                        agrees = isinstance(candidate, str) and source_number.is_finite() and (Decimal(candidate) == source_number)
                    except InvalidOperation:
                        agrees = False
                    if not agrees:
                        error = error.model_copy(update={'interpretation_state': 'unresolved', 'values': None, 'reason': 'numeric_error_cell_transcription_mismatch_or_missing'})
                        checks.append({'field': error.location, 'state': 'numeric_error_requires_interpretation'})
        errors.append(error)
    for name in mapping['error_columns']:
        if present(name) and (not any((error.location == name or name in [a.column for a in error.catalog_semantics_evidence] for error in errors))):
            errors.append(ErrorProposal(location=name, raw_text=row[name], kind='other_reported', values=None, role='unspecified', meaning='unspecified', interpretation_state='unresolved', reason='source_error_column_not_interpreted', source_unit=metadata.get(name, {}).get('unit_text')))
            checks.append({'field': name, 'state': 'omitted_error_raw_preserved'})
            if unknown_code(name) is not None:
                errors[-1] = errors[-1].model_copy(update={'reason': 'source_declared_unknown_code'})
    for name in mapping.get('context_columns', []):
        column = metadata.get(name, {})
        correlation = declared_uncertainty_relation(column)
        if correlation and present(name) and (not any((e.location == name for e in errors))):
            errors.append(ErrorProposal(location=name, raw_text=row[name], kind=correlation, values=None, role='unspecified', meaning='reported_error', interpretation_state='unresolved', reason='source_declared_correlation_preserved_axes_and_dependencies_not_yet_interpreted', source_unit=column.get('unit_text')))
            checks.append({'field': name, 'state': 'source_declared_correlation_raw_preserved'})
    main_column = mapping.get('value_column', proposal.column)
    main_cell = row.get(main_column)
    if proposal.value.kind in {'real', 'integer'} and (not errors) and isinstance(main_cell, str) and re.search('±|\\d\\(\\d+\\)', main_cell):
        errors.append(ErrorProposal(location=main_column, raw_text=main_cell, kind='other_reported', values=None, role='unspecified', meaning='unspecified', interpretation_state='unresolved', reason='composite_source_uncertainty_not_interpreted'))
        checks.append({'field': main_column, 'state': 'composite_uncertainty_raw_preserved_unresolved'})
    references = [ReportedReferenceProposal(raw_code=row[name], location=name) for name in mapping.get('reference_columns', []) if present(name)]
    for reference in proposal.source_references:
        if reference.location not in mapping.get('reference_columns', []) or row.get(reference.location) != reference.raw_code:
            checks.append({'field': reference.location, 'state': 'unverified_model_reference_not_admitted'})
    updates = {'errors': errors, 'source_references': references}
    if isinstance(main_cell, str):
        if main_cell != proposal.raw_value:
            checks.append({'field': main_column, 'state': 'main_raw_text_restored_from_actual_cell'})
        updates['raw_value'] = main_cell
        if (plain_numeric_main and proposal.value.kind in {'real','integer'} and proposal.limit=='none'
                and proposal.representation in {'linear','log10','ln','magnitude'}):
            updates['value']=proposal.value.model_copy(update={'value':main_cell.strip()})
            checks.append({'field':main_column,'state':'native_scalar_coefficient_copied_without_conversion'})
        if proposal.value.kind == 'text':
            updates['value'] = proposal.value.model_copy(update={'value': main_cell})
            updates['unit'] = metadata.get(main_column, {}).get('unit_text')
        elif metadata.get(main_column, {}).get('unit_text') is not None:
            if proposal.unit != metadata[main_column]['unit_text']:
                checks.append({'field': main_column, 'state': 'source_unit_restored_from_actual_metadata'})
            updates['unit'] = metadata[main_column]['unit_text']
    return (proposal.model_copy(update=updates), checks)
