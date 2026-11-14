"""Bounded production-protocol regressions; synthetic cases are not scientific evidence."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

from astroquery_ai.runtime.codec import loads
from astroquery_ai.science.documents import identity_page_view
from astroquery_ai.science.papers.acquisition import verify_download_identity


def test_catalog_initial_groups_budget_the_actual_prompt_not_only_raw_nodes():
    from astroquery_ai.science.catalog.selection import screening_batches,ranking_messages
    from astroquery_ai.runtime.calls import input_upper_bound
    spec={'target':{'main_id':'SYNTHETIC'},'properties':[{'property_id':'p'+str(i),
        'definition':{'description':'SYNTHETIC definition. '*300,'value_schema':{'kind':'real'}}} for i in range(4)]}
    nodes=[{'node_id':f'table{i}','description':'SYNTHETIC actual metadata',
        'columns':[{'name':f'c{j}','description':'SYNTHETIC field definition. '*12} for j in range(30)]} for i in range(26)]
    groups=list(screening_batches(nodes,spec=spec))
    assert len(groups)>1
    assert {n['node_id'] for group in groups for n in group}=={n['node_id'] for n in nodes}
    assert all(len(n['columns'])==30 for group in groups for n in group)
    assert all(input_upper_bound(ranking_messages(spec,group))<=96000-2048 for group in groups)


def test_catalog_metadata_labels_keep_the_full_column_set_and_bind_source():
    from astroquery_ai.science.catalog.selection import ranking_messages,checked_ranking,screening_batches
    spec={'target':{'main_id':'SYNTHETIC'},'properties':[]}
    node={'node_id':'table','description':'Actual catalogue description',
          'columns':[{'name':f'c{i}','description':f'Actual definition {i}'} for i in range(70)]}
    body=loads(ranking_messages(spec,[node])[0]['content'])
    assert len(body['metadata'][0]['evidence'])==71
    spec['properties']=[{'property_id':'p'}]
    result=checked_ranking({'candidates':[{'node_id':'table','property_ids':['p'],
        'priority':2,'evidence_ids':['C70']}]},[node],spec)
    assert result[0]['bound_metadata_evidence'][0]['column']=='c69'
    assert sum(len(n['columns']) for batch in screening_batches([node]) for n in batch)==70


def test_native_log_copy_keeps_original_coefficient_instead_of_calculating():
    from astroquery_ai.science.extraction_wire import extraction_bindings,expand_extraction
    spec={'properties':[{'property_id':'p'}]}
    binding=extraction_bindings(spec,rows=[0])
    result=expand_extraction({'results':[{'property_id':'P1','row':'R1','column':'x','native_cell':True,
        'representation':'log10','limit':'none'}]},binding,rows={0:{'x':'9.450'}},
        columns=[{'name':'x','datatype':'double','unit_text':'yr'}])['results'][0]
    assert result['value']=={'kind':'real','value':'9.450'} and result['raw_value']=='9.450'


def test_new_source_evidenced_error_columns_amend_the_navigation_plan():
    from tests.rebuild.test_catalog_transcription import proposal
    from astroquery_ai.science.catalog_transcription import preserve_catalog_fields
    item=proposal().model_copy(update={'catalog_field_roles':[]})
    from astroquery_ai.science.measurements.contracts import CatalogFieldRole
    item=item.model_copy(update={'catalog_field_roles':[CatalogFieldRole(column='lo',role='uncertainty',
        source_quote='Lower reported quantile',reason='Source lower endpoint, not a symmetric sigma'),
        CatalogFieldRole(column='hi',role='uncertainty',source_quote='Upper reported quantile',reason='Source upper endpoint')]})
    columns=[{'name':'DM','description':'Native value'},{'name':'lo','description':'Lower reported quantile'},
             {'name':'hi','description':'Upper reported quantile'}]
    result,checks=preserve_catalog_fields(item,{'DM':'26.764100','lo':'26.7','hi':'26.9'},
        {'value_column':'DM','error_columns':[]},columns)
    assert {e.location:e.raw_text for e in result.errors}=={'lo':'26.7','hi':'26.9'}
    assert all(e.interpretation_state=='unresolved' for e in result.errors)
    assert any(c['state']=='source_evidenced_auxiliary_plan_amendment' for c in checks)


def test_source_notation_uses_actual_cells_and_alias_labels_without_spelling_options():
    from astroquery_ai.science.catalog_identity import identity_prompt,checked_identities
    target={'main_id':'SYNTHETIC A','aliases':[]}
    table={'columns':[{'name':'Object','datatype':'char','description':'Object designation'}],
        'rows':[{'Object':'SYNTHETIC_A'}],'table_id':'J/SYNTHETIC/table','description':'Actual object catalogue'}
    prompt,spans=identity_prompt(target,table,table['rows'],[0],'Object')
    assert 'notation_options' not in prompt
    response={'rows':[{'row':0,'relation':'same_entity','method':'source_notation','source_column':'Object',
        'target_alias_id':'A1','evidence_ids':['cell:0:Object','column:Object'],
        'reason':'Source row spelling expresses the supplied target identifier.'}]}
    checked=checked_identities(response,target,table,table['rows'],[0],'Object',spans)
    assert checked[0]['state']=='accepted'
    response['rows'][0]['target_alias_id']='A999'
    assert checked_identities(response,target,table,table['rows'],[0],'Object',spans)[0]['state']=='unresolved'


def test_quantity_identity_cannot_call_derivation_an_exact_match():
    import pytest
    from pydantic import ValidationError
    from astroquery_ai.science.measurements.admission_contracts import AdmissionCheck
    raw={'index':0,'subject':'target','printed_subject':'SYNTHETIC','subject_evidence':[],
         'result_role':'reported_result','role_evidence':[],'reason':'Actual related coordinate',
         'quantity_match':'exact','quantity_identity':{
             'reported_quantity':'Related source coordinate','subject_scale':'same aggregate',
             'native_representation':'source-native logarithmic coordinate','relation':'requires_derivation',
             'evidence':[{'page':1,'block_ids':['p1:l1-1']}]}}
    with pytest.raises(ValidationError):AdmissionCheck.model_validate(raw)
    raw['quantity_match']='different'
    assert AdmissionCheck.model_validate(raw).quantity_identity.relation=='requires_derivation'
    raw.pop('quantity_identity')
    assert 'quantity_identity' not in AdmissionCheck.model_validate(raw).model_dump(mode='json')


def test_actual_review_input_keeps_declared_dimension_and_quantity_focus():
    from astroquery_ai.science.paper_admission import verification_instruction
    binding={'property_id':'synthetic-whole-length','definition':{
        'name_cn':'合成整体长度','name_en':'Synthetic whole length','quantity_key':'synthetic.length',
        'quantity_kind':'length','scope':'whole','description':'Source-reported whole length.',
        'aliases':[],'measurement_conditions_schema':[],
        'explanation':{'quantity':'Source-reported whole length','subject':'identified whole target',
            'representation':'native linear length','boundary':'Retain related model context.'}},
        'output_profile':{'unit':{'kind':'physical','dimension':'length','canonical_symbol':'m'},'representation':{'kind':'linear'}}}
    prompt=verification_instruction({'target':{'main_id':'SYNTHETIC','aliases':[]},'properties':[binding]},[],{1:'Actual original source'},compact=True)
    view=prompt['properties'][0]
    assert view['definition']['quantity_kind']=='length'
    assert view['quantity_focus']['quantity_kind']=='length'
    assert view['declared_measurand_dimension']=='length'


def test_registered_coordinate_dimensions_are_necessary_not_quantity_identity():
    from astroquery_ai.science.native_dimensions import contradiction
    physical={'representation':{'kind':'linear'},'unit':{'kind':'physical','canonical_symbol':'pc'}}
    def field(unit):return {'name':'actual','datatype':'double','unit_text':unit}
    assert contradiction(field('mag'),physical,'magnitude')['registered_function_coordinate']
    assert contradiction(field('km/s'),physical)['source_dimension']=='speed/velocity'
    assert contradiction(field('kpc'),physical) is None
    assert contradiction(field('undefined_actual_unit'),physical) is None
    logarithm={'representation':{'kind':'log10'},'unit':{'kind':'physical','canonical_symbol':'yr'}}
    assert contradiction(field('dex'),logarithm,'log10') is None
    magnitude={'representation':{'kind':'magnitude'},'unit':{'kind':'physical','canonical_symbol':'mag'}}
    assert contradiction(field('mag'),magnitude,'magnitude') is None


def test_title_input_omits_layout_and_expands_actual_front_matter_only_once():
    async def run():
        title='Actual printed title with typography'
        index={'sha256':'synthetic','page_count':3,'pages':[
            {'page':1,'text':'DOI:10.1234/test\n'+'Unrelated front matter\n'*5000,'layout_lines':[{'text':'x'}]*30000},
            {'page':2,'text':title+'\n'+'Body\n'*5000},
            {'page':3,'text':'Other actual front matter'}]}
        work={'work_id':'synthetic','records':[{'titles':['Metadata version of the actual title'],
            'dois':['10.1234/test'],'arxivs':[]}]}
        calls=[]
        async def model(execution,**kwargs):
            body=loads(kwargs['messages'][0]['content']);calls.append((kwargs,body))
            assert all('layout_lines' not in p for p in body['actual_pages'])
            if len(calls)==1:return {'same_title':None,'printed_title_quote':None,'page':None},{'attempt_id':'one'}
            return {'same_title':True,'printed_title_quote':title,'page':2},{'attempt_id':'two'}
        service=SimpleNamespace(steps=SimpleNamespace(model=model),model_profile=lambda *a,**kw:kw,
            repo=SimpleNamespace(read=lambda:nullcontext(None)),spec=lambda *a:{'run_policy':{'documents':{}}})
        proof=await verify_download_identity(service,{'task_id':'synthetic'},index,work)
        assert proof['state']=='verified' and proof['title_equivalence']['page']==2
        assert len(calls)==2 and len({c[0]['root_id'] for c in calls})==1
        assert len(calls[0][1]['actual_pages'])==1 and len(calls[1][1]['actual_pages'])==3
        for _,body in calls:assert len(str(body)) < 32000
        assert identity_page_view(index)[0]['text']==index['pages'][0]['text'][:identity_page_view(index)[0]['source_char_range'][1]]
    asyncio.run(run())
