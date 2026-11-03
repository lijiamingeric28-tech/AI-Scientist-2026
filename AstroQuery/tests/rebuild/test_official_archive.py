"""Synthetic boundary tests; actual acquisition evidence is recorded separately."""
from pathlib import Path

import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.attachments import structured_table
from astroquery_ai.science.official_archive import archive_links


README = '''J/A+A/999/A1   SYNTHETIC fixture only
===============================================================================
Synthetic article
    =2026A&A...999A...1A        (SIMBAD/NED BibCode)
===============================================================================
ADC_Keywords: Test
File Summary:
ReadMe       80 . This file
values.dat   31 2 Synthetic values
See also:
 J/A+A/998/A1 : Another article (2026A&A...998A...1B)
Byte-by-byte Description of file: values.dat
-------------------------------------------------------------------------------
 Bytes Format Units Label Explanations
-------------------------------------------------------------------------------
  1- 5 A5     ---    Name  Full object name
  7-12 F6.3   km/s   Value Synthetic value
 14-19 F6.3   km/s e_Value Synthetic error
 21-25 F5.2   ---    Corr  Correlation coefficient
-------------------------------------------------------------------------------
'''


def test_archive_requires_own_catalog_and_primary_citation_not_references():
    raw = README.encode()
    links, _ = archive_links(raw, 'J/A+A/999/A1', [], ['2026A&A...999A...1A'])
    assert [item['url'].rsplit('/', 1)[-1] for item in links] == ['ReadMe', 'values.dat']
    assert links[1]['association']['parent_bibcodes'] == ['2026A&A...999A...1A']
    with pytest.raises(DomainError) as caught:
        archive_links(raw, 'J/A+A/999/A1', [], ['2026A&A...998A...1B'])
    assert caught.value.code == 'OFFICIAL_PARENT_UNVERIFIED'
    with pytest.raises(DomainError):
        archive_links(raw, 'J/A+A/998/A1', [], ['2026A&A...999A...1A'])


def test_original_fixed_width_literals_units_and_numeric_identity_survive(tmp_path):
    path = tmp_path / 'artifact'
    path.write_text(f"{'HD 1':5s} {0:6.3f} {0.01:6.3f} {0:5.2f}\n"
                    f"{'HD 2':5s} {-1.25:6.3f} {0.1:6.3f} {-0.25:5.2f}\n", encoding='utf-8')
    table = structured_table(path, 'mrt', 'attachment/table', readme_text=README,
        original_filename='values.dat')['resources'][0]['tables'][0]
    assert table['rows'][0] == {'Name': 'HD 1', 'Value': '0.000', 'e_Value': '0.010', 'Corr': '0.00'}
    assert table['columns'][1]['unit_text'] == 'km/s'
    assert table['columns'][1]['datatype'] == 'double'
    assert table['columns'][3]['unit_text'] is None


def test_numeric_placeholder_preserves_raw_instead_of_rejecting_whole_cds_table(tmp_path):
    path=tmp_path/'placeholder'
    path.write_text(f"{'HD 1':5s} {'---':>6s} {'0.010':>6s} {'0.00':>5s}\n",encoding='utf-8')
    table=structured_table(path,'mrt','attachment/table',readme_text=README,original_filename='values.dat')['resources'][0]['tables'][0]
    assert table['rows'][0]['Value']=='---' and table['rows'][0]['e_Value']=='0.010'
    assert table['columns'][1]['datatype']=='double' and table['columns'][1]['unit_text']=='km/s'


def test_fits_unit_token_does_not_disappear_when_astropy_renders_dimensionless(tmp_path):
    from astropy.io import fits
    column = fits.Column(name='Value', format='D', unit='1', array=[1.])
    path = tmp_path / 'unit.fits'
    fits.BinTableHDU.from_columns([column]).writeto(path)
    table = structured_table(path, 'fits', 'table')['resources'][0]['tables'][0]
    assert table['columns'][0]['unit_text'] == '1'


def test_local_attachment_passes_exact_readme_and_field_notes_to_shared_m03():
    import asyncio
    from tests.rebuild.scenario import application
    from astroquery_ai.science.workflow.attachment_service import LocalAttachmentCatalog
    from tempfile import TemporaryDirectory

    async def run(root):
        app = application(root)
        task = app.repository.create_task('SYNTHETIC local attachment', kind='validation')
        raw = app.artifacts.write(b'HD 1   0.000  0.010  0.00\n', 'text/plain')
        doc = app.artifacts.write(README.encode(), 'text/plain')
        with app.repository.transaction() as conn:
            app.artifacts.register(conn, task['task_id'], 'data', raw)
            app.artifacts.register(conn, task['task_id'], 'doc', doc)
        attachment = {'format': 'mrt', 'artifact': raw, 'attachment_id': 'test', 'original_filename': 'values.dat',
            'readme': {'artifact': doc, 'url': 'https://cdsarc.cds.unistra.fr/ftp/cats/J/A+A/999/A1/ReadMe'}}
        result, _, _ = await LocalAttachmentCatalog(app, task['task_id'], attachment).table_schema(task['task_id'], 'test/table')
        table = result['resources'][0]['tables'][0]
        assert table['catalog_document']['parsed']['fields']['Corr'][0]['unit_token'] == '---'
        assert table['catalog_document']['artifact_ref']['content_sha256'] == doc['sha256']
    with TemporaryDirectory() as root:
        asyncio.run(run(Path(root)))
