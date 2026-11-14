from astroquery_ai.query.selection import resolve_explicit_selection


def test_explicit_catalog_selection_replaces_unmatched_wording_but_not_filters():
    draft={'property_requests':[{'text':'SYNTHETIC alias','resolution':'unsupported'}],
        'issues':[{'kind':'unsupported_property','status':'open','description':'SYNTHETIC alias'},
                  {'kind':'unsupported_filter','status':'open','description':'SYNTHETIC filter'}]}
    resolve_explicit_selection(draft,['SYNTHETIC offered ID'],'SYNTHETIC operation')
    assert draft['issues'][0]['status']=='resolved'
    assert draft['issues'][1]['status']=='open'
    assert draft['property_requests'][0]['text']=='SYNTHETIC alias'
    assert draft['property_requests'][0]['resolution']=='superseded_by_explicit_selection'
    assert draft['property_requests'][0]['selected_property_ids']==['SYNTHETIC offered ID']
