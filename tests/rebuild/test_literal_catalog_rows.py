import pytest
from astroquery_ai.science.catalog.literal_rows import literal_proposal

COLS=[{'name':'RV','datatype':'double','unit_text':'km/s','null':'NaN'},
      {'name':'e_RV','datatype':'double','unit_text':'km/s'},
      {'name':'BJD','datatype':'double','unit_text':'d'},
      {'name':'flag','datatype':'char','unit_text':None}]
PLAN={'value_column':'RV','property_id':'rv','quantity_match':'exact',
      'source_representation':'linear','source_unit':'km/s','error_columns':['e_RV'],'context_columns':['BJD']}

def test_literal_collection_preserves_zero_precision_errors_and_epoch_without_semantic_promotion():
    p,state=literal_proposal({'RV':'0.000','e_RV':'0.0050','BJD':'2450001.001'},1031,COLS,PLAN)
    assert state=='literal_scalar' and p.row==1031 and p.raw_value==p.value.value=='0.000'
    assert p.errors[0].raw_text=='0.0050' and p.errors[0].source_unit=='km/s'
    assert p.errors[0].interpretation_state=='unresolved' and p.errors[0].level_kind is None
    assert p.conditions[0].value=='2450001.001' and p.source_quality is None

@pytest.mark.parametrize('value,state',[('NaN','missing'),('','missing'),('12 ± 2','composite_token'),('Inf','non_finite')])
def test_missing_or_composite_cells_never_become_a_guessed_scalar(value,state):
    p,why=literal_proposal({'RV':value},0,COLS,PLAN)
    assert p is None and why==state

@pytest.mark.parametrize('change',[
    {'quantity_match':'unresolved'}, {'source_unit':'m/s'}, {'source_representation':None},
    {'limit_column':'flag'}, {'quality_columns':['flag']},
])
def test_uncertain_science_or_row_flags_keep_existing_model_route(change):
    p,_=literal_proposal({'RV':'12.30','flag':'U'},0,COLS,{**PLAN,**change})
    assert p is None

def test_every_plain_observation_survives_more_than_one_thousand_rows():
    result=[literal_proposal({'RV':str(i/100),'e_RV':'0.003','BJD':str(2450000+i/2)},i,COLS,PLAN)[0] for i in range(1032)]
    assert all(result) and len({p.row for p in result})==1032
    assert result[-1].raw_value=='10.31' and result[-1].conditions[0].value=='2450515.5'
