"""Literal scalar collection after model column interpretation and object binding.

This produces unreviewed candidates, never a scientific acceptance or a unit
conversion. Non-scalar/limit/flagged cells keep the existing interpretation route.
"""
from decimal import Decimal, InvalidOperation
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.science.measurements.contracts import MeasurementProposal,ConditionProposal
from astroquery_ai.science.catalog_transcription import native_cell_state,preserve_catalog_fields


def literal_proposal(row,index,columns,mapping,*,source_document=None):
    field=next((c for c in columns if c['name']==mapping['value_column']),None)
    if not field or mapping.get('quantity_match')!='exact':return None,'quantity_needs_interpretation'
    if native_cell_state(row,field['name'],columns)!='reported_token':return None,'missing'
    if field.get('datatype') in {'floatComplex','doubleComplex'} or (
        field.get('datatype') not in {'char','unicodeChar'} and str(field.get('arraysize') or '1')!='1'):
        return None,'non_scalar'
    native_representation=mapping.get('source_representation')
    if native_representation not in {'linear','log10','ln','magnitude'}:return None,'representation_needs_interpretation'
    if mapping.get('source_unit')!=field.get('unit_text'):return None,'unit_needs_interpretation'
    flags=[mapping.get('limit_column'),*mapping.get('quality_columns',[])]
    if any(n and native_cell_state(row,n,columns)=='reported_token' for n in flags):return None,'flag_needs_interpretation'
    raw=row.get(field['name'])
    if not isinstance(raw,str):return None,'non_literal'
    try:
        if not Decimal(raw.strip()).is_finite():return None,'non_finite'
    except InvalidOperation:return None,'composite_token'
    conditions=[ConditionProposal(key='source_field:'+name,value=row[name],state='known',raw_text=name+': '+str(row[name]))
        for name in mapping.get('context_columns',[]) if native_cell_state(row,name,columns)=='reported_token']
    proposal=MeasurementProposal(property_id=mapping['property_id'],value={'kind':'real','value':raw.strip()},
        raw_value=raw,unit=field.get('unit_text'),representation=native_representation,
        source_quote=canonical({'cells':row,'columns':columns}).decode(),page=None,row=index,column=field['name'],
        subject_role='target',result_role='reported_result',location_kind='catalog_cell',limit='none',
        errors=[],conditions=conditions,ambiguity=None,quantity_match='exact',source_quality=None)
    proposal,_=preserve_catalog_fields(proposal,row,{**mapping,'source_document':source_document,
        'provided_auxiliary_columns':{c['name'] for c in columns}},columns)
    return proposal,'literal_scalar'


async def collect_literal_rows(service,kwargs):
    from astroquery_ai.runtime.run_policy import consolidated
    from astroquery_ai.runtime.codec import digest,content_hash
    if not consolidated(kwargs['spec']):return None
    rows=kwargs['rows'];columns=kwargs['table']['columns'];job=kwargs['job'];tid=kwargs['tid']
    remainder=[];assembled=[];locations=[]
    with service.repo.read() as conn:
        plan_record=service.repo.object(conn,tid,'catalog_column_plan',job['job_id'])
        checked_bindings={}
        eligible=set()
        for index,ref in kwargs['binding_refs'].items():
            key=(ref['id'],ref['version'])
            if key not in checked_bindings:
                checked_bindings[key]=service.repo.object(conn,tid,'object_match',*key)
            proof=checked_bindings[key]
            # A matching name alone does not establish that every numeric
            # column measures that subject (e.g. a local calibration sequence).
            if (proof.get('schema_version')=='EvidencedTableSubjectBinding/1'
                and proof.get('source_declaration',{}).get('scope')=='single_target_observations'
                and proof.get('model_attempt_ref')):
                eligible.add(index)
    plan_ref={'id':job['job_id'],'version':plan_record.get('revision',1),'content_sha256':content_hash(plan_record)}
    def commit():
        if not assembled:return
        with service.repo.transaction() as conn:
            service.repo.validate_lease(conn,job)
            service.commit_candidates(conn,tid,assembled,job['job_id'])
            receipt={'method':'model_columns_program_literal_cells/1','quality_checked':False,
                'column_plan_ref':plan_ref,'artifact_sha256':kwargs['artifact']['sha256'],'locations':list(locations)}
            service.repo.put_object(conn,tid,'catalog_transcription_receipt','literal-'+digest(receipt),1,receipt)
        assembled.clear();locations.clear()
    for plan in kwargs['pending_plans']:
        for mapping in plan['properties']:
            pending=[]
            for index in kwargs['matched']:
                if index not in eligible:
                    pending.append(index)
                    continue
                proposal,state=literal_proposal(rows[index],index,columns,mapping,source_document=kwargs['table'].get('catalog_document'))
                if proposal is None:
                    if state!='missing':pending.append(index)
                    continue
                source_row=kwargs['actual']['source_row_numbers'][index] if kwargs['attachment'] else index
                proposal=proposal.model_copy(update={'row':source_row})
                # The normal assembler checks the actual target/table/artifact
                # binding before creating a pending-unified-quality candidate.
                result=service.extractor.assemble(spec=kwargs['spec'],source=kwargs['source'],artifact=kwargs['artifact'],
                    proposal=proposal,owner='M03',batch_id=job['job_id'],allowed_pages=[],matched_rows=[source_row],
                    object_binding_ref=kwargs['binding_refs'][index])
                assert result['state']=='review_candidate'
                assembled.append(result);locations.append({'row':source_row,'column':mapping['value_column'],'property_id':mapping['property_id']})
                kwargs['seen_rows'].add(digest(rows[index]))
                if len(assembled)>=64:commit()
            if pending:remainder.append((pending,{**plan,'properties':[mapping]}))
    commit()
    return remainder
