from astroquery_ai.science.catalog_document import parse_readme, document_view
from astroquery_ai.science.unit_declarations import catalog_unit_declaration, execution_unit
from tests.rebuild.factories import ref


README = '''J/SYNTHETIC/1 Synthetic catalog
Byte-by-byte Description of file: main.dat
 1-5 A5 --- Name Source identifier
Byte-by-byte Description of file: spectrum.dat
 1-5 F5.2 --- Shape Native fit exponent (G1)
Note (G1): Synthetic fit definition. Its uncertainty level remains unknown.
'''


def test_html_readme_keeps_visible_text_and_explicit_decoded_coordinates():
    from html import escape
    html='<html><script>do not treat this as notes</script><pre>'+escape(README)+'</pre></html>'
    parsed=parse_readme(html,'J/SYNTHETIC/1/main')
    assert parsed['state']=='table_layout_identified'
    assert parsed['fields']['Name'][0]['text']==' 1-5 A5 --- Name Source identifier'
    assert parsed['text_view']['line_coordinate']=='decoded_pre_text'
    assert parse_readme(html,'J/OTHER/2/main')['state']=='catalog_identity_mismatch'
    assert parse_readme(html.replace('</pre>','</pre><pre>'+escape(README)+'</pre>'),'J/SYNTHETIC/1/main')['state']!='table_layout_identified'


def test_joined_view_requires_unique_exact_column_and_native_description():
    columns = [{'name': 'Name', 'description': 'Source identifier'}, {'name': 'Shape', 'description': 'Native fit exponent (G1)'}]
    parsed = parse_readme(README, 'J/SYNTHETIC/1/main', columns=columns)
    assert parsed['fields']['Shape'][0]['source_layout'] == 'spectrum.dat'
    view = document_view({'parsed': parsed}, ['Shape'], ['Name', 'Shape'])
    assert view['notes']['G1'][0]['text'].startswith('Note (G1):')
    changed = parse_readme(README, 'J/SYNTHETIC/1/main', columns=[{'name': 'Shape', 'description': 'A different physical exponent'}])
    assert 'Shape' not in changed['fields']
    ambiguous = parse_readme(README + '\nByte-by-byte Description of file: other.dat\n 1-5 F5.2 --- Shape Native fit exponent (G1)\n',
        'J/SYNTHETIC/1/main', columns=columns)
    assert 'Shape' not in ambiguous['fields']
    assert parse_readme(README, 'J/OTHER/2/main', columns=columns)['state'] == 'catalog_identity_mismatch'


def test_inline_source_unit_is_not_overwritten_by_readme_placeholder():
    parsed = parse_readme('SYNTHETIC\nByte-by-byte Description of file: values.dat\n 1-8 E8.3 --- Field Source magnetic field (in Gauss)\n', 'J/SYNTHETIC/values')
    source = {'metadata': {'table_id': 'J/SYNTHETIC/values', 'columns': [{'name': 'Field', 'unit_text': None, 'datatype': 'double'}],
        'catalog_document': {'parsed': parsed, 'artifact_ref': ref('SYNTHETIC-ReadMe')}}}
    declaration = catalog_unit_declaration(source, 'Field')
    assert declaration['source_literal'] == 'Gauss'
    assert declaration['kind'] == 'source_declared_unit'
    assert execution_unit({'unit': None, 'unit_declaration': declaration}) == 'Gauss'
    parsed['fields']['Field'][0].update(text=' 1-8 E8.3 --- Field Physical flux (19)')
    # A model interpretation of an actual source footnote remains physical;
    # the --- format slot cannot replace it with a dimensionless unit.
    assert catalog_unit_declaration(source, 'Field', proposed_unit='erg.cm-2.s-1') is None
