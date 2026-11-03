"""Offline uncertainty examples used by the interpretation and wire tests."""
from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.science.uncertainty_interpretation import available_spans, prompt

def cases(*, final_round=False, definitions_override=None, error_units=None):
    definitions = [
        ('literal-stat', '7.25', '0.34', 'Statistical uncertainty of Length',
         [('symmetric_delta', {'delta': '0.34'}, 'stat', None)]),
        ('asymmetric', '7.25', '-0.21,+0.46', 'Reported lower and upper uncertainty offsets of Length',
         [('asymmetric_delta', {'minus': '0.21', 'plus': '0.46'}, 'unspecified', None)]),
        ('last-digits', '2.531(7)', '2.531(7)', 'Length(error); parenthesized digits are uncertainty in the last quoted decimal places',
         [('symmetric_delta', {'delta': '0.007'}, 'unspecified', None)]),
        ('separate-stat-sys', '7.25', '0.12 stat; 0.08 sys', 'Two separately reported uncertainty components',
         [('symmetric_delta', {'delta': '0.12'}, 'stat', None), ('symmetric_delta', {'delta': '0.08'}, 'sys', None)]),
        ('percent-without-basis', '7.25', '3.5%', 'Reported percent error; denominator definition not supplied', None),
        ('no-confidence-level', '7.25', '0.21', 'Reported error; confidence level and statistical meaning are not stated',
         [('symmetric_delta', {'delta': '0.21'}, 'unspecified', None)]),
        ('confidence-endpoints', '7.25', '[6.8,8.2]', '95% confidence interval endpoints of Length',
         [('interval_endpoints', {'kind': 'interval', 'lower': '6.8', 'upper': '8.2', 'lower_closed': True, 'upper_closed': True},
           'unspecified', ('confidence_probability', ['0.95']))]),
        ('matrix-without-axes', '7.25', '[[0.21,0.03],[0.03,0.4]]', 'Covariance matrix; axis identities are missing', None),
    ]
    if final_round:
        definitions = [
            ('separate-stat-sys-new', '7.50', '0.17 stat; 0.09 sys', 'Two separately reported uncertainty components',
             [('symmetric_delta', {'delta': '0.17'}, 'stat', None), ('symmetric_delta', {'delta': '0.09'}, 'sys', None)]),
            ('confidence-endpoints-new', '7.50', '[6.75,8.30]', '90% confidence interval endpoints of Length',
             [('interval_endpoints', {'kind': 'interval', 'lower': '6.75', 'upper': '8.30', 'lower_closed': True, 'upper_closed': True},
               'unspecified', ('confidence_probability', ['0.9']))]),
        ]
    if definitions_override is not None:
        definitions = definitions_override
    items = []
    for name, main, raw, description, expected in definitions:
        error = {'location': 'e_Length', 'raw_text': raw, 'kind': 'other_reported', 'values': None,
            'role': 'unspecified', 'meaning': 'reported_error', 'interpretation_state': 'unresolved',
            'reason': 'SYNTHETIC first reader left unresolved', 'source_unit': None,
            'relative_basis': None, 'level_kind': None, 'level_values': [], 'level_raw_text': None,
            'semantics_evidence': []}
        numeric_main = main.split('(')[0] + (main.split(')', 1)[1] if ')' in main else '')
        proposal = {'property_id': 'SYNTHETIC-length', 'value': {'kind': 'real', 'value': numeric_main},
            'raw_value': main, 'unit': 'm', 'representation': 'linear', 'source_quote': '',
            'page': None, 'row': 0, 'column': 'Length', 'subject_role': 'target', 'result_role': 'reported_result',
            'location_kind': 'catalog_cell', 'limit': 'none', 'errors': [error], 'conditions': [],
            'ambiguity': None, 'representation_parameters': None, 'location_label': None,
            'source_quality': None, 'source_references': [], 'local_admission': None}
        ref = {'id': 'SYNTHETIC-ref', 'version': 1, 'content_sha256': '0' * 64}
        component = {'component_id': 'SYNTHETIC-' + name, 'interpretation_state': 'unresolved',
            'kind': 'other_reported', 'values': None, 'role': 'unspecified', 'raw_label': 'unspecified',
            'statistical_meaning': 'reported_error', 'level': None, 'representation_ref': ref,
            'unit_ref': ref, 'basis_ref': None, 'axes': [], 'dependency_refs': [], 'evidence_refs': [ref],
            'raw_text': raw, 'interpretation_provenance': ref, 'reason': 'SYNTHETIC unresolved'}
        record = {'measurement_id': 'SYNTHETIC-' + name, 'content_sha256': digest(proposal),
            'raw_value': main, 'value': proposal['value'], 'unit': 'm', 'representation': 'linear',
            'uncertainty': {'components': [component]}}
        interpretation = {'proposal': proposal}
        evidence = {'text_origin': 'original_cells', 'raw_text': canonical({
            'cells': {'Length': main, 'e_Length': raw},
            'columns': [{'name': 'Length', 'unit_text': 'm', 'description': 'SYNTHETIC length'},
                        {'name': 'e_Length', 'unit_text': (error_units or {}).get(name, None if expected is None else 'm'), 'description': description}]
        }).decode()}
        spans = available_spans(evidence, interpretation)
        items.append({'case_id': name, 'synthetic': True, 'source': record, 'interpretation': interpretation,
            'spans': spans, 'source_evidence': evidence,
            'expected_before_call': expected, 'prompt': prompt(record, interpretation, spans)})
    return items
