"""Task book 1.1–1.3: short references, complete science, local failures."""
from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science import property_insights as cards
from astroquery_ai.science.insight_inputs import explanation_wire
from tests.rebuild.test_author_insight_generation import setup_case


def example():
    delivery,spec,release=setup_case()
    current=cards.property_units(delivery,spec,release)[0]
    current['measurements'][0]['source_evidence']=[{'evidence_id':'synthetic-evidence',
        'raw_text':'SYNTHETIC comparison companion, not the target.',
        'locator':{'page':3},'text_origin':'native_pdf_text'}]
    return delivery,spec,current


def reply(current):
    entry={'text':'这些记录保留各自独立误差，按实际主体和测量条件分组使用。',
        'measurement_ids':[current['measurements'][0]['measurement_id']],
        'evidence_ids':['synthetic-evidence'],'claim_ids':[]}
    return {'found':[entry],'comparison':[],'uses':[deepcopy(entry)],'limitations':[],'findings':[]}


def test_all_records_errors_conditions_and_originals_survive_projection():
    d,s,u=example();text='完整原文、表头脚注与独立误差保留。'*100
    u['measurements'][0]['source_evidence'][0]['raw_text']=text
    second=deepcopy(u['measurements'][0]);second['measurement_id']='another';u['measurements'].append(second)
    d['measurements'].append({**deepcopy(d['measurements'][0]),'measurement_id':'another'})
    before=deepcopy((d,s,u));packed,b=cards.model_input(u,d,s);body=cards.unpack_materials(packed)
    assert body==explanation_wire(cards.prompt(u,d,s),b)
    assert len(body['record_index'])==2 and len(body['original_materials'])==1
    assert body['original_materials'][0]['raw_text']==text
    assert len(body['record_index'][0]['source_uncertainty']['components'])==2
    assert len(body['sources'])==1 and 'source_id' not in body['sources'][0]
    assert (d,s,u)==before


def test_zero_quote_output_binds_actual_original_and_same_record_values():
    d,s,u=example();_,b=cards.model_input(u,d,s)
    card=cards.validate_reply(explanation_wire(reply(u),b),u,b);p=card['sections']['found'][0]
    assert card['status']=='generated' and not card['validation_issues']
    assert p['evidence_ids']==['synthetic-evidence'] and 'quote' not in p and 'value_assertions' not in p
    assert p['measurement_ids']==[u['measurements'][0]['measurement_id']]
    assert u['measurements'][0]['source_value']['value']['value']=='2'


def test_finding_uses_real_location_without_model_quote_and_needs_owner():
    d,s,u=example();r=reply(u);mid=u['measurements'][0]['measurement_id']
    r['findings']=[{'classification':'explicit_counterevidence','issue':'subject',
        'measurement_ids':[mid],'evidence_ids':['synthetic-evidence'],'reason':'原文主体为比较伴星，需责任复检。'}]
    before=deepcopy(u);f=cards.validate_reply(r,u)['findings'][0]
    assert f['owner_state']=='pending_owner_recheck' and f['anchors'][0]['locator']=={'page':3}
    assert 'quote' not in f['anchors'][0] and u==before
    r['findings'][0]['evidence_ids']=['other-record-evidence']
    card=cards.validate_reply(r,u)
    assert not card['findings'] and card['sections']['found'] and card['field_states']['findings']=='partial'


def test_bad_reference_is_local_and_preserves_valid_siblings():
    d,s,u=example();_,b=cards.model_input(u,d,s);r=explanation_wire(reply(u),b)
    r['comparison']=[{'text':'一个无效引用。','measurement_ids':['M999'],'evidence_ids':[],'claim_ids':[]}]
    card=cards.validate_reply(r,u,b)
    assert card['status']=='generated' and card['sections']['found'] and card['sections']['uses']
    assert not card['sections']['comparison'] and len(card['validation_issues'])==1
    assert card['validation_issues'][0]['rejected_fragment']['measurement_ids']==['M999']


def test_evidence_only_explanation_does_not_require_repeating_location_owners():
    _,_,u=example();r=reply(u)
    r['comparison']=[{'text':'按这段原文所述的方法条件分别比较。','measurement_ids':[],
                       'evidence_ids':['synthetic-evidence'],'claim_ids':[]}]
    paragraph=cards.validate_reply(r,u)['sections']['comparison'][0]
    assert paragraph['measurement_ids']==[]
    assert paragraph['evidence_record_ids']==[u['measurements'][0]['measurement_id']]
    r['comparison'][0]['evidence_ids']=['foreign-property-evidence']
    assert not cards.validate_reply(r,u)['sections']['comparison']


def test_writing_target_is_not_a_character_number_or_item_count_gate():
    _,_,u=example();r=reply(u);r['uses']=[deepcopy(r['uses'][0]) for _ in range(3)]
    r['uses'][0]['text']='M67与47 Tuc的名字和GM/R²数学记号不是新测量断言。'
    assert len(cards.validate_reply(r,u)['sections']['uses'])==3
    r['found'][0]['text']='{{V1}}';out=cards.validate_reply(r,u)
    assert not out['sections']['found'] and out['sections']['uses']


def test_inline_main_value_range_is_a_local_card_format_issue_not_a_whole_property_failure():
    _,_,u=example();r=reply(u)
    r['found'].append({**deepcopy(r['found'][0]),'text':'这些结果集中在2–3 m区间。'})
    card=cards.validate_reply(r,u)
    assert len(card['sections']['found'])==1 and card['sections']['uses']
    assert card['validation_issues'][0]['code']=='INSIGHT_NUMERIC_CARD_FORMAT'
    r['found'][1]['text']='M67和47 Tuc的名字含数字；GM/R²是模型关系，2026年只是背景年份。'
    assert len(cards.validate_reply(r,u)['sections']['found'])==2


def test_dot_conditions_and_labels_remain_without_compulsory_theory_filler():
    d,s,u=example();u['claims'][0]['conditions']=['SYNTHETIC only this method']
    packed,_=cards.model_input(u,d,s);k=cards.unpack_materials(packed)['knowledge'][0]
    assert k['authoring_basis']=='author_knowledge' and k['conditions']==u['claims'][0]['conditions']
    assert 'conditional' in k['claim']['text']
    r=reply(u);r['uses'][0]['claim_ids']=[u['claims'][0]['claim']['claim_id']]
    assert cards.validate_reply(r,u)['sections']['uses'][0]['claim_ids']
    r['uses'][0]['claim_ids']=['other-property-claim']
    assert not cards.validate_reply(r,u)['sections']['uses']


def test_unverified_context_quote_is_preserved_without_becoming_original_evidence():
    d,s,u=example();u['measurements'][0]['source_statements']=[{
        'statement_id':'synthetic-unverified','raw_quote':'SYNTHETIC unresolved model context',
        'text':'A stored interpretation, not original scientific proof.',
        'qualification':'not_independently_verified','subject_scope':'unresolved'}]
    packed,_=cards.model_input(u,d,s);body=cards.unpack_materials(packed)
    saved=body['record_index'][0]['saved_interpretations'][0]
    assert saved['raw_quote']=='SYNTHETIC unresolved model context'
    assert saved['qualification']=='not_independently_verified'
    assert not any(e['evidence_id']=='synthetic-unverified' for e in body['original_materials'])


def test_same_value_same_paper_do_not_merge_without_saved_archive():
    d,_,u=example();second=deepcopy(u['measurements'][0]);second['measurement_id']='another';u['measurements'].append(second)
    assert cards.coverage(d,u)['measurement_group_count']==2
    assert cards.coverage(d,u)['contributing_source_count']==1
    d['archive_groups']=[{'group_id':'saved','member_refs':[{'id':r['measurement_id']} for r in u['measurements']]}]
    assert cards.coverage(d,u)['measurement_group_count']==1
    assert len(u['measurements'])==2


def test_only_exact_owner_revision_suppresses_examples_without_changing_science():
    d,s,u=example();r=d['measurements'][0];r.setdefault('revision',1);r.setdefault('content_sha256','synthetic-hash')
    before=deepcopy(d);states={u['unit_id']:{'card':cards.validate_reply(reply(u),u),
        'actual_attempt_ref':'synthetic-attempt','actual_model':'synthetic-model'}}
    check={'status':'not_supported','snapshot_ref':d['snapshot_ref'],
        'measurement_ref':{'id':r['measurement_id'],'version':r['revision'],'content_sha256':r['content_sha256']},
        'source_recheck_ref':{'id':'synthetic-owner-receipt'}}
    report=cards.final_report(d,s,{'id':'synthetic-kb'},[u],states,owner_rechecks=[check]);card=report['cards'][0]
    assert card['coverage']['frozen_record_count']==card['coverage']['owner_excluded_count']==1
    assert not card['sections']['found'] and card['suppressed_examples'] and d==before
    check['measurement_ref']['content_sha256']='other'
    assert cards.final_report(d,s,{'id':'synthetic-kb'},[u],states,owner_rechecks=[check])['cards'][0]['coverage']['owner_excluded_count']==0


def test_wrong_top_level_protocol_not_silently_accepted():
    _,_,u=example()
    with pytest.raises(DomainError):cards.validate_reply({'units':[]},u)


def test_local_repair_keeps_good_entries_and_sends_only_relevant_material():
    d,s,u=example();_,b=cards.model_input(u,d,s)
    r=explanation_wire(reply(u),b)
    r['comparison']=[{'text':'需要修正这个引用。','measurement_ids':['M999'],'evidence_ids':[],'claim_ids':[]}]
    initial=cards.validate_reply(r,u,b)
    packed,slots=cards.repair_input(r,initial,u,d,s,b)
    body=cards.unpack_materials(packed)
    assert len(slots)==1 and len(body['record_index'])==1
    good=deepcopy(r['found'])
    fixed={'repairs':[{'slot':slots[0]['slot'],'entry':r['found'][0]}]}
    updated,card=cards.apply_repairs(r,fixed,slots,u,b)
    assert updated['found']==good and len(card['sections']['comparison'])==1
    assert not card['validation_issues'] and r['comparison'][0]['measurement_ids']==['M999']
    with pytest.raises(DomainError):cards.apply_repairs(r,{'repairs':[{'slot':'R999','entry':r['found'][0]}]},slots,u,b)


def test_one_failed_repair_keeps_other_repairs_and_previously_valid_sections():
    d,s,u=example();_,b=cards.model_input(u,d,s)
    original=explanation_wire(reply(u),b)
    bad={'text':'SYNTHETIC invalid reference','measurement_ids':['M999'],'evidence_ids':[],'claim_ids':[]}
    original['comparison']=[deepcopy(bad)];original['limitations']=[deepcopy(bad)]
    card=cards.validate_reply(original,u,b)
    _,slots=cards.repair_input(original,card,u,d,s,b)
    fixed={'repairs':[{'slot':slots[0]['slot'],'entry':bad},
                     {'slot':slots[1]['slot'],'entry':original['found'][0]}]}
    updated,result=cards.apply_repairs(original,fixed,slots,u,b)
    assert updated['found']==original['found'] and result['sections']['found']
    assert len(result['sections']['limitations'])==1 and not result['sections']['comparison']
    assert len(result['validation_issues'])==1 and len(result['local_repair_diagnostics'])==1


def test_initial_capacity_groups_cover_all_sources_and_final_synthesis_uses_notes(monkeypatch):
    from astroquery_ai.science.property_insight_generation import plan,synthesis_input
    from astroquery_ai.runtime.calls import input_upper_bound
    from astroquery_ai.runtime.codec import canonical
    d,s,u=example()
    u['measurements'][0]['source_evidence'][0]['raw_text']='SYNTHETIC source A context '*700
    second=deepcopy(u['measurements'][0]);second['measurement_id']='another'
    second['source']['source_id']='another-paper'
    second['source_evidence']=[{'evidence_id':'another-evidence','raw_text':'SYNTHETIC different source B '*700,'locator':{'page':4}}]
    u['measurements'].append(second)
    d['measurements'].append({**deepcopy(d['measurements'][0]),'measurement_id':'another'})
    def size(unit):
        body,_=cards.model_input(unit,d,s)
        return input_upper_bound([{'role':'user','content':canonical(body).decode()}])
    from astroquery_ai.science.author_insights import unit
    individual=max(size(unit(d,u['property_id'],[r],u['claims'])) for r in u['measurements'])
    whole=size(u)
    assert whole>individual
    monkeypatch.setattr(cards,'INPUT_LIMIT',(individual+whole)//2)
    groups,needs_synthesis=plan(u,d,s)
    assert needs_synthesis and len(groups)==2
    assert {r['measurement_id'] for g in groups for r in g['unit']['measurements']}=={r['measurement_id'] for r in u['measurements']}
    # Full originals are available to source groups; final synthesis retains
    # the complete scientific row index and notes, without pasting them back.
    packed,_=synthesis_input(u,d,s,[]);body=cards.unpack_materials(packed)
    assert len(body['record_index'])==2 and all('raw_text' not in e for e in body['original_materials'])
