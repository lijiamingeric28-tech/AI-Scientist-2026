from copy import deepcopy

from astroquery_ai.query.property_labels import ground_registered_labels


def test_literal_full_property_name_does_not_become_two_fake_filter_questions():
    text = 'SYNTHETIC_AQ 的 SYNTHETIC 来源 Type 分类文本，且只取大于5的值'
    label = 'SYNTHETIC 来源 Type 分类文本'
    def span(fragment):
        start = text.index(fragment)
        return {'text': fragment, 'start': start, 'end': start + len(fragment)}
    parsed = {'property_operation': 'replace', 'properties': [span('Type')],
        'conditions': [{**span('SYNTHETIC 来源'), 'kind': 'scope'}, {**span('分类文本'), 'kind': 'filter'},
                       {**span('只取大于5的值'), 'kind': 'filter'}], 'unknown_fragments': []}
    bindings = [{'property_id': 'SYNTHETIC_type', 'definition': {'name_cn': label, 'name_en': 'SYNTHETIC type text', 'aliases': ['Type']}}]
    original = deepcopy(parsed)
    grounded, repairs = ground_registered_labels(parsed, text, bindings)
    assert grounded['properties'] == [span(label)]
    assert [c['text'] for c in grounded['conditions']] == ['只取大于5的值']
    assert repairs[0]['property_id'] == 'SYNTHETIC_type'
    assert parsed == original


def test_a_different_occurrence_or_ambiguous_label_cannot_expand_the_request():
    text = '不要SYNTHETIC 来源 Type 分类文本，只查Type'
    start = text.rindex('Type')
    parsed = {'property_operation': 'replace', 'properties': [{'text': 'Type', 'start': start, 'end': start + 4}],
        'conditions': [], 'unknown_fragments': []}
    binding = {'property_id': 'SYNTHETIC type', 'definition': {'name_cn': 'SYNTHETIC 来源 Type 分类文本', 'name_en': '', 'aliases': ['Type']}}
    grounded, repairs = ground_registered_labels(parsed, text, [binding])
    assert grounded == parsed and not repairs
    earlier = deepcopy(parsed)
    earlier['properties'][0].update(start=text.index('Type'), end=text.index('Type') + 4)
    other = {**binding, 'property_id': 'SYNTHETIC ambiguous type'}
    assert ground_registered_labels(earlier, text, [binding, other]) == (earlier, [])
