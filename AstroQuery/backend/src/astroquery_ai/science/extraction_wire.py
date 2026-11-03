"""Wire-only references and literal source copying; no scientific admission."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from .model_bindings import labels,binding_ref,map_fields

VERSION='extraction-labels-2'


def extraction_bindings(spec,*,artifact=None,rows=()):
    return binding_ref({'P':labels([b['property_id'] for b in spec['properties']],'P'),
        'R':{f'R{i+1}':row for i,row in enumerate(rows)}},
        context={'spec_hash':spec.get('spec_hash'),'artifact':artifact})


def extraction_wire(prompt,bindings,*,paper=False):
    value=map_fields(deepcopy(prompt),{'property_id':bindings['groups']['P'],
        'property_ids':bindings['groups']['P'],'row':bindings['groups']['R'],
        'row_index':bindings['groups']['R']})
    target=value.get('target',{})
    for key in ('target_id','evidence_id','retrieved_at','content_sha256','raw_type_fields'):
        target.pop(key,None)
    schema=value.get('schema',{}).get('$defs',{}).get('MeasurementProposal',{})
    properties=schema.get('properties',{})
    if paper:
        for key in ('row','column','catalog_quantity_evidence','catalog_field_roles','catalog_review_issue','quantity_match'):
            properties.pop(key,None)
        schema['required']=[k for k in schema.get('required',[]) if k not in {'row','column','source_quote'}]
        properties['source_blocks']={'type':'array','items':{'type':'string'},'maxItems':6}
        value['native_copy_rule']='For a native excerpt select source_blocks from the supplied page block IDs instead of copying source_quote; if local_admission.role_evidence already selects those core-page blocks, the server reuses them without a duplicate source_blocks list. Still transcribe the main value/individual errors and interpret subject, quantity, unit, role and context. On scans or missing blocks, source_quote is necessary transcription and remains unverified until page verification. Do not use context-only blocks as new measurements.'
    else:
        schema['required']=[k for k in schema.get('required',[]) if k not in {'value','raw_value','source_quote','unit'}]
        properties['native_cell']={'type':'boolean'}
        properties['row']={'type':'string','enum':list(bindings['groups']['R'])}
        value['native_copy_rule']='Use supplied R row and real column names. For a plain finite scalar numeric POINT in its stated native coordinate (including a source-native log coefficient), set native_cell=true and omit value/raw_value/source_quote; the server copies the original coefficient unchanged. YOU must establish native representation from actual definitions, not the column name. This is no logarithm or other calculation. Omit unit only when the column declares it. Preserve subject/quantity/role, independent errors, source quality and context. Composite strings, limits and uncertain encoding require explicit interpretation. Never convert to a target coordinate.'
    return value


def deduplicate_context(instruction):
    """No text cutoff: repeated native context is an explicit exact reference."""
    value=deepcopy(instruction)
    seen={}
    for key in ('page_evidence','context_fragments','document_frame'):
        for block in value.get(key,[]):
            text=block.get('text')
            if text is None:continue
            identity=(block.get('page'),text)
            if identity in seen:
                block.pop('text',None);block['text_ref']=seen[identity]
            else:seen[identity]=block['block_id']
    value['native_reference_rule']='A text_ref is exactly the complete native text at the supplied block_id on the SAME physical page, not omitted evidence. Its original page and CORE/CONTEXT scope still apply. Select actual block IDs; never infer cross-subject ownership from repeated text.'
    return value


def expand_extraction(response,bindings,*,rows=None,columns=(),blocks=()):
    value=map_fields(response,{'property_id':bindings['groups']['P'],
        'property_ids':bindings['groups']['P'],'row':bindings['groups']['R']},expand=True,strict=False)
    if not isinstance(value,dict):return value
    by_block={b['block_id']:b for b in blocks}
    fields={c['name']:c for c in columns}
    for proposal in value.get('results',[]):
        if not isinstance(proposal,dict):continue
        if rows is None:
            proposal.setdefault('row',None);proposal.setdefault('column',None)
            selected=proposal.pop('source_blocks',None)
            if selected is None and 'source_quote' not in proposal:
                selected=list(dict.fromkeys(k for anchor in (proposal.get('local_admission') or {}).get('role_evidence',[])
                    if isinstance(anchor,dict) and anchor.get('page')==proposal.get('page')
                    for k in anchor.get('block_ids',[]))) or None
            if selected is not None:
                if (isinstance(selected,list) and selected and len(selected)<=6
                    and all(isinstance(k,str) and k in by_block for k in selected)
                    and all(by_block[k]['page']==proposal.get('page') for k in selected)):
                    proposal['source_quote']='\n'.join(by_block[k]['text'] for k in selected)
                else:
                    # Invalid references remain an item-level schema failure.
                    proposal.pop('source_quote',None)
        elif proposal.pop('native_cell',False) or 'value' not in proposal or 'raw_value' not in proposal:
            row,column=proposal.get('row'),proposal.get('column')
            if type(row) is not int or row not in rows or column not in fields:continue
            field=fields[column];literal=rows[row].get(column)
            if (proposal.get('representation') not in {'linear','log10','ln','magnitude'} or proposal.get('limit')!='none'
                or not isinstance(literal,str) or not literal.strip()
                or field.get('datatype') in {'floatComplex','doubleComplex'}
                or (field.get('datatype') not in {'char','unicodeChar'} and str(field.get('arraysize') or '1')!='1')
                or (field.get('null') is not None and literal.strip()==field['null'])):continue
            try:number=Decimal(literal.strip())
            except InvalidOperation:continue
            if not number.is_finite():continue
            proposal['value']={'kind':'real','value':literal.strip()}
            proposal['raw_value']=literal
            proposal['source_quote']=''  # full immutable row is bound downstream
            if 'unit' not in proposal:proposal['unit']=field.get('unit_text',field.get('unit'))
    return value


def unified_paper_extraction(response,bindings,*,blocks,core_pages):
    """Bind original text for an unreviewed candidate, not an admission claim.

    A physical CORE page is already an evidence location. If no finer locator
    was supplied, keep its actual visible native excerpt for the independent
    quality reader. Never substitute CONTEXT pages, invented blocks, or text on
    a scan. Optional first-reader opinions remain paid raw history/navigation;
    they cannot require an entire second admission verdict before quality.
    """
    raw=deepcopy(response);navigation=[];by_id={b['block_id']:b for b in blocks}
    if not isinstance(raw,dict) or not isinstance(raw.get('results'),list):
        return expand_extraction(raw,bindings,blocks=blocks),navigation
    for index,item in enumerate(raw['results']):
        if not isinstance(item,dict):continue
        annotations={k:item.pop(k) for k in ('local_admission','source_quality') if item.get(k) is not None}
        refs=[]
        def visit(value):
            if isinstance(value,dict):
                for key in value.get('block_ids',[]) if isinstance(value.get('block_ids'),list) else []:
                    if isinstance(key,str) and key in by_id and by_id[key]['page']==value.get('page') and key not in refs:refs.append(key)
                for child in value.values():visit(child)
            elif isinstance(value,list):
                for child in value:visit(child)
        visit(annotations)
        quality=annotations.get('source_quality')
        if isinstance(quality,dict):
            for key in quality.get('raw_info',[]) if isinstance(quality.get('raw_info'),list) else []:
                if isinstance(key,str) and key in by_id and key not in refs:refs.append(key)
        if annotations:
            navigation.append({'proposal_index':index,'raw_annotations':annotations,
                               'blocks':[by_id[k] for k in refs]})
        page=item.get('page')
        if 'source_quote' not in item and 'source_blocks' not in item and type(page) is int and page in core_pages:
            actual=[b['text'] for b in blocks if b['page']==page and isinstance(b.get('text'),str) and b['text'].strip()]
            if actual:item['source_quote']='\n'.join(actual)
    return expand_extraction(raw,bindings,blocks=blocks),navigation
