"""Explicit source declarations, separate from a missing unit or a target unit."""
import re


def catalog_unit_declaration(source, column_name, *, proposed_unit=None):
    table = source.get('metadata', {})
    document = table.get('catalog_document') or {}
    if document.get('parsed', {}).get('state') != 'table_layout_identified' or not document.get('artifact_ref'):
        return None
    columns = [c for c in table.get('columns', []) if c['name'] == column_name]
    spans = document['parsed'].get('fields', {}).get(column_name, [])
    if (len(columns) != 1 or len(spans) != 1 or columns[0].get('unit_text') is not None
            or columns[0].get('datatype') not in {'unsignedByte', 'short', 'int', 'long', 'float', 'double'}):
        return None
    token = spans[0].get('unit_token')
    if token == '---':
        inline = re.findall(r'\((?:in|units of)\s+([^()]+)\)', spans[0]['text'], re.I)
        if len(inline) == 1:
            try:
                from .units import parse_unit
                parse_unit(inline[0].strip())
            except (ValueError, TypeError):
                return None
            token = inline[0].strip()
    if token == '---' and proposed_unit not in {None, '1', 'dimensionless'}:
        # CDS --- is also used when a linked note defines the physical unit.
        # Never overwrite an explicitly interpreted source footnote unit with 1.
        return None
    if not token or any(c in token for c in '[]{}'):
        return None  # A log/encoded coordinate needs separate source interpretation.
    symbol = '1' if token == '---' else token
    try:
        from .units import parse_unit
        parse_unit(symbol)
    except (ValueError, TypeError):
        return None
    return {'schema_version': 'SourceUnitDeclaration/1', 'kind': 'dimensionless' if token == '---' else 'source_declared_unit', 'canonical_symbol': symbol,
        'raw_unit_text': None, 'source_literal': token, 'artifact_ref': document['artifact_ref'],
        'locator': {'table': table['table_id'], 'column': column_name,
            'line_start': spans[0]['line_start'], 'line_end': spans[0]['line_end'],
            **({'line_coordinate':document['parsed']['text_view']['line_coordinate'],
                'original_utf8_sha256':document['parsed']['text_view']['original_utf8_sha256']} if document['parsed'].get('text_view') else {})},
        'raw_quote': spans[0]['text'], 'rule': 'cds-numeric-unitless-1' if token == '---' else 'cds-numeric-unit-1',
        'format_basis': 'https://vizier.cds.unistra.fr/doc/catstd-3.2.htx'}


def execution_unit(record):
    """Return an arithmetic unit, without changing the stored raw-unit field."""
    if not isinstance(record, dict):
        record = record.model_dump()
    declaration = record.get('unit_declaration')
    if record.get('unit') is None and declaration and declaration.get('kind') in {'dimensionless', 'source_declared_unit'}:
        return declaration['canonical_symbol']
    return record.get('unit')


def dimensionless_coordinate_declaration(proposal, binding, verification, artifact_ref):
    """Keep an absent printed unit absent; bind the evidenced ratio coordinate."""
    check = (verification or {}).get('check', {})
    if (proposal.get('unit') is not None or proposal.get('representation') not in {'log10','ln'}
            or binding.get('output_profile',{}).get('unit',{}).get('kind') != 'dimensionless'
            or (verification or {}).get('state') != 'passed' or check.get('quantity_match') != 'exact'
            or not (check.get('native_unit')=='1' and check.get('unit_match')=='exact'
                    and check.get('unit_evidence') or verification.get('dimensionless_native_coordinate'))):
        return None
    anchors=check.get('unit_evidence') or check.get('quantity_evidence',[])
    blocks = {b['block_id']:b for b in verification.get('source_information_blocks',[])}
    quotes = [blocks[k]['text'] for a in anchors for k in a.get('block_ids',[])
              if k in blocks and blocks[k]['page'] == a['page']]
    # Passed admission has resolved these anchors against the actual blocks.
    # Source-quality notes are a separate use and need not repeat unit anchors.
    quotes += [a['quote'] for a in anchors if a.get('quote')]
    if not quotes:
        return None
    return {'schema_version':'SourceUnitDeclaration/1','kind':'dimensionless','canonical_symbol':'1',
        'raw_unit_text':None,'source_literal':None,'artifact_ref':artifact_ref,
        'locator':{'page':anchors[0]['page'],'basis':'independent_original_coordinate_definition'},
        'raw_quote':'\n'.join(dict.fromkeys(quotes)),
        'rule':'independently_evidenced_dimensionless_log_coordinate-1',
        'format_basis':'Exact reviewed quantity and independent original coordinate definition; no printed unit invented.'}


def unit_record_text(record):
    return execution_unit({'unit': record.get('unit_text'), 'unit_declaration': record.get('unit_declaration')})


def output_coordinate_unit(profile):
    """Interpret a reviewed coefficient encoding without rewriting its profile.

    Percentage is dimensionless physically, but its displayed coefficient uses
    percent as the arithmetic unit. These are vocabulary aliases for the same
    encoding, independent of object, property ID, source and observed value.
    """
    unit = profile['unit']
    if unit.get('canonical_symbol'):
        return unit['canonical_symbol']
    encodings = {'percentage': '%', 'polarization_percentage': '%'}
    if unit.get('kind') == 'dimensionless' and unit.get('semantic_kind') in encodings:
        return encodings[unit['semantic_kind']]
    return '1'


def arithmetic_coordinate_units(record, profile):
    """A declared count coordinate has coefficient 1, with no rate equivalency.

    This supplies arithmetic only. Exact quantity/subject/source evidence and
    the reviewed operation still have to pass independently. Raw ct/--- and
    all error unit records remain unchanged.
    """
    native,target=execution_unit(record),output_coordinate_unit(profile)
    unit=profile['unit']
    if (_count_coordinate(profile)
            and record['representation']=='linear' and profile['representation']['kind']=='linear'
            and native in {'ct','count','counts','1','dimensionless'}):
        return '1','1'
    return native,target


def intrinsic_count_binding(binding):
    return _count_coordinate(binding.get('output_profile',{}))


def _count_coordinate(profile):
    # Both are explicit author-reviewed count coordinates. Do not infer counts
    # from a property name, prose column label, ratio or count-rate dimension.
    unit=profile.get('unit',{})
    return unit.get('kind')=='dimensionless' and unit.get('semantic_kind') in {
        'count','count under exact source definition'}


def count_unit_declaration(source, proposal, binding, *, artifact_ref, paper_verification=None):
    """A source-evidenced count, preserving the absent native unit literally."""
    if (not intrinsic_count_binding(binding) or proposal.get('unit') is not None
            or proposal.get('representation')!='linear' or proposal.get('value',{}).get('kind') not in {'real','integer'}):
        return None
    if source.get('kind') in {'catalog','official_attachment'}:
        column=next((c for c in source.get('metadata',{}).get('columns',[]) if c['name']==proposal.get('column')),None)
        if (proposal.get('quantity_match')!='exact' or proposal.get('column') not in proposal.get('catalog_quantity_evidence',[])
                or not column or column.get('unit_text') is not None or not column.get('description')):
            return None
        locator={'table':source['table_id'],'column':column['name'],'row':proposal['row']}
        quote=column['description']
    else:
        if not paper_verification or paper_verification.get('state')!='passed' or not paper_verification.get('intrinsic_count_coordinate'):
            return None
        basis=paper_verification['intrinsic_count_coordinate']
        locator={'page':proposal['page']}
        quote='\n'.join(a['quote'] for a in basis['quantity_evidence'] if a.get('quote'))
        if not quote:return None
    return {'schema_version':'SourceUnitDeclaration/1','kind':'dimensionless','canonical_symbol':'1',
        'raw_unit_text':None,'source_literal':None,'rule':'evidenced_intrinsic_count_coordinate-1',
        'artifact_ref':artifact_ref,'locator':locator,'raw_quote':quote,
        'format_basis':'Intrinsic count in the exact reviewed measurand, supported by original quantity evidence; no printed physical unit is invented.'}


def catalog_representation_declaration(source, record, interpretation):
    """Read the actual CDS/VOUnits column coordinate, never a prose default.

    CDS catalogue standard §3.2: [solMass] denotes the decimal logarithm of a
    quantity expressed in solar masses. The format itself supplies reference 1.
    https://vizier.cds.unistra.fr/vizier/doc/catstd-3.htx
    """
    if source.get('kind') not in {'catalog', 'official_attachment'} or record['representation'] != 'log10':
        return None
    column = interpretation['proposal'].get('column')
    fields = [c for c in source.get('metadata', {}).get('columns', []) if c['name'] == column]
    if len(fields) != 1:
        return None
    token = fields[0].get('unit_text')
    if not isinstance(token, str) or token != record.get('unit'):
        return None
    bracket = re.fullmatch(r'\[([^\[\]]+)\]', token)
    vounit = re.fullmatch(r'log\(([^()]+)\)', token)
    if not (bracket or vounit):
        return None
    from .units import parse_unit
    unit = (bracket or vounit)[1]
    try:
        parse_unit(unit)
    except (ValueError, TypeError):
        return None
    # VizieR's VOUnits export maps CDS [unit] to log(unit). Both declarations
    # identify the coordinate, not a newly computed logarithm. If an associated
    # layout is available, keep its exact field and reject conflicting bases.
    document = source.get('metadata', {}).get('catalog_document') or {}
    parsed = document.get('parsed', {})
    provenance = {}
    if parsed.get('state') == 'table_layout_identified':
        table_id = source.get('table_id') or source.get('metadata', {}).get('table_id')
        if parsed.get('table_id') != table_id:
            return None
        spans = parsed.get('fields', {}).get(column, [])
        if len(spans) > 1:
            return None
        if spans:
            original = spans[0].get('unit_token')
            if original != '[' + unit + ']':
                return None
            if not document.get('artifact_ref'):
                return None
            provenance = {'catalog_document_ref': document.get('document_ref'),
                'artifact_ref': document['artifact_ref'], 'locator': {
                    'table': table_id, 'column': column,
                    'line_start': spans[0]['line_start'], 'line_end': spans[0]['line_end']},
                'raw_quote': spans[0]['text']}
    return {'schema_version': 'SourceRepresentationDeclaration/1', 'rule': 'cds-vounit-decimal-log-2',
            'source_ref': record['source_ref'], 'source_hash': record['content_sha256'],
            'column': column, 'native_unit_text': token, 'field_metadata': fields[0],
            **provenance,
            'parameters': {'kind': 'log10', 'scale': '1', 'offset': '0', 'reference_value': '1', 'reference_unit': unit},
            'format_basis': 'https://vizier.cds.unistra.fr/vizier/doc/catstd-3.htx',
            'export_format_basis': 'https://wiki.ivoa.net/internal/IVOA/InterOpApr2022Ops/VizieR_VOUnits.pdf#page=5'}
