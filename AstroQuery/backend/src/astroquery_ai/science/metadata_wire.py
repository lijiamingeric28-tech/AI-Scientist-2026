"""Mechanical experimental metadata field binding; never a relevance judge."""
from copy import deepcopy
from astroquery_ai.runtime.errors import DomainError


def bind_metadata_row(raw,property_labels):
    if not isinstance(raw,dict):
        raise DomainError('LITERATURE_RELEVANCE_SCHEMA','候选判断必须是对象')
    row=deepcopy(raw);changes=[]
    for canonical,aliases in (('evidence',('evidence_labels','evidence_ids')),
                              ('reason',('relation_reason','relation'))):
        for alias in aliases:
            if alias not in row:continue
            if canonical in row and row[canonical]!=row[alias]:
                raise DomainError('LITERATURE_FIELD_CONFLICT','同义协议字段给出不一致内容',field=canonical,alias=alias)
            if canonical not in row:
                row[canonical]=row[alias]
                changes.append({'field':canonical,'source_field':alias,'basis':'equivalent_protocol_field'})
    if 'properties' not in row:
        if row.get('decision') in {'relevant','needs_fulltext'}:
            if len(property_labels)!=1:
                raise DomainError('LITERATURE_RELEVANCE_SCHEMA','多性质判断仍须明确选择性质')
            row['properties']=list(property_labels)
            changes.append({'field':'properties','basis':'single_frozen_requested_property','labels':list(property_labels)})
        elif row.get('decision') in {'unrelated','unassessable'}:
            row['properties']=[]
            changes.append({'field':'properties','basis':'no_positive_allocation'})
    return row,changes
