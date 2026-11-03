"""Offline literature fixtures used by the retrieval regression suite."""
from astroquery_ai.runtime.errors import DomainError


def checked(response,pages,*,visual=False,blocks=None):
    if not isinstance(response,dict) or response.get('status') not in {'U','F','X','Q'}:
        raise DomainError('LAB_CONTENT_SCHEMA','Use the four material statuses')
    if not isinstance(response.get('match_reason'),str) or not response['match_reason'].strip():
        raise DomainError('LAB_CONTENT_SCHEMA','Explain actual scope, not an expected answer')
    identity=response.get('source_identity')
    if (not isinstance(identity,dict) or any(not isinstance(identity.get(k),str) or not identity[k].strip()
            for k in ('subject','quantity','estimator','coordinate','reference_context','role'))
            or identity['role'] not in {'reported_result','adopted_result','fixed_assumption','method_only','unknown'}
            or response.get('scope_match') not in {'exact','related','different','insufficient'}):
        raise DomainError('LAB_CONTENT_SCHEMA','First state actual source identity and structured scope match')
    if response['status']=='U' and (response['scope_match']!='exact' or identity['role'] not in {'reported_result','adopted_result'}):
        raise DomainError('LAB_CONTENT_SCHEMA','U conflicts with the structured scope or result-role conclusion')
    checks=response.get('boundary_checks')
    axes={'subject','quantity','estimator','native_representation','component_or_correction','reference','aperture'}
    if not isinstance(checks,dict) or set(checks)!=axes:
        raise DomainError('LAB_CONTENT_SCHEMA','Compare the seven actual source/request boundary axes')
    for axis,row in checks.items():
        if (not isinstance(row,dict) or type(row.get('required')) is not bool
                or row.get('match') not in {'same','different','unknown','not_applicable'}
                or any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('requested','source'))
                or not isinstance(row.get('evidence'),list)
                or any(label not in (blocks or {}) for label in row['evidence'])):
            raise DomainError('LAB_CONTENT_SCHEMA','Bind short actual conditions to supplied evidence')
        if axis in {'subject','quantity','native_representation'} and not row['required']:
            raise DomainError('LAB_CONTENT_SCHEMA','Subject, quantity and native representation are necessary')
    unsatisfied=any(r['required'] and r['match']!='same' for r in checks.values())
    contrary=any(r['required'] and r['match']=='different' for r in checks.values())
    if response['status']=='U' and (unsatisfied or contrary):
        raise DomainError('LAB_CONTENT_SCHEMA','U contradicts a required condition or an explicit difference')
    if response['scope_match']=='exact' and (unsatisfied or contrary):
        raise DomainError('LAB_CONTENT_SCHEMA','Exact scope conflicts with the structured boundary checks')
    evidence=response.get('evidence',[])
    if not isinstance(evidence,list) or len(evidence)>12:
        raise DomainError('LAB_CONTENT_SCHEMA','Need a bounded evidence list')
    bound=[]
    for row in evidence:
        if isinstance(row,dict) and isinstance(row.get('blocks'),list):
            labels=row['blocks']
            if not labels or len(labels)>12 or any(label not in (blocks or {}) for label in labels):
                raise DomainError('LAB_CONTENT_EVIDENCE','Select actual supplied B labels')
            for label in dict.fromkeys(labels):
                original=blocks[label]
                bound.append({**original,'block':label,'quote':original['text'],
                              'role':row.get('role','unknown'),'binding':'native_block_verified'})
            continue
        if not isinstance(row,dict) or type(row.get('page')) is not int or row['page'] not in pages:
            raise DomainError('LAB_CONTENT_EVIDENCE','Select an actually supplied physical page')
        quote=row.get('quote')
        if not isinstance(quote,str) or not quote.strip() or len(quote)>2400:
            raise DomainError('LAB_CONTENT_EVIDENCE','Use a short actual excerpt')
        text_ok=' '.join(quote.split()) in ' '.join(pages[row['page']].split())
        if not visual and not text_ok:
            raise DomainError('LAB_CONTENT_EVIDENCE','Excerpt is not in the supplied original page; copy text, not paraphrase')
        bound.append({**row,'binding':'native_text_verified' if text_ok else 'actual_image_page_executor_check_required'})
    if response['status']=='U' and not bound:
        raise DomainError('LAB_CONTENT_EVIDENCE','U requires actual evidence')
    return {**response,'evidence':bound,'formal_measurement':False}
