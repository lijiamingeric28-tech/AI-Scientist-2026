"""Pin a reviewed ordinary reader strategy to the existing frozen task."""
from astroquery_ai.runtime.codec import content_hash, loads
from astroquery_ai.runtime.errors import DomainError


def pin_reader_profile(app, conn, task_id, spec):
    repo = app.repository
    pins = repo.objects(conn, task_id, 'reader_profile_pin')
    if pins:
        return pins[0]
    row = conn.execute("SELECT payload FROM settings WHERE key='reader_profile:M06'").fetchone()
    if not row:
        return None  # Historical/unconfigured installs keep their original default.
    ref = loads(row[0])
    profile = repo.object(conn, ref['task_id'], 'reader_profile', ref['id'], ref['version'])
    actual = {b['property_id']: b['definition']['content_sha256'] for b in spec['properties']}
    exact=profile.get('definition_refs')
    covered=all({'id':b['property_id'],'version':b['definition']['definition_version'],
                 'content_sha256':b['definition']['content_sha256']} in exact for b in spec['properties']) if exact is not None else all(profile['definition_hashes'].get(k)==v for k,v in actual.items())
    if (content_hash(profile) != ref['content_sha256'] or profile['registry_ref'] != spec['registry_release']
            or not covered):
        raise DomainError('READER_PROFILE_UNVERIFIED', '读取配置未覆盖本次准确定义')
    qualification, qref = app.profile_authority.load(conn, 'M06')
    if qref != profile['qualification_ref'] or qualification['state'] != 'qualified':
        raise DomainError('READER_PROFILE_UNVERIFIED', '读取配置未绑定正常M06资格')
    pin = {'reference': ref, 'registry_ref': spec['registry_release'], 'settings': profile['settings'],
        'qualification_ref': qref, 'evidence_refs': profile['evidence_refs']}
    repo.put_object(conn, task_id, 'reader_profile_pin', task_id, 1, pin)
    return pin
