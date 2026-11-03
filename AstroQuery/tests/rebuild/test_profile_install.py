"""Qualification publication protocol, synthetic evidence only."""
from copy import deepcopy
import pytest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.tools.install_profile_qualification import install
from tests.rebuild.test_profile_scope import qualified_case


def test_install_copies_only_exact_qualification_proof_and_preserves_scope(tmp_path):
    target,_,_,_=qualified_case(tmp_path/'a')
    source,live,_,_=qualified_case(tmp_path/'b')
    with source.repository.transaction() as c:
        report,old=source.profile_authority.load(c,'M03')
        execution=report.pop('execution');report['schema_version']='ScientificProfileQualification/2'
        report['execution_profiles']=[execution,{**execution,'version':'synthetic-new'}]
        new=source.repository.put_object(c,old['task_id'],'profile_validation','new-proof',1,report)
        setting={'state':'validated','synthetic':True,'endpoint_identity':__import__('astroquery_ai.runtime.codec',fromlist=['digest']).digest(source.configuration.runtime['dashscope_base_url']),
                 'validation_ref':{**new,'task_id':old['task_id']}}
        c.execute("UPDATE settings SET payload=? WHERE key='profile:M03'",(canonical(setting),))
    result=install(target,source.repository.path,'M03')
    assert result['scientific_scope_unchanged'] and not result['imported_scientific_runs']
    with target.repository.read() as c:
        report,reference=target.profile_authority.load(c,'M03')
        assert len(report['execution_profiles'])==2 and reference==setting['validation_ref']
        assert not c.execute('SELECT 1 FROM tasks WHERE task_id=?',(live,)).fetchone()
        assert not c.execute('SELECT 1 FROM objects WHERE task_id=? AND kind NOT IN (?,?)',
            (old['task_id'],'profile_validation','validation')).fetchone()
    assert install(target,source.repository.path,'M03')['copied_evidence_refs']==[]
    with source.repository.transaction() as c:
        report=deepcopy(report);report['scope']['primary_otypes'].append('unapproved')
        ref=source.repository.put_object(c,old['task_id'],'profile_validation','new-proof',2,report)
        setting['validation_ref']={**ref,'task_id':old['task_id']}
        c.execute("UPDATE settings SET payload=? WHERE key='profile:M03'",(canonical(setting),))
    with pytest.raises(DomainError) as e:install(target,source.repository.path,'M03')
    assert e.value.code=='PROFILE_IMPORT_SCOPE'
