"""The experiment cannot waive fixed quantity identity or fabricate evidence."""
import pytest
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_literature_lab_content import context
from tests.support.literature.content_identity import checked


@pytest.mark.parametrize('match',['unknown','different'])
def test_fixed_identity_cannot_be_waived_by_exact_or_u(match):
    row={**context(),'status':'U','match_reason':'synthetic source',
         'identity_conditions':{'I1':{'match':match,'source_fact':'synthetic fact','blocks':['B1']}},
         'evidence':[{'blocks':['B1'],'role':'reported'}]}
    with pytest.raises(DomainError):
        checked(row,{1:'SYNTHETIC'},blocks={'B1':{'page':1,'text':'SYNTHETIC'}},requirements=[{'id':'I1'}])


def test_explicit_match_preserves_original_not_a_model_transcription():
    row={**context(),'status':'U','match_reason':'synthetic source',
         'identity_conditions':{'I1':{'match':'met','source_fact':'synthetic fact','blocks':['B1']}},
         'evidence':[{'blocks':['B1'],'role':'reported'}]}
    original='SYNTHETIC only: 5 +2 -1; optional confidence unknown'
    r=checked(row,{1:original},blocks={'B1':{'page':1,'text':original}},requirements=[{'id':'I1'}])
    assert r['evidence'][0]['quote']==original and r['formal_measurement'] is False
    row['identity_conditions']['I1']['blocks']=['unprovided']
    with pytest.raises(DomainError):
        checked(row,{1:original},blocks={'B1':{'page':1,'text':original}},requirements=[{'id':'I1'}])
