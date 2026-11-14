"""Native log coordinates do not authorize invented reference parameters."""
from decimal import Decimal
import pytest
from pydantic import ValidationError
from astroquery_ai.registry.models import Representation
from astroquery_ai.science.normalization import SameQuantityTransform
from astroquery_ai.runtime.errors import DomainError


def transform(source, target, a, b):
    return SameQuantityTransform(source, target, a, b, source_quantity_key='synthetic-q', target_quantity_key='synthetic-q')


def test_native_log_identity_preserves_literal_and_error_coordinate():
    native = Representation(kind='log10', native_coordinate_only=True)
    op = transform(native, native, 'dex', 'dex')
    assert op.apply(Decimal('-4.9200')) == Decimal('-4.9200')
    assert str(op.apply(Decimal('-4.9200'))) == '-4.9200'
    assert op.derivative(Decimal('-4.9200')) == 1
    assert op.check_first_order(Decimal('-4.9200'), Decimal('.07'))['derivative'] == '1'
    for target, unit in [(Representation(kind='linear'), '1'), (native, 'unknown-other-coordinate')]:
        with pytest.raises(DomainError) as err:
            transform(native, target, 'dex', unit)
        assert err.value.code == 'NATIVE_COORDINATE_ONLY'
    with pytest.raises(ValidationError):
        Representation(kind='log10')


def test_opaque_h_unit_can_only_pass_an_exact_identity():
    rep = Representation(kind='linear')
    op = transform(rep, rep, 'source h100^-1 Mpc', 'source h100^-1 Mpc')
    assert str(op.apply(Decimal('3.400'))) == '3.400'
    with pytest.raises((DomainError, ValueError)):
        transform(rep, rep, 'source h100^-1 Mpc', 'Mpc')
    assert 'native_coordinate_only' not in rep.model_dump()


def test_explicit_log_unit_alias_identity_preserves_decimal_literal():
    source = Representation(kind='log10', reference_value='1', reference_unit='mW/m2')
    target = Representation(kind='log10', reference_value='1', reference_unit='erg/cm2/s')
    op = transform(source, target, '[mW/m2]', 'erg/cm2/s')
    assert op.coordinate_identity and str(op.apply(Decimal('-10.8400'))) == '-10.8400'
    assert op.derivative(Decimal('-10.84')) == 1
    from astroquery_ai.science.unit_declarations import catalog_representation_declaration
    declaration = catalog_representation_declaration({'kind':'catalog','metadata':{'columns':[{'name':'flux','unit_text':'[mW/m2]'}]}},
        {'representation':'log10','unit':'[mW/m2]','source_ref':{'id':'native'},'content_sha256':'f'*64},
        {'proposal':{'column':'flux'}})
    assert declaration['parameters']['reference_value'] == '1'
    assert catalog_representation_declaration({'kind':'paper'}, {'representation':'log10'}, {'proposal':{}}) is None


def test_known_original_basis_and_identity_only_output_are_same_coordinate():
    source=Representation(kind='log10',reference_value='1',reference_unit='yr')
    target=source.model_copy(update={'native_coordinate_only':True})
    op=transform(source,target,'yr','yr')
    assert op.coordinate_identity and str(op.apply(Decimal('9.5800')))=='9.5800'
    assert op.derivative(Decimal('9.58'))==1
    with pytest.raises(DomainError):
        transform(source,target.model_copy(update={'reference_value':'10'}),'yr','yr')
    ratio=Representation(kind='log10',reference_value='1',reference_unit='1')
    op=transform(ratio,ratio.model_copy(update={'native_coordinate_only':True}),'dex','1')
    assert str(op.apply(Decimal('+0.050')))=='0.050'
