"""Validate admitted source provenance for locally published user contracts."""
from astroquery_ai.registry.user_execution import verified_user_bindings
from astroquery_ai.registry.workbench_projection import ref
from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.registry.models import Representation
from .conversion_policy import conversion_permission
from .normalization import SameQuantityTransform
from .unit_declarations import arithmetic_coordinate_units


def user_permission(service, spec, binding, record, policy, source_parameters):
    if binding['property_id'] not in verified_user_bindings(service.app, spec):
        raise DomainError('USER_EXECUTION_STALE', 'Missing frozen user execution authority')
    tid = record['task_id']
    if record['property_ref'] != ref(binding['definition']):
        raise DomainError('USER_EXECUTION_SOURCE_MISMATCH', 'Admitted source has a different definition')
    with service.repo.read() as conn:
        originals = {}
        for field, kind in [('context_ref', 'context'), ('source_ref', 'source'), ('admission_receipt_ref', 'admission'),
                            ('interpretation_ref', 'interpretation')]:
            reference = record[field]
            value = service.repo.object(conn, tid, kind, reference['id'], reference['version'])
            if content_hash(value) != reference['content_sha256']:
                raise DomainError('USER_EXECUTION_SOURCE_MISMATCH', 'Source evidence reference changed')
            originals[kind] = value
        context, admission = originals['context'], originals['admission']
        if (admission.get('status') != 'passed' or context['snapshot_binding']['property'] != record['property_ref']
                or context['measurement_ref'] != {'id': record['measurement_id'], 'version': record['revision']}):
            raise DomainError('USER_EXECUTION_SOURCE_MISMATCH', 'Source admission does not bind this record')
        if not record['evidence_refs']:
            raise DomainError('USER_EXECUTION_SOURCE_MISMATCH', 'Source evidence missing')
        for reference in record['evidence_refs']:
            evidence = service.repo.object(conn, tid, 'evidence', reference['id'], reference['version'])
            artifact, _ = service.app.artifacts.read_owned(tid, evidence['artifact_ref']['id'])
            if content_hash(evidence) != reference['content_sha256'] or artifact['sha256'] != evidence['artifact_ref']['content_sha256']:
                raise DomainError('USER_EXECUTION_SOURCE_MISMATCH', 'Source artifact or evidence changed')
    if record['representation'] in {'log10', 'ln', 'magnitude'}:
        from .unit_declarations import catalog_representation_declaration
        declaration = catalog_representation_declaration(originals['source'], record, originals['interpretation'])
        declared = originals['interpretation']['proposal'].get('representation_parameters')
        try:
            candidate = Representation.model_validate(source_parameters) if source_parameters else None
            supplied = [Representation.model_validate(p) for p in (declared, declaration and declaration['parameters']) if p]
            grounded = (candidate is not None and candidate in supplied and candidate.kind == record['representation']
                        and candidate.reference_value is not None and candidate.reference_unit is not None
                        and (candidate.kind != 'magnitude' or candidate.system_ref is not None))
        except (ValueError, TypeError):
            grounded = False
        if not grounded:
            return {'allowed': False, 'reason': 'user_source_representation_reference_unresolved'}
    capabilities = binding['execution_capabilities']
    if not capabilities['normalization']['ready']:
        return {'allowed': False, 'reason': 'user_numeric_examples_required_native_retained'}
    representation = Representation.model_validate(source_parameters) if source_parameters else None
    permission = conversion_permission(policy, record, binding['output_profile'], representation)
    if permission['allowed'] and record['value']['kind'] in {'real', 'integer', 'interval'}:
        try:
            native, target = arithmetic_coordinate_units(record, binding['output_profile'])
            transform = SameQuantityTransform(representation, Representation.model_validate(binding['output_profile']['representation']), native, target,
                source_quantity_key=binding['definition']['quantity_key'], target_quantity_key=binding['definition']['quantity_key'])
            transform.value(record['value'])
        except (DomainError, ValueError, TypeError, ArithmeticError) as exc:
            return {'allowed': False, 'reason': getattr(exc, 'code', 'user_source_conversion_unsupported')}
    return permission
