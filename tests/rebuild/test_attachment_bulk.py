from astroquery_ai.science.attachments import structured_table
from astroquery_ai.science.official_archive import metadata_export_links


def test_actual_catalogue_prefix_wording_selects_native_keys_without_inventing_identity():
    from astroquery_ai.science.catalog.identifiers import declared_namespace,identifier_selectors
    field={'name':'SN','datatype':'char','description':'Supernova designation','ucd':'meta.id;meta.main'}
    assert declared_namespace(field,None)=='SN'
    assert '2011fe' in identifier_selectors('SN 2011fe','SN',field)
    assert declared_namespace({**field,'description':'Signal to noise ratio'},None) is None
    assert declared_namespace({'name':'HD','datatype':'int','description':'HD (Cat. <III/135>) number','ucd':'meta.id;meta.main'},None)=='HD'


def test_deposit_retries_transient_disconnect_but_does_not_rotate_on_rate_refusal():
    import asyncio
    import pytest
    from astroquery_ai.science.official_repositories import repository_request
    from astroquery_ai.runtime.errors import DomainError
    async def run():
        calls=[]
        async def fetch(url,**kw):
            calls.append(url)
            if len(calls)==1:raise DomainError('SOURCE_TRANSPORT_ERROR','injected interrupted transfer')
            return b'original bytes',{'endpoint':url}
        raw,meta=await repository_request(fetch,'https://zenodo.org/api/records/1')
        assert raw==b'original bytes' and len(calls)==2 and meta['repository_request_count']==2
        assert calls[0]==calls[1]
        async def limited(url,**kw):
            calls.append(url);raise DomainError('SOURCE_HTTP_ERROR','injected rate refusal',provider_status=429)
        with pytest.raises(DomainError):await repository_request(limited,'https://zenodo.org/api/records/1')
        assert len(calls)==3
    asyncio.run(run())


def test_bulk_batches_bound_measurement_outputs_not_just_row_count():
    from astroquery_ai.science.catalog.rows import bounded_row_batches
    rows=list(range(1032));fields=[{'value_column':f'band{i}'} for i in range(9)]
    batches=list(bounded_row_batches(rows,[{'id_column':None,'properties':fields}]))
    actual=[(r,p['value_column']) for group,plan in batches for r in group for p in plan['properties']]
    assert len(actual)==len(set(actual))==1032*9
    assert set(actual)=={(r,f['value_column']) for r in rows for f in fields}
    assert all(len(group)*len(plan['properties'])<=4 for group,plan in batches)


def test_normal_archive_discovery_requests_full_table_headers_before_export(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4
    from astroquery_ai.runtime.application import Application
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.science.catalogs import VizierCatalogs
    from astroquery_ai.science.workflow.attachment_service import AttachmentService
    async def run():
        app=Application(tmp_path);task=app.create('SYNTHETIC archive discovery',str(uuid4()));job=app.repository.claim_job('test')
        async def schema(self,tid,**kw):
            # VizieR -meta by itself returns only RESOURCE, no actual tables.
            full=kw['params'].get('-meta.all')=='1'
            table='<TABLE name="J/Test/1/table1"><FIELD name="v" datatype="double"/></TABLE>' if full else ''
            raw=('<VOTABLE><RESOURCE name="J/Test/1"><INFO name="cites" value="bibcode:2026ApJ...999...12A"/>'+table+'</RESOURCE></VOTABLE>').encode()
            return raw,{}
        class NoNativeReadme:
            async def request(self,*a,**kw):raise DomainError('SOURCE_TRANSPORT_ERROR','Synthetic native ReadMe outage')
        monkeypatch.setattr(VizierCatalogs,'request',schema)
        context=SimpleNamespace(app=app,repo=app.repository,steps=SimpleNamespace(http=lambda j:NoNativeReadme()),extractor=None)
        service=AttachmentService(context)
        found,gaps=await service.archive_candidates(job,{'work_id':'work-test','records':[{'bibcode':'2026ApJ...999...12A'}]})
        assert len(found)==1 and found[0]['association']['source_table_id']=='J/Test/1/table1'
        assert '-meta.all' not in found[0]['vizier_export']
        assert gaps[0]['fallback']=='official_vizier_export'
    asyncio.run(run())


def test_paging_preserves_raw_rows_and_does_not_stop_at_one_thousand(tmp_path):
    path = tmp_path/'rows.csv'
    path.write_text('Name,Value\n'+''.join(f'{"TARGET" if i%2 else "OTHER"},{i}.000\n' for i in range(2400)))
    first = structured_table(path,'csv','t',id_column='Name',aliases=['TARGET'])
    assert first['next_row_offset'] == 1000 and first['matched_rows'] == 1200
    second = structured_table(path,'csv','t',id_column='Name',aliases=['TARGET'],row_offset=1000)
    assert not second['overflow'] and second['next_row_offset'] is None
    t1=first['resources'][0]['tables'][0];t2=second['resources'][0]['tables'][0]
    assert len(t1['rows']) == 1000 and len(t2['rows']) == 200
    assert t2['source_row_numbers'][0] == 2001 and t2['rows'][0]['Value'] == '2001.000'
    assert t2['source_row_numbers'][-1] == 2399


def test_official_export_needs_resource_origin_not_incidental_bibcode():
    bib='2026ApJ...999...12A'
    raw=f'''<VOTABLE><RESOURCE name="J/ApJ/999/12"><INFO name="cites" value="bibcode:{bib}"/>
      <INFO name="citation" value="doi:10.26093/cds/vizier.19990012"/>
      <TABLE name="J/ApJ/999/12/table1"><FIELD name="v" datatype="double"/></TABLE></RESOURCE></VOTABLE>'''.encode()
    links=metadata_export_links(raw,[bib],artifact_ref='synthetic-artifact')
    assert len(links)==1 and links[0]['association']['native_file_claimed'] is False
    assert links[0]['vizier_export']['-out.max']=='100000'
    assert not any(k.startswith('-meta') for k in links[0]['vizier_export'])
    assert metadata_export_links(raw,[bib.replace('12A','12B')],artifact_ref='x')==[]
    # A generic reference/link or a global INFO must never grant parent identity.
    assert metadata_export_links(raw.replace(b'name="cites"',b'name="reference"'),[bib],artifact_ref='x')==[]
    outer=f'<VOTABLE><INFO name="cites" value="bibcode:{bib}"/><RESOURCE name="J/ApJ/999/12"><TABLE name="J/ApJ/999/12/table1"/></RESOURCE></VOTABLE>'.encode()
    assert metadata_export_links(outer,[bib],artifact_ref='x')==[]


def test_single_object_scope_requires_real_quote_and_resolved_name():
    from astroquery_ai.science.catalog.table_subject import check_scope
    target={'main_id':'SN 2026test','aliases':['SN 2026test'],'submitted_mentions':['SN2026test']}
    evidence={'description':'Photometric observations of SN2026test in six bands.'}
    response={'scope':'single_target_observations','evidence_id':'description',
      'quote':evidence['description'],'source_name':'SN2026test','reason':'The table declares this target.'}
    assert check_scope(response,evidence,target)
    assert check_scope({**response,'source_name':'SN2026other'},evidence,target) is None
    assert check_scope({**response,'quote':'Invented target observations'},evidence,target) is None
    assert check_scope({**response,'scope':'mixed'},evidence,target) is None
    assert check_scope({**response,'scope':'model_template'},evidence,target) is None


def test_missing_votable_endpoint_does_not_cancel_healthy_official_mirror():
    import asyncio
    from astroquery_ai.runtime.service_routes import ServiceRoutes
    from astroquery_ai.runtime.errors import DomainError
    class HTTP:
        repository=None
        async def request(self,tid,owner,service,method,endpoint,**kwargs):
            if endpoint=='https://missing.example/votable':
                raise DomainError('SOURCE_HTTP_ERROR','Missing protocol route',provider_status=404)
            return b'<VOTABLE/>',{'endpoint':endpoint,'status':200}
    async def run():
        routes=ServiceRoutes(HTTP())
        endpoints=('https://missing.example/votable','https://working.example/votable')
        await routes.probe('t','M05','publisher','votable_metadata',endpoints,{'-out.max':'0'})
        raw,meta=await routes.request('t','M05','publisher','votable_metadata',endpoints,'GET')
        assert raw==b'<VOTABLE/>' and meta['endpoint']==endpoints[1]
        state=routes.state('t','publisher','votable_metadata')
        assert len(state['probe_failures'])==1 and state['probe_failures'][0]['endpoint']==endpoints[0]
    asyncio.run(run())


def test_explicit_fits_hdu_keeps_observations_separate_from_fit(tmp_path):
    import numpy as np
    from astropy.io import fits
    from astroquery_ai.science.archives import fits_manifest
    primary=fits.PrimaryHDU();primary.header['NAME']='SYNTHETIC target'
    observed=fits.BinTableHDU.from_columns([
      fits.Column(name='RV',format='D',unit='km/s',array=np.array([1.2,3.4])),
      fits.Column(name='BJD',format='D',unit='d',array=np.array([2450000.5,2450001.5]))],name='DATA')
    fitted=fits.BinTableHDU.from_columns([fits.Column(name='COEFF',format='D',array=np.array([99.0]))],name='FIT')
    path=tmp_path/'multi.fits';fits.HDUList([primary,observed,fitted]).writeto(path)
    manifest=fits_manifest(path.read_bytes())
    assert [(t['hdu'],t['rows']) for t in manifest['tables']]==[(1,2),(2,1)]
    parsed=structured_table(path,'fits','selected/data',hdu=1)
    t=parsed['resources'][0]['tables'][0]
    assert len(t['rows'])==2 and t['rows'][0]['RV']=='1.2'
    assert t['file_subject_context']['hdu']==1 and t['columns'][0]['unit_text']=='km/s'
    import asyncio
    from astroquery_ai.runtime.parsing import Parsers
    assert asyncio.run(Parsers().run('fits_manifest', path)) == manifest


def test_pdf_archive_member_keeps_its_parent_and_does_not_enter_table_parser(tmp_path):
    import zipfile
    import pymupdf
    from astroquery_ai.science.archives import structured_archive
    with pymupdf.open() as document:
        document.new_page(width=200, height=200)
        original = document.tobytes()
    path = tmp_path / 'supplement.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('files/table.pdf', original)
        archive.writestr('invalid.pdf', b'not a PDF')
    parsed = structured_archive(path, original_filename=path.name)
    assert [(m['path'], m['format']) for m in parsed['members']] == [('files/table.pdf', 'pdf')]
    assert parsed['gaps'] == [{'path': 'invalid.pdf', 'reason': 'invalid_pdf_member'}]


def test_author_deposit_needs_bidirectional_publication_association():
    from astroquery_ai.science.official_repositories import paper_zenodo_links,zenodo_files
    loc=paper_zenodo_links({'pages':[{'page':1,'text':'Data at https://zenodo.org/records/12345 are published with this work.'}]})[0]
    document={'id':12345,'metadata':{'related_identifiers':[{'scheme':'doi','identifier':'10.1234/synthetic','relation':'isSupplementTo'}]},
      'files':[{'key':'tables.zip','checksum':'md5:00','links':{'self':'https://zenodo.org/api/records/12345/files/tables.zip/content'}}]}
    links=zenodo_files(document,['10.1234/synthetic'],loc,metadata_artifact='synthetic')
    assert len(links)==1 and links[0]['filename']=='tables.zip' and links[0]['format']=='container'
    assert zenodo_files(document,['10.1234/different'],loc,metadata_artifact='synthetic')==[]
    document['metadata']['related_identifiers'][0]['relation']='cites'
    assert zenodo_files(document,['10.1234/synthetic'],loc,metadata_artifact='synthetic')==[]


def test_isolated_parser_preserves_paging_options(tmp_path,monkeypatch):
    import asyncio
    from astroquery_ai.runtime.parsing import Parsers
    monkeypatch.delenv('PYTHONPATH',raising=False)
    p=tmp_path/'pages.csv';p.write_text('Name,Value\n'+''.join(f'TARGET,{i}\n' for i in range(1003)))
    async def run():
        result=await Parsers().run('structured_table',p,format='csv',table_id='synthetic/table',row_offset=1000)
        table=result['resources'][0]['tables'][0]
        assert table['source_row_numbers']==[1000,1001,1002]
        assert not result['overflow']
    asyncio.run(run())


def test_no_name_column_keeps_valid_value_mapping_but_grants_no_identity():
    from astroquery_ai.science.catalog_plan import validate_plan
    from astroquery_ai.science.catalog_context import quarantine_unseen
    raw={'id_column':None,'identity_namespace':None,'limitations':['No object name column'],
      'properties':[{'property_id':'P1','value_column':None,'error_columns':[],
         'source_unit':None,'source_representation':None},
        {'property_id':'P2','value_column':'RV','error_columns':['e_RV'],
         'source_unit':'km/s','source_representation':'linear'}]}
    plan,gaps=validate_plan(raw,{'RV','e_RV'},{'P1','P2'})
    assert [p['property_id'] for p in plan['properties']]==['P2'] and gaps
    retained,unseen=quarantine_unseen(plan,{'RV','e_RV'})
    assert retained['id_column'] is None and len(retained['properties'])==1 and not unseen


def test_partial_metadata_can_supply_hints_but_never_measurement_rows():
    import pytest
    from astroquery_ai.science.catalogs import parse_votable
    from astroquery_ai.runtime.errors import DomainError
    raw=b'<VOTABLE><INFO name="Error" value="metadata database warning"/><RESOURCE name="J/TEST/1"><DESCRIPTION>Synthetic metadata hint</DESCRIPTION><TABLE name="J/TEST/1/t"><FIELD name="v" datatype="double"/></TABLE></RESOURCE></VOTABLE>'
    with pytest.raises(DomainError):parse_votable(raw)
    hints=parse_votable(raw,allow_partial_metadata=True)
    assert hints['metadata_hints_only'] and hints['overflow'] and hints['metadata_service_warnings']
    with_values=raw.replace(b'</TABLE>',b'<DATA><TABLEDATA><TR><TD>99</TD></TR></TABLEDATA></DATA></TABLE>')
    with pytest.raises(DomainError):parse_votable(with_values,allow_partial_metadata=True)


def test_declared_identifier_prefix_and_navigation_do_not_invent_aliases():
    from astroquery_ai.science.catalog.identifiers import declared_namespace,identifier_selectors,exact_rows
    sn={'name':'SN','description':'Supernova SN name','datatype':'char','ucd':'meta.id;meta.main'}
    assert declared_namespace(sn,None)=='SN'
    assert identifier_selectors('SN 2026xyz','SN',sn)==['2026xyz']
    assert exact_rows([{'SN':'2026xyz'}],['SN'],['SN 2026xyz'],{'SN':'SN'})==[0]
    sao={'name':'SAO','description':'SAO number','datatype':'int','ucd':'meta.id;meta.main'}
    assert declared_namespace(sao,None)=='SAO'
    name={'name':'Name','description':'Star name','datatype':'char','ucd':'meta.id;meta.main'}
    assert declared_namespace(name,None) is None
    assert identifier_selectors('* bet Dor',None,name)==['bet Dor','* bet Dor']
    # Retrieval navigation does not alter the verified names used for admission.
    assert exact_rows([{'Name':'bet Dor'}],['Name'],['* bet Dor'])==[]


def test_table_declaration_options_bind_source_text_not_author_labels():
    from astroquery_ai.science.catalog.table_subject import declaration_choices,check_scope
    target={'main_id':'SN 2026xyz','aliases':[]}
    evidence={'description':'SN2026xyz photometry (Example et al. 2026)'}
    options=declaration_choices(evidence,target)
    assert len(options)==1
    resolved={**next(iter(options.values())),'scope':'single_target_observations'}
    assert resolved['source_name']=='SN2026xyz' and check_scope(resolved,evidence,target)
