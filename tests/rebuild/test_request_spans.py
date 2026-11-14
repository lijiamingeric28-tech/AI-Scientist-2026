import pytest
from astroquery_ai.query.spans import ground_spans
from astroquery_ai.runtime.errors import DomainError


def parsed(text, start=0, end=1):
    return dict(targets=[dict(text=text, start=start, end=end)], properties=[], conditions=[], unknown_fragments=[])


def test_unique_literal_with_wrong_model_offsets_is_grounded_without_model_retry():
    original = parsed('PSR B0329+54')
    grounded, repairs = ground_spans('查询 PSR B0329+54 的 DM', original)
    assert grounded['targets'][0] == dict(text='PSR B0329+54', start=3, end=15)
    assert original['targets'][0]['start'] == 0 and repairs[0]['basis'] == 'unique_exact_literal'


def test_missing_or_repeated_phrases_cannot_be_guessed():
    for text, value in [('查询 PSR B0329+54', 'B0329+55'), ('DM与DM', 'DM')]:
        with pytest.raises(DomainError, match='唯一'):
            ground_spans(text, parsed(value))


def test_explicit_valid_location_can_disambiguate_repeated_literal():
    value, repairs = ground_spans('DM与DM', parsed('DM', 3, 5))
    assert value['targets'][0]['start'] == 3 and not repairs
