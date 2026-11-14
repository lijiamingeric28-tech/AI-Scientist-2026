"""A proven dimensional contradiction rejects; compatibility never admits."""
from .units import parse_unit
from .unit_declarations import output_coordinate_unit


def contradiction(column, output, source_representation='linear'):
    if (not column or source_representation not in {'linear','magnitude'} or output['representation']['kind'] != 'linear'
            or output['unit']['kind'] != 'physical' or not column.get('unit_text')
            or column.get('datatype') not in {'unsignedByte', 'short', 'int', 'long', 'float', 'double'}):
        return None
    try:
        from astropy import units
        native, target = parse_unit(column['unit_text']), parse_unit(output_coordinate_unit(output))
        native_function=False
        if hasattr(native,'physical_unit'):
            native=native.physical_unit;native_function=True
        elif getattr(native,'_function_unit_class',None):
            native=native._function_unit_class().physical_unit;native_function=True
        if hasattr(target,'physical_unit'):
            target=target.physical_unit
        elif getattr(target,'_function_unit_class',None):
            target=target._function_unit_class().physical_unit
        if (str(native.physical_type)=='unknown'
                or str(native.physical_type)=='dimensionless' and not native_function
                or str(target.physical_type) in {'unknown', 'dimensionless'}
                or native.is_equivalent(target, equivalencies=units.temperature())):
            return None
    except (ValueError, TypeError):
        return None
    return {'reason': 'native_linear_dimension_conflicts_with_selected_quantity', 'column': column['name'],
        'source_unit': column['unit_text'], 'target_unit': output_coordinate_unit(output),
        'source_dimension': str(native.physical_type), 'target_dimension': str(target.physical_type),
        'registered_function_coordinate':native_function}
