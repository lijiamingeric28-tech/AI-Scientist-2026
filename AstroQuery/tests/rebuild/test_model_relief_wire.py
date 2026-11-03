"""Wire changes preserve exact native evidence; synthetic boundaries only."""
from copy import deepcopy
import pytest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.model_bindings import binding_ref,map_fields
from astroquery_ai.science.extraction_wire import extraction_bindings,extraction_wire,expand_extraction,deduplicate_context
from astroquery_ai.science.evidence_views import locate_excerpt,table_view
from astroquery_ai.science.scientific_conditions import semantic_wire,expand_semantic_wire
from astroquery_ai.science.extraction_wire import unified_paper_extraction

SPEC={'spec_hash':'synthetic-spec','properties':[{'property_id':'synthetic-property'}]}


def test_unified_initial_core_page_binding_keeps_errors_and_unreviewed_navigation():
    binding=extraction_bindings(SPEC,artifact='synthetic-original')
    blocks=[{'block_id':'p2:l1-3','page':2,'text':'SYNTHETIC target length 1.200 ± .03 m.'},
            {'block_id':'p1:l1-3','page':1,'text':'Method and subject scope, needed for independent quality.'}]
    raw={'results':[{'property_id':'P1','page':2,'raw_value':'1.200','value':{'kind':'real','value':'1.200'},
        'errors':[{'raw_text':'.03','values':{'delta':'.03'}}],
        'local_admission':{'role_evidence':[{'page':1,'block_ids':['p1:l1-3']}],'subject':'target'},
        'source_quality':{'raw_info':['p1:l1-3'],'note':'optional initial opinion, not a check'}}]}
    before=deepcopy(raw);expanded,notes=unified_paper_extraction(raw,binding,blocks=blocks,core_pages=[2])
    item=expanded['results'][0]
    assert item['source_quote']==blocks[0]['text'] and item['raw_value']=='1.200'
    assert item['errors']==raw['results'][0]['errors'] and 'local_admission' not in item and 'source_quality' not in item
    assert notes[0]['blocks']==[blocks[1]] and notes[0]['raw_annotations']=={k:raw['results'][0][k] for k in ['local_admission','source_quality']}
    assert raw==before
    # Context-only output, scans, missing page and invalid explicit references
    # still cannot manufacture a native quote or quality admission.
    for change in [{'page':1},{'page':None},{'page':3},{'source_blocks':['invented']}]:
        bad=deepcopy(raw);bad['results'][0].update(change)
        value,_=unified_paper_extraction(bad,binding,blocks=blocks,core_pages=[2])
        assert 'source_quote' not in value['results'][0]


def test_reference_map_never_rewrites_prose_or_schema():
    data={'property_id':'synthetic-property','quote':'synthetic-property',
        'schema':{'properties':{'property_id':{'type':'string'}}}}
    wire=map_fields(data,{'property_id':{'P1':'synthetic-property'}})
    assert wire['property_id']=='P1' and wire['quote']==data['quote']
    assert wire['schema']==data['schema']
    assert map_fields(wire,{'property_id':{'P1':'synthetic-property'}},expand=True)==data


def test_identical_wire_labels_do_not_share_source_binding():
    a=extraction_bindings(SPEC,artifact='synthetic-a',rows=[0])
    b=extraction_bindings(SPEC,artifact='synthetic-b',rows=[0])
    assert a['groups']==b['groups'] and a['binding_hash']!=b['binding_hash']
    with pytest.raises(DomainError):map_fields({'property_id':'P2'},{'property_id':a['groups']['P']},expand=True)


def test_native_scalar_is_server_copied_without_touching_error_interpretation():
    binding=extraction_bindings(SPEC,artifact='synthetic-a',rows=[17])
    result={'results':[{'property_id':'P1','row':'R1','column':'x','native_cell':True,
        'representation':'linear','limit':'none','errors':[{'raw_text':'.03','role':'unspecified'}]}]}
    native={17:{'x':' 12.3000 ','error':'.03'}}
    columns=[{'name':'x','datatype':'double','unit':'ms'}]
    expanded=expand_extraction(result,binding,rows=native,columns=columns)['results'][0]
    assert expanded['row']==17 and expanded['property_id']=='synthetic-property'
    assert expanded['raw_value']==' 12.3000 ' and expanded['value']['value']=='12.3000'
    assert expanded['unit']=='ms' and expanded['errors']==result['results'][0]['errors']
    assert native[17]['x']==' 12.3000 '


@pytest.mark.parametrize('literal,limit,representation',[
    ('12.3 +/- .2','none','linear'),('NaN','none','linear'),('12.3','upper','linear'),
    ('log(12.3)','none','log10'),('NULL','none','linear')])
def test_complex_or_non_point_native_cells_require_semantic_proposal(literal,limit,representation):
    bindings=extraction_bindings(SPEC,rows=[0])
    raw={'results':[{'row':'R1','column':'x','native_cell':True,'limit':limit,'representation':representation}]}
    result=expand_extraction(raw,bindings,rows={0:{'x':literal}},columns=[{'name':'x','null':'NULL'}])
    assert 'value' not in result['results'][0]


def test_pdf_selected_original_blocks_and_invalid_sibling_are_separate():
    bindings=extraction_bindings(SPEC,artifact='synthetic-pdf')
    blocks=[{'block_id':'p2:l1-3','page':2,'text':'SYNTHETIC original measurement and its error.'}]
    raw={'results':[{'page':2,'property_id':'P1','source_blocks':['p2:l1-3']},
                    {'page':3,'property_id':'P1','source_blocks':['p2:l1-3']}]}
    result=expand_extraction(raw,bindings,blocks=blocks)['results']
    assert result[0]['source_quote']==blocks[0]['text']
    assert 'source_quote' not in result[1]
    assert raw['results'][0].get('source_quote') is None
    raw={'results':[{'page':2,'local_admission':{'role_evidence':[{'page':2,'block_ids':['p2:l1-3']}]}}]}
    assert expand_extraction(raw,bindings,blocks=blocks)['results'][0]['source_quote']==blocks[0]['text']


def test_context_dedup_is_exact_same_page_and_keeps_counterevidence():
    a={'page':2,'block_id':'p2:l1-3','text':'SYNTHETIC full header and uncertainty.'}
    b={'page':1,'block_id':'p1:l1-3','text':'SYNTHETIC other subject, not this measurement.'}
    original={'page_evidence':[a],'document_frame':[b],'context_fragments':[deepcopy(a)]}
    wire=deduplicate_context(original)
    assert wire['context_fragments'][0]['text_ref']==a['block_id']
    assert wire['document_frame'][0]['text']==b['text']
    assert original['context_fragments'][0]['text']==a['text']


def test_science_wire_keeps_unknown_component_and_all_native_text():
    record={'measurement_id':'synthetic-long-id','content_sha256':'synthetic-hash',
            'uncertainty':{'components':[{'component_id':'synthetic-component','raw_text':'0','interpretation_state':'unresolved'}]}}
    payload={'measurement':record,'server_record_bindings':{'target_ref':'internal'},
        'response_template':{'uncertainty':[{'component_id':'synthetic-component'}]},
        'contexts':[{'key':'epoch','on_missing':'retain_unknown'}],
        'evidence_spans':[{'span_id':'s1','text':'SYNTHETIC original zero is unknown, not an error of zero.'}]}
    wire,binding=semantic_wire(payload,record)
    assert 'measurement_id' not in wire['measurement'] and 'server_record_bindings' not in wire
    assert wire['measurement']['uncertainty']['components'][0]['raw_text']=='0'
    assert wire['contexts']==payload['contexts'] and wire['evidence_spans']==payload['evidence_spans']
    expanded=expand_semantic_wire({'uncertainty':[{'component_id':'U1'},{'component_id':'U9'}]},binding)
    assert expanded['uncertainty']==[{'component_id':'synthetic-component'},{'component_id':'U9'}]


def test_native_highlight_is_unique_and_scan_or_repeated_text_degrades():
    line={'text':'SYNTHETIC target native statement with error','bbox':[10,20,400,35]}
    assert locate_excerpt({'layout_lines':[line]},line['text'])==[line['bbox']]
    assert locate_excerpt({'layout_lines':[line,line]},line['text'])==[]
    assert locate_excerpt({'layout_lines':[]},line['text'])==[]
    assert locate_excerpt({'layout_lines':[line]},'model changed the statement')==[]
    assert locate_excerpt({'layout_lines':[line]},'12.3')==[]
    assert locate_excerpt({'layout_lines':[line],'width':200,'height':100},line['text'])==[]
    assert locate_excerpt({'layout_lines':[line],'layout_rotation':90},line['text'])==[]
    assert locate_excerpt({'layout_lines':[line],'layout_rotation':90,'layout_coordinate_space':'rendered_page_points'},line['text'])==[line['bbox']]


def test_attachment_row_is_original_data_row_not_query_offset():
    raw={'evidence_id':'synthetic-evidence','artifact_ref':{'id':'synthetic-file'},
        'raw_text':canonical({'cells':{'x':'12.300','e_x':'.03'},'columns':[{'name':'x','unit':'m'}]}).decode(),
        'locator':{'table':'synthetic-table','row':47,'column':'x'}}
    view=table_view(raw,{'kind':'official_attachment','work_id':'synthetic-parent'})
    assert view['row']==47 and view['row_basis']=='attachment_data_row'
    assert next(c['raw'] for c in view['cells'] if c['column']=='e_x')=='.03'
    assert view['parent_work_id']=='synthetic-parent'


def test_new_delivery_api_and_five_exports_share_exact_evidence_view(tmp_path):
    import asyncio,csv,io,zipfile,httpx
    from astroquery_ai.runtime.codec import loads,digest
    from tests.rebuild.scenario import application,confirmed_case
    from astroquery_ai.api.http import create_app
    from astroquery_ai.science.results.exporting import _serialize
    async def run():
        app=application(tmp_path/'data')
        state,_=await confirmed_case(app)
        with app.repository.read() as conn:
            delivery=app.delivery.get(conn,state['task_id'])
        original_hash=digest(delivery)
        view=delivery['evidence_views'][0]
        assert view['kind']=='table' and view['cells'] and view['row_basis']=='query_response_row'
        web=create_app(root=app.root,application=app,start_worker=False,allow_synthetic=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web),base_url='http://test') as client:
            response=await client.get(f"/api/tasks/{state['task_id']}/deliveries/{delivery['delivery_id']}/records")
        assert response.status_code==200
        assert response.json()['items'][0]['evidence_views']==delivery['evidence_views']
        for format in ('json','json_wide','csv_long','csv_wide','package'):
            raw,_=_serialize(delivery,format)
            if format=='json':assert loads(raw)['evidence_views']==delivery['evidence_views']
            elif format=='json_wide':assert loads(raw)['metadata']['evidence_views']==delivery['evidence_views']
            elif format.startswith('csv'):
                row=next(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
                assert loads(row['evidence_views_json'])==delivery['evidence_views']
            else:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    assert loads(z.read('delivery.json'))['evidence_views']==delivery['evidence_views']
        assert digest(delivery)==original_hash
    asyncio.run(run())
