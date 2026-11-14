"""Typography-only unit parsing; original source strings stay in records."""
import unicodedata
import re
from decimal import Decimal, localcontext


def parse_unit(text):
    from astropy import units
    lexical = unicodedata.normalize('NFKC', text).replace('−', '-').replace('·', ' ')
    # Literal integer exponent braces are source typography, not a different
    # unit. Do not evaluate TeX or strip arbitrary braces/commands.
    lexical = re.sub(r'\^\{([+-]?\d+)\}', r'**\1', lexical)
    # Registered language aliases, never infer a unit from the measured value.
    lexical = re.sub(r'\bdays\b', 'day', lexical)
    return units.Unit(lexical)


def decimal_unit_factor(source, target):
    """Compose declared unit scales before division, without float cancellation.

    Astropy still establishes legality and supplies its registered unit
    definitions. Decimal composition preserves exact prefix/power identities
    such as 10^-7 W == erg/s; it does not round a nearly-one ratio to one.
    """
    from astropy.units.core import CompositeUnit, IrreducibleUnit
    left, right = parse_unit(source), parse_unit(target)
    if not left.is_equivalent(right):
        raise ValueError('Units have different dimensions')

    def expand(unit):
        if isinstance(unit, IrreducibleUnit):
            return Decimal(1), {unit: 1}
        if not isinstance(unit, CompositeUnit):
            return expand(unit.represents)
        scale, dimensions = Decimal(str(unit.scale)), {}
        for base, power in zip(unit.bases, unit.powers):
            if int(power) != power:
                raise ValueError('nonintegral unit power')
            factor, powers = expand(base)
            scale *= factor ** int(power)
            for key, exponent in powers.items():
                dimensions[key] = dimensions.get(key, 0) + exponent * int(power)
        return scale, {k: v for k, v in dimensions.items() if v}

    with localcontext() as ctx:
        ctx.prec = 80
        try:
            a, dimensions_a = expand(left)
            b, dimensions_b = expand(right)
        except ValueError:
            # Exotic fractional powers retain the library's numeric factor;
            # never infer a rational or snap it to a convenient exact value.
            return Decimal(str(left.to(right)))
        if dimensions_a != dimensions_b:
            return Decimal(str(left.to(right)))
        return a / b


def native_coordinate_unit_equal(source, target, kind):
    """Same coordinate scale only; no logarithmic zero point is invented."""
    if source == target:
        return True
    if kind not in {'log10', 'ln'} or not isinstance(source, str) or not isinstance(target, str):
        return False
    def underlying(value):
        if kind == 'log10' and value.strip() == 'dex':
            return '1'  # coordinate coefficient; quantity/zero point still require scientific evidence
        if kind == 'log10' and (match := re.fullmatch(r'log\(([^()]+)\)', value)):
            return match[1]  # VizieR VOUnits spelling of CDS [unit]; parameters are checked separately
        return value[1:-1] if kind == 'log10' and value.startswith('[') and value.endswith(']') else value
    try:
        return decimal_unit_factor(underlying(source), underlying(target)) == 1
    except (ValueError, TypeError):
        return False
