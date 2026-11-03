"""Synthetic compiler/branch/reference counterexamples; not new science data."""
import asyncio
from copy import deepcopy
from itertools import product
from hashlib import sha256
from types import SimpleNamespace
import pytest
from astroquery_ai.registry.assembly import finite_support
from astroquery_ai.registry.compiler import matches
from astroquery_ai.registry.candidate import CandidateRegistry
from astroquery_ai.registry.amendments import checked_reference_alignments
from astroquery_ai.runtime.codec import canonical,content_hash,digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.workflow.scientific_conditions_service import ScientificConditionsMixin


def rule(number,when,profile='profile-one'):
    return dict(rule_id=str(number),version=1,kind='include',when=when,
        subject_class_id='synthetic-whole',definition_ref={'id':'synthetic-value','version':1,'content_sha256':'d'*64},
        profile_ref={'id':profile,'version':1,'content_sha256':digest(profile)})


def evaluate(table,root,types):
    nodes={n['id']:n for n in table['nodes']}
    while root not in (0,1):
        n=nodes[root];root=n['high'] if table['variables'][n['variable_index']] in types else n['low']
    return bool(root)


def test_reduced_partitions_agree_with_independent_ast_on_every_small_assignment():
    rules=[rule(1,{'all_of':[{'otype':'A'},{'not':{'otype':'B'}}]}),
           rule(2,{'any_of':[{'otype':'C'},{'all_of':[{'otype':'D'},{'otype':'E'}]}]}),
           rule(3,{'all_of':[{'otype':'B'},{'subject_class':'synthetic-whole'}]},'profile-two')]
    table=finite_support(rules)['tables'][0]
    for flags in product((False,True),repeat=5):
        types={t for t,on in zip('ABCDE',flags) if on}
        expected={digest(r['profile_ref']) for r in rules if matches(r['when'],types,'synthetic-whole')}
        chosen=[p for p in table['partitions'] if evaluate(table,p['root'],types)]
        assert len(chosen)==1 and {digest(p) for p in chosen[0]['candidate_profile_refs']}==expected
        assert chosen[0]['outcome']==('no_active' if not expected else 'resolved' if len(expected)==1 else 'conflict')


def test_39_type_shared_quantity_is_compact_without_changing_conflicts():
    rules=[rule(n,{'otype':'T'+str(n)}) for n in range(39)]
    table=finite_support(rules)['tables'][0]
    assert len(table['partitions'])==2 and len(table['nodes'])<2000
    for types in (set(),{'T0'},{'T38'},{'T1','T4'},set(table['variables'])):
        chosen=[p for p in table['partitions'] if evaluate(table,p['root'],types)]
        assert len(chosen)==1 and chosen[0]['outcome']==('resolved' if types else 'no_active')


def test_parent_stratum_and_negative_type_are_evaluated_together_from_source_ast():
    r=rule(1,{'all_of':[{'otype':'parent'},{'otype':'confirmed-stratum'},{'not':{'otype':'excluded'}}]})
    d={'property_id':r['definition_ref']['id'],'definition_version':1,'content_sha256':r['definition_ref']['content_sha256']}
    p={'profile_id':r['profile_ref']['id'],'version':1,'content_sha256':r['profile_ref']['content_sha256']}
    candidate={'report':{'manifest_content_sha256':'a'*64},'data':{'definitions':[d],'output_profiles':[p],
        'unapproved_aggregate_composition_and_rules':{'rules':[r]},'build_only_symbolic_support':finite_support([r])}}
    reader=CandidateRegistry()
    assert not reader.select_context(candidate,accepted_otypes=['parent'],subject_class_id='synthetic-whole')['bindings']
    assert reader.select_context(candidate,accepted_otypes=['parent','confirmed-stratum'],subject_class_id='synthetic-whole')['bindings']
    assert not reader.select_context(candidate,accepted_otypes=['parent','confirmed-stratum','excluded'],subject_class_id='synthetic-whole')['bindings']


def test_parallel_definition_versions_become_local_gap_without_arbitrary_selection():
    r=rule(1,{'otype':'A'});other=deepcopy(r);other['rule_id']='2';other['definition_ref']={**r['definition_ref'],'version':2,'content_sha256':'e'*64}
    ds=[{'property_id':x['definition_ref']['id'],'definition_version':x['definition_ref']['version'],
         'content_sha256':x['definition_ref']['content_sha256']} for x in (r,other)]
    p={'profile_id':r['profile_ref']['id'],'version':1,'content_sha256':r['profile_ref']['content_sha256']}
    candidate={'report':{'manifest_content_sha256':'a'*64},'data':{'definitions':ds,'output_profiles':[p],
        'unapproved_aggregate_composition_and_rules':{'rules':[r,other]},'build_only_symbolic_support':finite_support([r,other])}}
    support=CandidateRegistry().select_context(candidate,accepted_otypes=['A'],subject_class_id='synthetic-whole')
    assert support['bindings']==[] and support['gaps'][0]['reason']=='reviewed_definition_versions_conflict'


def test_alternatives_use_one_complete_permission_not_cross_branch_predicates():
    first={'record_id':'scope-one','version':1,'content_sha256':'1'*64}
    second={'record_id':'scope-two','version':1,'content_sha256':'2'*64}
    refs=[{'id':r['record_id'],'version':1,'content_sha256':r['content_sha256']} for r in (first,second)]
    release={'science':{'records':{},'by_ref':{}}}
    from astroquery_ai.registry.amendments import reference_key
    release['science']['by_ref']={reference_key(ref):r for ref,r in zip(refs,(first,second))}
    binding={'property_id':'synthetic-value','science_branches':[{'otypes':['A'],'science_ref':refs[0]},
                                                               {'otypes':['B'],'science_ref':refs[1]}]}
    class Consumer(ScientificConditionsMixin):
        async def _scientific_permission_record(self,*args):
            science=args[-1]
            self.seen.append(science['record_id'])
            return ({'allowed':science is second,'reason':'complete-proof' if science is second else 'missing-own-context'},
                    {'science_record_hash':science['content_sha256']})
    # Summary content is relevant only to the supplied record; these no-op
    # fields model a tiny synthetic independent condition set.
    for r in (first,second):r.update(required_conditions=[],context_contracts=[],operations=[])
    consumer=Consumer();consumer.seen=[]
    permission,semantics=asyncio.run(consumer.scientific_permission({}, {'target':{'primary_otype':'A'}},
        binding,{}, {},release,None))
    assert consumer.seen==['scope-one','scope-two']
    assert permission['allowed'] and permission['science_record_ref']==refs[1]
    assert semantics['science_record_hash']=='2'*64
    assert [e['allowed'] for e in permission['condition_branch_evaluations']]==[False,True]


def test_review_only_reference_alignment_cannot_change_units(tmp_path):
    old={'profile_id':'synthetic-profile','version':'2','unit':'m','review_ref':{'review_id':'pending','version':'1'}}
    old['content_sha256']=content_hash(old)
    new={**old,'unit':'km','review_ref':{'review_id':'approved','version':'1'}}
    new['content_sha256']=content_hash(new)
    files=[];pins=[]
    for name,record in [('old.json',old),('new.json',new)]:
        raw=canonical([record]);(tmp_path/name).write_bytes(raw)
        pin={'path':name,'file_sha256':sha256(raw).hexdigest()};pins.append(pin);files.append(pin)
    ref=lambda r:{'id':r['profile_id'],'version':r['version'],'content_sha256':r['content_sha256']}
    amendment={'schema_version':'ConsumerScienceAmendment/1','authorized_by':'user','decision_text':'SYNTHETIC metadata-only test',
        'revision':1,'amendment_id':'synthetic','changes':[], 'reference_alignments':[{'old_ref':ref(old),'new_ref':ref(new),
            'old_record_pin':pins[0],'new_record_pin':pins[1]}]}
    amendment['content_sha256']=content_hash(amendment)
    candidate={'manifest':{'content_files':files},'data':{'output_profiles':[new],'reviews':[]}}
    with pytest.raises(DomainError) as error:checked_reference_alignments(tmp_path,candidate,amendment)
    assert error.value.code=='REFERENCE_ALIGNMENT_SCIENCE_CHANGED'
