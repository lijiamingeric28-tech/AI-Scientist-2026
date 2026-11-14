"""Adapt an already interpreted lower offset; never infer an error from text."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation


def canonical_error_values(kind, values):
    """Sides name directions. A negative *lower offset* is not a negative size.

    Intervals, matrices, scalar errors and unclassified strings are untouched.
    Impossible upper/lower directions stay invalid for the existing validator.
    The producer's immutable proposal retains its original values as well.
    """
    if kind not in {'asymmetric_delta', 'relative', 'percent'} or not isinstance(values, dict):
        return values, None
    if set(values) != {'minus', 'plus'} or values.get('minus') is None:
        return values, None
    try:
        lower = Decimal(values['minus'])
        upper = Decimal(values['plus']) if values['plus'] is not None else None
        if not lower.is_finite() or upper is not None and not upper.is_finite():
            return values, None
        if lower >= 0 or upper is not None and upper < 0:
            return values, None
    except (InvalidOperation, TypeError, ValueError):
        return values, None
    result = {**values, 'minus': str(lower.copy_negate())}
    return result, {'rule': 'typed_lower_offset_to_magnitude/1',
                    'source_kind': kind, 'input_values': deepcopy(values),
                    'output_values': deepcopy(result),
                    'basis': 'model-interpreted minus/plus directions; no text inference'}
