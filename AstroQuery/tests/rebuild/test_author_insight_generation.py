"""New author content, type scope, exact-coordinate explanation and scoring."""
from copy import deepcopy
import json
import pytest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.author_knowledge import assemble_insight_input
from astroquery_ai.science.author_insights import property_materials,plan_units,prompt,validate_explanation,final_report
from astroquery_ai.science.results.task_score import calculate
from tests.rebuild.test_insight_snapshot_inputs import case


def setup_case():
    delivery,spec=case();b=spec['properties'][0];pid=b['property_id']
    spec['target']['target_id']='synthetic-target'
    b['definition'].update(property_id=pid,definition_version=1,content_sha256='d')
    b['output_profile'].update(profile_id='profile',version=1,content_sha256='o')
    rule={'id':'actual-rule','version':1,'content_sha256':'r'};b['rule_refs']=[rule]
    delivery['definitions']=[b]
    release={'manifest':{'release_id':'synthetic-author','content_sha256':'release'},'sources':{},
        'author':{'bindings':[{'item_id':'actual-item','otype':'*','property_id':pid,
            'definition_ref':{'id':pid,'version':'1','content_sha256':'d'},
            'output_profile_ref':{'id':'profile','version':'1','content_sha256':'o'},
            'applicability_rule_refs':[rule],'entry_ids':['meaning'],'status':'covered','reason':''}],
            'entries':[{'entry_id':'meaning','title':'合成长度解释','otypes':['*'],'conditions':[],
                'blocks':[{'role':'meaning','text':'SYNTHETIC length, conditional method statement in the body.',
                    'basis':'author_knowledge','source_ids':[]}]}],'sources':[]}}
    return delivery,spec,release


def test_task_type_and_established_rules_filter_candidates_without_star_wildcard():
    delivery,spec,release=setup_case()
    assert len(assemble_insight_input(delivery,release['author'],spec=spec)['knowledge_candidates'])==1
    spec['target']['primary_otype']='GlC'
    assert assemble_insight_input(delivery,release['author'],spec=spec)['knowledge_candidates']==[]
    spec['target']['classification_assertions']=[{'state':'current_verified','subject_identity_ref':'synthetic-target',
        'canonical_otype':'*','evidence_refs':['given']}]
    assert len(assemble_insight_input(delivery,release['author'],spec=spec)['knowledge_candidates'])==1
    spec['properties'][0]['rule_refs']=[]
    assert assemble_insight_input(delivery,release['author'],spec=spec)['knowledge_candidates']==[]


def test_exact_source_to_projection_binding_is_used_not_name_or_projected_hash():
    delivery,spec,release=setup_case();binding=spec['properties'][0]
    binding['candidate_projection_receipt']={'definition_view_hash':'d','profile_view_hash':'o',
        'source_definition_ref':{'id':binding['property_id'],'version':'1','content_sha256':'original-d'},
        'source_profile_ref':{'id':'profile','version':'1','content_sha256':'original-o'}}
    release['author']['bindings'][0]['definition_ref']['content_sha256']='original-d'
    release['author']['bindings'][0]['output_profile_ref']['content_sha256']='original-o'
    assert len(assemble_insight_input(delivery,release['author'],spec=spec)['knowledge_candidates'])==1
    binding['candidate_projection_receipt']['definition_view_hash']='changed'
    with pytest.raises(DomainError):assemble_insight_input(delivery,release['author'],spec=spec)


def test_full_facts_independent_errors_and_author_tags_reach_model_and_output():
    delivery,spec,release=setup_case();before=deepcopy(delivery)
    materials=property_materials(delivery,spec,release);units=plan_units(materials[0],delivery,spec)
    assert len(units)==1
    current=units[0];body=prompt(current,delivery,spec)
    assert 'source_fact' in body['response_constraints'][0]['allowed_kinds']
    assert 'theory_background' in body['response_constraints'][0]['allowed_kinds']
    assert len(body['units'][0]['measurements'][0]['source_uncertainty']['components'])==2
    claim=current['claims'][0]
    assert claim['authoring_basis']=='author_knowledge' and 'conditional' in claim['claim']['text']
    mid=current['measurements'][0]['measurement_id'];cid=claim['claim']['claim_id']
    reply={'units':[{'unit_id':current['unit_id'],'numeric_mode':'snapshot_placeholders/1','paragraphs':[
        {'kind':'source_fact','text':'本次原报为{{v0}}，其统计与系统分量分别保留。','measurement_ids':[mid],'claim_ids':[],
         'value_assertions':[{'measurement_id':mid,'coordinate':'source'}]},
        {'kind':'theory_background','text':'这项知识解释量的含义，不代表理论验证了本次测量。','measurement_ids':[],
         'claim_ids':[cid],'value_assertions':[]}]}]}
    current.update(status='generated',paragraphs=validate_explanation(reply,current))
    assert '2 m' in current['paragraphs'][0]['text']
    report=final_report(delivery,spec,{'id':'kb'},materials,units,1)
    assert report['status']=='complete' and report['qualified_property_ids']==[materials[0]['property_id']]
    assert report['knowledge_blocks'][0]['authoring_basis']=='author_knowledge'
    assert delivery==before and 'measurements' not in report['units'][0]
    reply['units'][0]['paragraphs'][1]['claim_ids']=['invented']
    with pytest.raises(DomainError):validate_explanation(reply,current)


def test_background_without_results_does_not_earn_insight_result_coverage():
    delivery,spec,release=setup_case();delivery['measurements']=[]
    materials=property_materials(delivery,spec,release);units=plan_units(materials[0],delivery,spec)
    units[0].update(status='generated',paragraphs=[])
    report=final_report(delivery,spec,{'id':'kb'},materials,units,1)
    assert report['status']=='not_applicable' and not report['qualified_property_ids']


def test_context_numbers_require_owned_original_evidence_not_a_new_measurement():
    from astroquery_ai.science.insight_inputs import explanation_bindings,explanation_wire
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    record=current['measurements'][0];mid=record['measurement_id'];cid=current['claims'][0]['claim']['claim_id']
    record['source_evidence']=[{'evidence_id':'synthetic-owned-context','raw_text':'SYNTHETIC fit uses W=7.4 at D=3.6 kpc; another fit uses W=8.3.','locator':{'page':2}}]
    before=deepcopy(current)
    response={'units':[{'unit_id':current['unit_id'],'paragraphs':[
        {'kind':'source_fact','text':'原报{{v0}}；模型条件W={{v1}}。','measurement_ids':[mid],'claim_ids':[],
         'value_assertions':[{'measurement_id':mid,'coordinate':'source'},
             {'measurement_id':mid,'coordinate':'context','evidence_id':'synthetic-owned-context','literal':'7.4'}]},
        {'kind':'theory_background','text':'按给定知识解释，不增加新的测量。','measurement_ids':[],'claim_ids':[cid],'value_assertions':[]}]}]}
    wire=explanation_bindings([current],delivery,include_context_evidence=True)
    encoded=explanation_wire(response,wire)
    assert encoded['units'][0]['paragraphs'][0]['value_assertions'][1]['evidence_id']=='E1'
    paragraphs=validate_explanation(explanation_wire(encoded,wire,expand=True),current)
    assert 'W=7.4' in paragraphs[0]['text'] and paragraphs[0]['value_assertions'][1]['scope']=='source_context_quotation_not_measurement'
    assert current==before
    response['units'][0]['paragraphs'][0]['value_assertions'][1]['literal']='7.5'
    with pytest.raises(DomainError) as error:validate_explanation(response,current)
    assert error.value.code=='INSIGHT_CONTEXT_SCOPE'
    response['units'][0]['paragraphs'][0]['value_assertions'][1].update(literal='7.4',evidence_id='another-record')
    with pytest.raises(DomainError):validate_explanation(response,current)


def test_unbound_context_numeric_repair_receives_the_actual_paragraph_and_literal():
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    mid=current['measurements'][0]['measurement_id']
    response={'units':[{'unit_id':current['unit_id'],'paragraphs':[
        {'kind':'source_fact','text':'模型条件W=7.4。','measurement_ids':[mid],'claim_ids':[],'value_assertions':[]}]}]}
    with pytest.raises(DomainError) as error:validate_explanation(response,current)
    assert error.value.code=='INSIGHT_VALUE_ASSERTION_MISSING'
    assert error.value.details['paragraph_index']==0 and error.value.details['unbound_literals']==['7.4']


def test_server_supplied_numeric_labels_remove_coordinate_transcription():
    from astroquery_ai.science.insight_inputs import explanation_bindings
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    record=current['measurements'][0];record['source_evidence']=[{'evidence_id':'context-piece','raw_text':'SYNTHETIC W=7.4, not another measurement.','locator':{'page':1}}]
    mid=record['measurement_id'];cid=current['claims'][0]['claim']['claim_id'];wire=explanation_bindings([current],delivery,include_context_evidence=True)
    response={'units':[{'unit_id':current['unit_id'],'paragraphs':[
        {'kind':'source_fact','text':'原报{{V1}}，模型条件W={{C:M1:E1:7.4}}。','measurement_ids':[],'claim_ids':[]},
        {'kind':'theory_background','text':'给定知识背景。','measurement_ids':[],'claim_ids':[cid]}]}]}
    paragraphs=validate_explanation(response,current,bindings=wire)
    assert '2 m' in paragraphs[0]['text'] and 'W=7.4' in paragraphs[0]['text']
    assert paragraphs[0]['measurement_ids']==[mid]
    assert paragraphs[0]['value_assertions'][0]['coordinate']=='source'
    assert paragraphs[0]['value_assertions'][1]['scope']=='source_context_quotation_not_measurement'
    response['units'][0]['paragraphs'][0]['text']='{{V999}}'
    with pytest.raises(DomainError):validate_explanation(response,current,bindings=wire)


def test_mixed_definition_boundary_is_not_mechanically_downgraded_to_source_only():
    from astroquery_ai.science.prompt_contracts import property_view
    boundary='SYNTHETIC estimator restriction applies to this selected quantity. Catalogue Q is an example only.'
    original={'property_id':'synthetic','definition':{'description':'SYNTHETIC quantity. '+boundary,
        'explanation':{'quantity':'SYNTHETIC quantity','boundary':boundary}}}
    view=property_view(original)
    assert view['definition']['description']==original['definition']['description']
    assert view['source_annotations']['content_kind']=='mixed_identity_constraints_and_source_examples'
    assert original['definition']['explanation']['boundary']==boundary


def test_confirmed_wording_is_carried_only_for_the_selected_frozen_binding():
    from astroquery_ai.science.prompt_contracts import confirmed_property_intent
    spec={'raw_query':'SYNTHETIC unbound text','property_selection':{'requests':[
        {'text':'SYNTHETIC estimator A','candidate_property_ids':['p']},
        {'text':'SYNTHETIC unrelated','candidate_property_ids':['other']},
        {'text':'SYNTHETIC estimator A','candidate_property_ids':['p']}]}}
    assert confirmed_property_intent(spec,'p')==['SYNTHETIC estimator A']
    assert confirmed_property_intent(spec,'absent')==[]


def test_repair_points_to_real_reference_choices_without_picking_the_science():
    from astroquery_ai.science.author_insights import explanation_repair
    from astroquery_ai.science.insight_inputs import explanation_bindings
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    current['measurements'][0]['source_evidence']=[{'evidence_id':'original','raw_text':'SYNTHETIC W=7.4'}]
    wire=explanation_bindings([current],delivery,include_context_evidence=True)
    error=DomainError('INSIGHT_VALUE_ASSERTION_MISSING','test',paragraph_index=1,unbound_literals=['7.4','99.9'])
    repair=explanation_repair(error,current,wire)
    assert any(r['reference']=='{{C:M1:E1:7.4}}' for r in repair['existing_reference_choices'])
    assert not any(r['literal']=='99.9' for r in repair['existing_reference_choices'])
    assert repair['details']['paragraph_index']==1


def test_new_score_pending_then_final_uses_fixed100_even_when_generation_fails(tmp_path):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC author score')['task_id']
    spec={'spec_hash':'synthetic','properties':[{'property_id':'p'}],
        'run_policy':{'insights':{'mode':'dot_author/1'}}}
    snapshot={'query':spec,'measurements':[],'derived':[]}
    with repo.transaction() as c:
        pending=calculate(repo,c,tid,spec,snapshot,delivery_verified=True)
        failed=calculate(repo,c,tid,spec,snapshot,delivery_verified=True,
            insight_report={'status':'partial','qualified_property_ids':[]})
    assert pending['score'] is None and pending['status']=='pending'
    assert failed['score']==0 and failed['possible_points']==100 and failed['excluded_scope']==[]
    assert failed['components'][-1]['earned']==0


def test_scoped_method_quote_gets_a_reference_without_becoming_a_new_measurement():
    from astroquery_ai.science.insight_inputs import explanation_bindings,explanation_wire
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    m=current['measurements'][0];m['source_evidence']=[]
    m['source_statements']=[{'statement_id':'actual-owned-statement','qualification':'scoped_source_interpretation',
        'subject_scope':'target','property_scope':'selected_quantity','page':4,'raw_quote':'SYNTHETIC fit epoch 6.3 with parameter 4.8.'}]
    binding=explanation_bindings([current],delivery,include_context_evidence=True)
    assert binding['groups']['E']=={'E1':'actual-owned-statement'}
    cid=current['claims'][0]['claim']['claim_id']
    reply={'units':[{'unit_id':current['unit_id'],'paragraphs':[
        {'kind':'source_fact','text':'原报{{V1}}，该来源假设{{C:M1:E1:6.3}}。','measurement_ids':[],'claim_ids':[]},
        {'kind':'theory_background','text':'给定的条件性理论。','measurement_ids':[],'claim_ids':[cid]}]}]}
    result=validate_explanation(reply,current,bindings=binding)
    assert result[0]['value_assertions'][1]['reference_kind']=='scoped_source_statement'
    assert result[0]['value_assertions'][1]['scope']=='source_context_quotation_not_measurement'
    assert explanation_wire(prompt(current,delivery,spec),binding)['units'][0]['measurements'][0]['source_statements'][0]['statement_id']=='E1'
    m['source_statements'][0]['qualification']='not_independently_verified'
    with pytest.raises(DomainError):validate_explanation(reply,current,bindings=binding)


def test_one_numeric_format_repair_receives_all_affected_paragraphs():
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    mid=current['measurements'][0]['measurement_id']
    reply={'units':[{'unit_id':current['unit_id'],'paragraphs':[
        {'kind':'source_fact','text':'参数7.4。','measurement_ids':[mid],'claim_ids':[]},
        {'kind':'usage_limit','text':'条件8.3。','measurement_ids':[mid],'claim_ids':[]}]}]}
    with pytest.raises(DomainError) as error:validate_explanation(reply,current)
    assert error.value.details['unbound_literals']==['7.4','8.3']
    assert [p['paragraph_index'] for p in error.value.details['paragraph_issues']]==[0,1]


def test_context_scope_repair_offers_actual_owned_labels_with_compact_identity():
    from astroquery_ai.science.author_insights import explanation_repair
    from astroquery_ai.science.insight_inputs import explanation_bindings
    delivery,spec,release=setup_case();current=plan_units(property_materials(delivery,spec,release)[0],delivery,spec)[0]
    m=current['measurements'][0];m['source_evidence']=[{'evidence_id':'owned-page','raw_text':'SYNTHETIC parameter 4.8'}]
    binding=explanation_bindings([current],delivery,include_context_evidence=True)
    err=DomainError('INSIGHT_CONTEXT_SCOPE','test',unit_id=current['unit_id'],paragraph_index=0,
        assertion={'measurement_id':m['measurement_id'],'evidence_id':'owned-page','literal':'4.8'})
    feedback=explanation_repair(err,current,binding)
    assert feedback['details']['unit_id']=='I1'
    assert feedback['details']['invalid_reference']['measurement']=='M1'
    assert feedback['existing_reference_choices'][0]['reference']=='{{C:M1:E1:4.8}}'
    assert 'navigation_excerpt' not in feedback['existing_reference_choices'][0]
