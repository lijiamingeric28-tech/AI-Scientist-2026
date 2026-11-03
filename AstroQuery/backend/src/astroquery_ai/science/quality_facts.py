"""Reuse exact unified quality facts, without granting a new science rule."""
from .scientific_conditions import semantic_keys,source_span_aliases


def reusable_response(science,record,interpretation,spans):
    quality=interpretation.get('quality_verification') or {}
    if quality.get('state')!='supported' or not quality.get('model_attempt_ref'):return None
    check=quality.get('assessment') or {};assessment=check.get('assessment',check)
    anchors=[k for k,v in source_span_aliases(spans).items() if v.get('origin')!='verified_repository_binding']
    if not anchors:return None
    same=(assessment.get('subject')=='target' and (
        assessment.get('quantity_match')=='exact' or assessment.get('quantity_relation')=='same'))
    # These are the existing predicate dialects for the same independently
    # evidenced facts. Arbitrary source/operation predicates are never assumed.
    known={}
    if same:
        for key in ('source_subject_quantity','source_subject_quantity_evidence_verified'):
            known[key]=True
    exact_unit=assessment.get('unit_match')=='exact'
    exact_native=check.get('native_representation')==record['representation'] and exact_unit
    if same and exact_native and check.get('value_match')=='exact':
        for key in ('native_unit_representation','source_native_main_coordinate_evidenced','source_main_state_interpreted'):
            known[key]=True
    checks=[{'key':key,'state':'supported','anchors':anchors,'reason':'reused_unified_quality_exact_original_verdict',
             'quality_attempt_ref':quality['model_attempt_ref']} for key in semantic_keys(science) if known.get(key)]
    uncertainty=[]
    for component in record['uncertainty']['components']:
        parsed=component['interpretation_state']=='parsed' and check.get('errors_match')=='exact'
        uncertainty.append({'component_id':component['component_id'],'disposition':'eligible' if parsed else 'retain_unknown',
            'interpretation_needed':False,'anchors':anchors,'reason':'same_verified_raw_component; optional confidence/role remains as reported'})
    return {'checks':checks,'contexts':[],'uncertainty':uncertainty,
        'comparison_prerequisites':{'state':'unresolved','required_context_keys':[],
            'reason':'handled_by_archive_and_review; not_a_main_conversion_gate'},
        'unified_quality_ref':{'candidate_ref':quality['candidate_ref'],'model_attempt_ref':quality['model_attempt_ref']}}
