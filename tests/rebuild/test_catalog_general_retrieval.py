"""General catalogue navigation and source-bound row regressions."""
import asyncio
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.science.catalogs import VizierCatalogs, parse_votable
from astroquery_ai.science.catalog import selection
from astroquery_ai.science.catalog.table_subject import scope_prompt, extract_table_subject


def votable(*tables, overflow=False):
    return ('<VOTABLE><RESOURCE name="synthetic/catalog"><DESCRIPTION>Photometric measurements</DESCRIPTION>'
        + ''.join('<TABLE name="synthetic/catalog/'+name+'"><DESCRIPTION>Photometry of Target X</DESCRIPTION>'
          '<FIELD name="mag" datatype="double" unit="mag" ucd="phot.mag"><DESCRIPTION>Observed magnitude</DESCRIPTION></FIELD>'
          '<DATA><TABLEDATA><TR><TD>12.1</TD></TR><TR><TD>12.2</TD></TR></TABLEDATA></DATA></TABLE>' for name in tables)
        + ('<INFO name="QUERY_STATUS" value="OVERFLOW"/>' if overflow else '')+'</RESOURCE></VOTABLE>').encode()


def running(tmp_path):
    repo=Repository(tmp_path/'runtime.sqlite3')
    tid=repo.create_task('SYNTHETIC general catalogue')['task_id']
    spec={'dependencies':[], 'registry_release':{'id':'synthetic'},
          'target':{'target_id':'target','main_id':'Target X','aliases':['Target X']},
          'properties':[{'property_id':'p'}],
          'run_policy':{'catalog':{'maximum_tables':20,'wave_tables':8,'maximum_catalog_expansions':12,
                                  'maximum_feedback_queries':0}}}
    spec['spec_hash']=digest(spec)
    with repo.transaction() as conn:
        q=repo.put_object(conn,tid,'confirmed_query',tid,1,spec)
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open',query_ref=canonical(q).decode())
        for name in ('catalog_discovery','catalog_hints'):
            repo.producer(conn,tid,name)
        repo.enqueue(conn,tid,'M03','catalog_discover',{})
    return repo,tid,repo.claim_job('test',lease_seconds=600),spec


def test_empty_keyword_search_is_success_but_missing_concrete_table_is_error():
    raw=b'<VOTABLE><INFO name="Error" value="Table or Catalog not found: words"/></VOTABLE>'
    parsed=parse_votable(raw,allow_partial_metadata=True)
    assert parsed['resources']==[] and parsed['search_no_matches'] and not parsed['overflow']
    with pytest.raises(DomainError,match='目录表'):
        parse_votable(raw)
    other=b'<VOTABLE><INFO name="QUERY_STATUS" value="ERROR">backend unavailable</INFO></VOTABLE>'
    with pytest.raises(DomainError):
        parse_votable(other,allow_partial_metadata=True)


def test_truncated_keyword_search_expands_and_preserves_both_responses():
    calls=[]
    class Catalog(VizierCatalogs):
        async def request(self,tid,**kwargs):
            cap=int(kwargs['params']['-meta.max']);calls.append(cap)
            return votable('first',overflow=cap==1),{}
    results=asyncio.run(Catalog(None).discover('task',{},[],[],expressions=['photometry'],caps=(1,3),expand_catalogs=False))
    assert calls==[1,3]
    assert results[0]['coverage_state']=='truncated_or_unknown'
    assert results[1]['coverage_state']=='complete_for_expression'


def test_exact_rows_expand_without_changing_identity_filter():
    requests=[]
    class Catalog(VizierCatalogs):
        async def request(self,tid,**kwargs):
            requests.append(kwargs['params'])
            return votable('first',overflow=len(requests)==1),{}
    parsed,_,metadata=asyncio.run(Catalog(None).exact_query('t','synthetic/catalog/first','Object','Target X'))
    assert [r['-out.max'] for r in requests]==['1000','10000']
    assert all(r['Object']=='==Target X' for r in requests)
    assert not parsed['overflow'] and metadata['row_query_complete']


def test_final_row_limit_remains_explicitly_incomplete():
    class Catalog(VizierCatalogs):
        async def request(self,*args,**kwargs):return votable('first',overflow=True),{}
    parsed,_,metadata=asyncio.run(Catalog(None).selected_rows('t','synthetic/catalog/first'))
    assert parsed['overflow'] and not metadata['row_query_complete']
    assert len(metadata['row_query_limits'])==3


def test_existing_child_does_not_hide_other_catalogue_tables(tmp_path,monkeypatch):
    repo,tid,job,spec=running(tmp_path)
    requested=[]
    initial={'expression':'photometry','cap':100,'coverage_state':'complete_for_expression',
             'parsed':parse_votable(votable('first')),'artifact':{'artifact_id':'initial'}}
    class Catalog:
        def __init__(self,*args,**kwargs):pass
        async def discover(self,*args,**kwargs):return [initial]
        async def request(self,*args,**kwargs):
            requested.append(kwargs['params']['-source'])
            return votable('first','second'),{}
    async def rank(service,job,spec,nodes,**kwargs):
        return [{**n,'property_ids':['p'],'priority':2,'evidence_quote':'Photometric measurements'} for n in nodes],[n['node_id'] for n in nodes]
    async def model(*args,**kwargs):return {'queries':['photometry']},{}
    async def commit(result):result['artifact']={'artifact_id':'expanded'}
    monkeypatch.setattr(selection,'VizierCatalogs',Catalog)
    monkeypatch.setattr(selection,'rank',rank)
    monkeypatch.setattr(selection,'planning_messages',lambda *args:[{'role':'user','content':'fixture'}])
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(_profile_state=lambda owner:'validated'),
                            steps=SimpleNamespace(model=model,http=lambda job:None))
    asyncio.run(selection.bounded_discovery(service,job,spec,[],[],commit))
    assert requested==['synthetic/catalog']
    with repo.read() as conn:
        pool=repo.objects(conn,tid,'catalog_pool')[0]
    assert set(pool['discovered_tables'])=={'synthetic/catalog/first','synthetic/catalog/second'}
    assert len(pool['dispatched'])==2


@pytest.mark.parametrize('scope,accepted',[('single_target_observations',True),('mixed',False),('unknown',False),('model_template',False)])
def test_dynamic_single_object_table_requires_declaration_and_reopens_rows(tmp_path,scope,accepted):
    repo,tid,job,spec=running(tmp_path)
    raw=votable('first');parsed=parse_votable(raw);table=parsed['resources'][0]['tables'][0]
    store=ArtifactStore(tmp_path/'artifacts',repo)
    calls=[];collected=[]
    class Catalog:
        async def selected_rows(self,*args):calls.append(args);return parsed,raw,{'row_query_complete':True}
    async def model(*args,**kwargs):
        return {'scope':scope,'declaration_id':'D1' if accepted else None,'reason':'source table scope'},{'attempt_id':'verified'}
    async def collect(**kwargs):collected.append(kwargs)
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(artifacts=store),steps=SimpleNamespace(model=model),
        model_profile=lambda *args,**kwargs:None,extract_verified_rows=collect,
        execution_plans=lambda plan:[plan])
    plan={'id_column':None,'identity_namespace':None,'properties':[{'property_id':'p','value_column':'mag',
          'error_columns':[],'source_unit':'mag','source_representation':'magnitude'}],'limitations':[]}
    asyncio.run(extract_table_subject(service,job,spec,table,plan,Catalog(),None,{'source_id':'source'},{}))
    assert bool(calls)==bool(collected)==accepted
    with repo.read() as conn:
        check=repo.objects(conn,tid,'catalog_subject_check')[0]
        coverage=repo.objects(conn,tid,'coverage')[0]
    assert check['accepted']==accepted
    assert coverage['verified_row_count']==(2 if accepted else 0)
    if accepted:
        _,path=store.read_owned(tid,collected[0]['artifact']['artifact_id'])
        assert path.read_bytes()==raw and collected[0]['input_format']=='votable'


def test_feedback_is_finite_deduplicated_and_never_accepts_model_urls():
    assert selection.checked_queries({'queries':[' photometry ','PHOTOMETRY','colour']},3,['colour'])==['photometry']
    with pytest.raises(DomainError):selection.checked_queries({'queries':['https://invented/catalog']})
    assert selection.checked_queries({'queries':['a','b','c']},2)==['a','b']


def test_metadata_for_other_target_does_not_create_a_single_object_choice():
    target={'main_id':'Target X','aliases':[]}
    prompt,evidence,choices=scope_prompt(target,{'columns':[], 'description':'Photometry of Target Y'},None)
    assert not choices
    assert prompt['verified_target_aliases']==['Target X']


def test_single_table_name_marker_preserves_verified_target_not_nearby_name():
    from astroquery_ai.science.catalog.table_subject import check_scope
    target={'main_id':'Cl Synthetic 12','aliases':['NAME Named Cluster']}
    _,evidence,choices=scope_prompt(target,{'columns':[],'description':'Observations of Named Cluster'},None)
    choice=next(iter(choices.values()))
    assert check_scope({'scope':'single_target_observations',**choice},evidence,target)
    assert not check_scope({'scope':'single_target_observations',**choice},evidence,{'main_id':'Cl Synthetic 13','aliases':[]})


def test_wide_screening_preserves_every_column_without_repeating_full_index(monkeypatch):
    from astroquery_ai.runtime.calls import json_input_capacity
    columns=[{'name':f'value_{i}','description':'Measured quantity '+('long field context '*12),'unit_text':'m'} for i in range(750)]
    node={'node_id':'synthetic/wide','description':'Measurements','columns':columns}
    monkeypatch.setattr(selection,'ranking_messages',lambda spec,nodes:[{'role':'user','content':canonical({'json':nodes}).decode()}])
    batches=list(selection.screening_batches([node],spec={}))
    assert len(batches)>1
    assert [c['name'] for batch in batches for item in batch for c in item['columns']]==[c['name'] for c in columns]
    assert all('column_index' not in item for batch in batches for item in batch)
    assert all(json_input_capacity(selection.ranking_messages({},batch),selection.selection_profile())['fits'] for batch in batches)


def test_screening_retry_uses_content_identity_when_batch_members_change(tmp_path,monkeypatch):
    repo,tid,job,spec=running(tmp_path);calls=[]
    monkeypatch.setattr(selection,'ranking_messages',lambda spec,nodes:[{'role':'user','content':canonical({'json':nodes}).decode()}])
    async def model(*args,**kwargs):
        calls.append(kwargs['root_id'])
        return {'candidates':[],'excluded':[]},{'attempt_id':'fixture-'+str(len(calls))}
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(_profile_state=lambda owner:'validated'),steps=SimpleNamespace(model=model))
    first={'node_id':'synthetic/first','description':'Saved metadata','columns':[]}
    second={'node_id':'synthetic/second','description':'Later acquired metadata','columns':[]}
    async def exercise():
        await selection.rank(service,job,spec,[first],root='resources')
        await selection.rank(service,job,spec,[first,second],root='resources')
        await selection.rank(service,job,spec,[first],root='resources')
    asyncio.run(exercise())
    assert len(calls)==2 and len(set(calls))==2
    with repo.read() as c:assert len(repo.objects(c,tid,'catalog_screening'))==2


@pytest.mark.parametrize('old_error_cached',[False,True])
def test_http_200_protocol_error_is_not_reused_as_success(tmp_path,old_error_cached):
    from astroquery_ai.runtime.checkpoints import JobSteps
    repo,tid,job,spec=running(tmp_path)
    requests=[]
    class HTTP:
        async def request(self,*args,**kwargs):
            requests.append(args)
            return (b'database unavailable' if len(requests)==1 else votable('first')), {'status':200,'attempt_id':str(len(requests))}
    app=SimpleNamespace(repository=repo,artifacts=ArtifactStore(tmp_path/'originals',repo),http=HTTP())
    client=JobSteps(app).http(job)
    def validate(raw):
        if not raw.startswith(b'<VOTABLE'):
            raise DomainError('SOURCE_PROTOCOL_UNAVAILABLE','injected HTTP 200 error page')
    async def exercise():
        args=(tid,'M03','vizier','GET','https://example.test/votable')
        if old_error_cached:
            raw,_=await client.request(*args)
            assert raw==b'database unavailable'
        else:
            with pytest.raises(DomainError):await client.request(*args,_validate_response=validate)
        raw,_=await client.request(*args,_validate_response=validate)
        again,_=await client.request(*args,_validate_response=validate)
        assert raw==again==votable('first')
    asyncio.run(exercise())
    assert len(requests)==2
    with repo.read() as c:
        cache=repo.objects(c,tid,'http_response_cache')[0]
        _,path=app.artifacts.read_owned(tid,cache['artifact']['artifact_id'])
        assert path.read_bytes()==votable('first')


def test_header_schema_explicitly_requests_verified_alias_selection(monkeypatch):
    from astroquery_ai.science.catalog import planning
    monkeypatch.setattr(planning,'header_property_view',lambda binding:{'property_id':binding['property_id']})
    target={'target_id':'x','main_id':'Cl Synthetic 12','aliases':['Cl Synthetic 12','NAME Named Cluster','M 12'],'primary_otype':'OCl'}
    table=parse_votable(votable('first'))['resources'][0]['tables'][0]
    prompt=planning.header_prompt(table,{'target':target,'properties':[{'property_id':'p'}]})
    schema=prompt['response_schema']
    assert 'identity_alias_ids' in schema['required']
    assert schema['properties']['identity_alias_ids']['items']['enum']==['A1','A2','A3']
    plan,_,_=planning.validate_column_plan({'id_column':'mag','identity_namespace':None,
        'identity_alias_ids':['A2','A3'],'properties':[],'limitations':[]},{'mag'},{'p'},None)
    assert plan['identity_alias_ids']==['A2','A3']


def test_name_markers_and_short_number_navigation_do_not_grant_identity():
    from astroquery_ai.science.catalog.identifiers import identifier_selectors,navigation_patterns,exact_rows
    field={'name':'Name','datatype':'char'}
    assert identifier_selectors('NAME Named Cluster',None,field)[0]=='Named Cluster'
    assert identifier_selectors('Cl Synthetic 12',None,field)[0]=='Synthetic 12'
    assert '*M*12*' in navigation_patterns(['M 12'])
    assert '*Named*Cluster*' in navigation_patterns(['NAME Named Cluster'])
    assert exact_rows([{'Name':'Named Cluster'}],['Name'],['NAME Named Cluster'])==[]


def test_node_failing_keyword_probe_cannot_supply_false_empty_fallback():
    from astroquery_ai.runtime.service_routes import ServiceRoutes
    calls=[];tries=0
    class HTTP:
        async def request(self,tid,owner,service,method,url,**kwargs):
            nonlocal tries
            probe=kwargs['params']['-words']=='known'
            calls.append((url,probe))
            if url.endswith('broken'):
                return b'<VOTABLE><RESOURCE/></VOTABLE>',{}
            if not probe:
                tries+=1
                if tries==1:raise DomainError('SOURCE_PROTOCOL_UNAVAILABLE','transient database outage')
            return votable('first'),{}
    async def exercise():
        routes=ServiceRoutes(HTTP())
        endpoints=['https://example.test/good','https://example.test/broken']
        await routes.probe('t','M03','vizier','votable_search',endpoints,{'-words':'known'})
        raw,_=await routes.request('t','M03','vizier','votable_search',endpoints,'GET',params={'-words':'target'})
        assert raw==votable('first')
    asyncio.run(exercise())
    assert ('https://example.test/broken',False) not in calls
    assert tries==2


@pytest.mark.parametrize('always_fails',[False,True])
def test_screen_timeout_is_bounded_and_does_not_erase_other_batches(tmp_path,monkeypatch,always_fails):
    repo,tid,job,spec=running(tmp_path);calls=[]
    first={'node_id':'first','description':'First source','columns':[]}
    second={'node_id':'second','description':'Second source','columns':[]}
    monkeypatch.setattr(selection,'screening_batches',lambda nodes,**kw:iter([[first],[second]]))
    monkeypatch.setattr(selection,'ranking_messages',lambda spec,nodes:[{'role':'user','content':canonical({'json':nodes}).decode()}])
    async def model(*args,**kwargs):
        calls.append(kwargs['root_id'])
        if len(calls)==1 or always_fails and len(calls)==2:raise TimeoutError('synthetic timeout')
        return {'candidates':[]},{'attempt_id':'test'}
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(_profile_state=lambda owner:'validated'),steps=SimpleNamespace(model=model))
    _,checked=asyncio.run(selection.rank(service,job,spec,[first,second],root='resources'))
    assert len(calls)==3 and calls[0]==calls[1]
    assert checked==(['second'] if always_fails else ['first','second'])
    with repo.read() as c:assert len(repo.objects(c,tid,'catalog_screening_failure'))==int(always_fails)


def test_reference_labels_and_schema_enums_agree_without_changing_science_text():
    from astroquery_ai.science.model_bindings import map_fields
    native={'property_id':'native-property','description':'native-property is literal scientific text',
            'response_schema':{'properties':{'property_id':{'type':'string','enum':['native-property']},
                'property_ids':{'type':'array','items':{'type':'string','enum':['native-property']}}}}}
    mappings={'property_id':{'P1':'native-property'},'property_ids':{'P1':'native-property'}}
    wire=map_fields(native,mappings)
    assert wire['property_id']=='P1'
    assert wire['response_schema']['properties']['property_id']['enum']==['P1']
    assert wire['response_schema']['properties']['property_ids']['items']['enum']==['P1']
    assert wire['description']==native['description']
    assert map_fields(wire,mappings,expand=True)==native


def test_empty_property_recommendation_is_exclusion_and_does_not_request_repair(tmp_path,monkeypatch):
    repo,tid,job,spec=running(tmp_path);calls=[]
    monkeypatch.setattr(selection,'ranking_messages',lambda spec,nodes:[{'role':'user','content':canonical({'json':nodes}).decode()}])
    node={'node_id':'first','description':'A source without a requested quantity','columns':[]}
    async def model(*args,**kwargs):
        calls.append(kwargs['root_id'])
        return {'candidates':[{'node_id':'T1','property_ids':[],
                              'priority':1,'evidence_ids':['D']}]},{'attempt_id':'test'}
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(_profile_state=lambda owner:'validated'),steps=SimpleNamespace(model=model))
    selected,checked=asyncio.run(selection.rank(service,job,spec,[node],root='resources'))
    assert not selected and checked==['first'] and len(calls)==1
    with repo.read() as c:
        receipt=repo.objects(c,tid,'catalog_screening')[0]
        assert not receipt['item_failures']
        assert receipt['response']['excluded'][0]['reason']=='no_selected_property'
    # Unknown nodes and malformed property fields still require validation.
    malformed={'candidates':[{'node_id':'unknown','property_ids':[]},
                             {'node_id':'first','property_ids':'P1'}]}
    assert selection.normalize_screening(malformed,[node])['candidates']==malformed['candidates']


def test_time_bounded_screening_interleaves_actual_queries_without_catalogue_seeds():
    def response(expression,ids):
        return {'expression':expression,'parsed':{'resources':[{'resource_id':i} for i in ids]}}
    rows=[response('first',['a1','a2']),response('first',['a1','a2','a3']),
          response('second',['b1','a2','b2'])]
    assert selection.interleaved_resource_ids(rows)==['a1','b1','a2','a3','b2']


@pytest.mark.parametrize('dynamic',[False,True])
def test_deadline_does_not_switch_dynamic_discovery_to_legacy_transport(tmp_path,monkeypatch,dynamic):
    from astroquery_ai.runtime.run_policy import current_job,save_window
    from astroquery_ai.runtime.service_routes import ServiceRoutes
    repo,tid,job,_=running(tmp_path);visits=[]
    policy={'end_seconds':1200,'stop_dispatch_seconds':1140}
    if dynamic:policy['discovery_protocol']='dynamic-metadata/2'
    with repo.transaction() as conn:
        save_window(repo,conn,tid,{'policy':policy,'started_at':0,'paused_seconds':0,
                                'paused_at':None,'closed':False})
    async def probe(*args,**kwargs):visits.append('capability_probe')
    async def request(*args,**kwargs):visits.append('qualified_mirrors');return votable('t'),{}
    async def legacy(*args,**kwargs):visits.append('legacy');return votable('t'),{}
    monkeypatch.setattr(ServiceRoutes,'probe',probe)
    monkeypatch.setattr(ServiceRoutes,'request',request)
    monkeypatch.setattr(VizierCatalogs,'legacy_request',legacy)
    transport=SimpleNamespace(steps=SimpleNamespace(repo=repo,app=SimpleNamespace(http=SimpleNamespace())))
    token=current_job.set(job)
    try:asyncio.run(VizierCatalogs(transport).request(tid,params={'-words':'synthetic category','-out.max':'0'}))
    finally:current_job.reset(token)
    assert visits==(['capability_probe','qualified_mirrors'] if dynamic else ['legacy'])
