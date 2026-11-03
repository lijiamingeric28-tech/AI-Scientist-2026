"""Synthetic interface cases only; no new scientific type qualification."""
from copy import deepcopy
import pytest
from astroquery_ai.registry.consumer import consumer_support, reviewed_compositions
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError


def composition():
    payload = {'otypes': ['SYNTHETIC-A', 'SYNTHETIC-B'], 'subject_class_id': 'synthetic-whole',
        'bindings': [{'definition_ref': {'id': 'synthetic-length', 'version': 1, 'content_sha256': 'a'*64},
                      'profile_ref': {'id': 'synthetic-profile', 'version': 1, 'content_sha256': 'b'*64}}]}
    return {**payload, 'review': {'decision': 'approved', 'reviewed_payload_sha256': digest(payload),
                                'checks': {'conflicts': 'passed'}, 'reviewer': 'synthetic-test'}}


def test_candidate_multiple_types_require_exact_explicit_review_not_auto_union():
    a, b, subject = 'SYNTHETIC-A', 'SYNTHETIC-B', 'synthetic-whole'
    release = {'context_bindings': {(a, subject): [{'property_id': 'synthetic-a'}],
                                    (b, subject): [{'property_id': 'synthetic-b'}]}}
    with pytest.raises(DomainError):
        consumer_support(release, [a, b], subject)
    record = composition()
    key = next(iter(reviewed_compositions({'reviewed_type_compositions': [record]}, set(release['context_bindings']))))
    release['composition_bindings'] = {key: [{'property_id': 'synthetic-reviewed-length'}]}
    assert [x['property_id'] for x in consumer_support(release, [b, 'unreviewed-label', a], subject)['bindings']] == ['synthetic-reviewed-length']
    assert consumer_support(release, [a], subject)['bindings'] == [{'property_id': 'synthetic-a'}]
    broken = deepcopy(record); broken['bindings'][0]['profile_ref']['version'] = 2
    with pytest.raises(DomainError):
        reviewed_compositions({'reviewed_type_compositions': [broken]}, set(release['context_bindings']))


def test_candidate_review_still_runs_existing_profile_conflict_compiler():
    record = composition()
    other = deepcopy(record['bindings'][0]); other['profile_ref']['id'] = 'synthetic-conflicting'
    record['bindings'].append(other)
    record['review']['reviewed_payload_sha256'] = digest({k: record[k] for k in ('otypes','subject_class_id','bindings')})
    with pytest.raises(DomainError) as caught:
        reviewed_compositions({'reviewed_type_compositions': [record]}, {('SYNTHETIC-A', 'synthetic-whole'), ('SYNTHETIC-B', 'synthetic-whole')})
    assert caught.value.code == 'UNRESOLVED_COMPOSITION'


def test_candidate_consumer_builds_exact_reviewed_composition_with_generic_types(tmp_path, monkeypatch):
    """Structural integration only: source signature validation is mocked here;
    the existing import tests cover it separately. Never a science receipt.
    """
    import astroquery_ai.registry.consumer as module
    from tests.rebuild.registry_fixture import make_release
    from astroquery_ai.runtime.codec import content_hash
    data=make_release(tmp_path/'SYNTHETIC native package')
    definition=data['definitions'][0];profile=data['output-profiles'][0];subject=definition['subject_class_id']
    def ref(obj,idkey,versionkey='version'):
        return {'id':obj[idkey],'version':obj[versionkey],'content_sha256':obj['content_sha256']}
    dref=ref(definition,'property_id','definition_version');pref=ref(profile,'profile_id')
    payload={'otypes':['SYNTHETIC-A','SYNTHETIC-B'],'subject_class_id':subject,
             'bindings':[{'definition_ref':dref,'profile_ref':pref}]}
    composition_record={**payload,'review':{'decision':'approved','reviewed_payload_sha256':digest(payload),
        'checks':{'synthetic_binding':'passed'},'reviewer':'synthetic-fixture'}}
    science_record={'record_id':'SYNTHETIC-science','version':1,'profile_ref':pref,'definition_ref':dref,
        'required_conditions':[],'context_contracts':[],'operations':[]}
    science_record['content_sha256']=content_hash(science_record)
    candidate={'report':{'manifest_file_sha256':'a'*64},'data':{
        'type_profiles':[{'otype':t,'subject_class_id':subject} for t in payload['otypes']],
        'unapproved_aggregate_composition_and_rules':{'rules':[
            {'rule_id':'SYNTHETIC-rule','version':1,'content_sha256':'b'*64}]},
        **{new:data[old] for new,old in [('families','families'),('subject_classes','subject-classes'),
          ('object_scales','object-scales'),('evidence','evidence'),('reviews','reviews'),
          ('conversion_policies','conversion-policies')]}}}
    class Reader:
        def inspect(self,package):return deepcopy(candidate)
        def select_context(self,release,**kwargs):return kwargs
    class Projection:
        version='SYNTHETIC projection'
        def __init__(self,release):pass
        def support(self,selected):
            return {'gaps':[],'bindings':[{'property_id':definition['property_id'],'definition':definition,
                'output_profile':profile,'projection_receipt':{'synthetic':True,'source_definition_ref':dref},
                'source_binding':{'output_profile':pref,'definition':dref,'active_rule_refs':['SYNTHETIC-rule']}}]}
    monkeypatch.setattr(module,'CandidateRegistry',Reader)
    monkeypatch.setattr(module,'CandidateProjection',Projection)
    monkeypatch.setattr(module,'read_science_conditions',lambda *a,**k:{
        'config':{'reviewed_type_compositions':[composition_record]},
        'records':{definition['property_id']:science_record}})
    result=module.consume_candidate(tmp_path,tmp_path/'SYNTHETIC config',manifest_sha256='a'*64,config_sha256='c'*64)
    support=module.consumer_support(result,payload['otypes'],subject)
    assert len(support['bindings'])==1 and support['bindings'][0]['property_id']==definition['property_id']
    assert support['bindings'][0]['science_ref']['id']=='SYNTHETIC-science'
    assert result['manifest']['runtime_capabilities']=='separate_local_receipts_required'
    assert result['manifest']['source_candidate_flags_unchanged'] is True
