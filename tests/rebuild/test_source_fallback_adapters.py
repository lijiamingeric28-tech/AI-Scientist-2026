import asyncio
from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.simbad_protocols import sesame_view
from astroquery_ai.science.catalogs import VizierCatalogs
from tests.rebuild.scenario import application

XML=b'''<Sesame><Target option="~S"><name>HD 123</name>
<Resolver name="Sca=Simbad (CfA, via client/server)"><oid>123</oid><otype>*</otype>
<oname>HD 123</oname><alias>HD123</alias><jradeg>0</jradeg><jdedeg>0</jdedeg>
<errRAmas>0.2</errRAmas><pm><pmRA>1.2</pmRA></pm></Resolver></Target></Sesame>'''


def test_sesame_requires_actual_simbad_type_identity_and_aliases():
    v=sesame_view(XML,'HD 123')
    assert v['data'][0][:5]==['123','HD 123','*',0.0,0.0]
    for bad in [XML.replace(b'Sca=Simbad',b'N=NED'), XML.replace(b'<otype>*</otype>',b''),
                XML.replace(b'<oname>HD 123</oname>',b'<oname>HD 124</oname>').replace(b'HD123',b'HD124'),
                XML.replace(b'<oid>123</oid>',b'<oid>unknown</oid>'),
                XML.replace(b'<oid>',b'<INFO>from cache</INFO><oid>')]:
        with pytest.raises(DomainError):sesame_view(bad,'HD 123')
    # No coordinate-name parser or default stellar classification.
    with pytest.raises(DomainError):sesame_view(XML.replace(b'<otype>*</otype>',b''),'HD 123')


def test_synthetic_variable_designation_prefix_keeps_the_complete_name():
    # Synthetic XML protocol boundary, not another real query or a new alias.
    raw=XML.replace(b'<name>HD 123</name>',b'<name>RR Lyr</name>').replace(
        b'<oname>HD 123</oname>',b'<oname>V* RR Lyr</oname>').replace(b'<alias>HD123</alias>',b'')
    result=sesame_view(raw,'RR Lyr')
    assert result['data'][0][1]=='V* RR Lyr' and 'RR Lyr' in result['data'][0][-1].split('|')
    assert result['native_records'][0]['identifier_normalization']['source_identifier']=='V* RR Lyr'
    for different in [b'V* RS Lyr',b'V* RR Lyr B',b'RR Lyr B']:
        with pytest.raises(DomainError):sesame_view(raw.replace(b'V* RR Lyr',different),'RR Lyr')


def test_normal_identity_fallback_preserves_xml_and_auxiliary_uncertainties(tmp_path):
    async def run():
        app=application(tmp_path/'data')
        class HTTP:
            def __init__(self):self.urls=[]
            async def request(self,tid,owner,service,method,url,**kwargs):
                self.urls.append(url)
                if method=='POST':raise DomainError('SOURCE_HTTP_TIMEOUT','synthetic primary failure')
                return XML,{'retrieved_at':'2026-10-28T00:00:00Z','endpoint':url}
        from astroquery_ai.science.identity import SimbadIdentity
        h=HTTP();app.identity=SimbadIdentity(h,app.artifacts)
        result=await app.identity.resolve('SYNTHETIC task','HD 123')
        assert len(h.urls)==5 and result['targets'][0]['authority']=='SIMBAD'
        assert result['targets'][0]['classification_completeness']['adapter_version']=='simbad-sesame-1'
        a=result['astrometric_evidence'][0]
        assert a['raw_values']['coo_err_maj'] is None
        assert 'coo_err_maj' in a['fields_not_returned']
        assert a['adapter_native_values']['native_xml_fields']
        assert result['artifact']['media_type']=='application/xml'
        assert result['metadata']['prior_endpoint_failures']
    asyncio.run(run())


def test_vizier_successful_mirror_is_shared_per_task_without_changing_query_or_owner():
    async def run():
        class HTTP:
            def __init__(self):self.endpoint_preferences={};self.calls=[]
            async def request(self,tid,owner,service,method,url,**kwargs):
                self.calls.append((tid,owner,url,kwargs))
                if 'idia.ac.za' not in url:raise DomainError('SOURCE_HTTP_TIMEOUT','SYNTHETIC')
                return b'<VOTABLE/>',{'endpoint':url}
        h=HTTP();a=VizierCatalogs(h);args={'params':{'-source':'SYNTHETIC/table'},'max_bytes':2048}
        await a.request('SYNTHETIC task',**args)
        assert len(h.calls)==4  # Three once-per-task protocol probes, one real query.
        b=VizierCatalogs(h,owner='M05',service='publisher');await b.request('SYNTHETIC task',resource_scope='attachment',**args)
        assert len(h.calls)==5 and h.calls[-1][1]=='M05'
        assert 'idia.ac.za' in h.calls[-1][2] and h.calls[-1][3]['params']==args['params']
        assert h.calls[-1][3]['resource_scope']=='attachment'
        await VizierCatalogs(h).request('OTHER TASK',**args)
        assert len(h.calls)==9  # Another task probes its own actual service state.
    asyncio.run(run())
