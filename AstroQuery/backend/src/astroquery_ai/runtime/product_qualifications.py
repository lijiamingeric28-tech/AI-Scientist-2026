"""Install release proofs independently of a user's account and query history."""
import gzip
import hashlib
from .codec import canonical, content_hash, loads, utcnow
from .errors import DomainError
from .paths import resource_root


def install_release(app, directory=None, *, upgrade=False):
    directory = directory or resource_root() / 'qualifications'
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    pin = loads(manifest.read_bytes())
    marker = 'product_qualification:' + pin['release_id']
    with app.repository.read() as c:
        if not upgrade and c.execute('select 1 from settings where key=?', (marker,)).fetchone():
            return None
    data = (directory / 'product.json.gz').read_bytes()
    if hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise DomainError('PRODUCT_PROOF_HASH', '产品资格包完整性检查失败')
    package = loads(gzip.decompress(data))
    if package['schema_version'] != 'ProductQualifications/1':
        raise DomainError('PRODUCT_PROOF_SCHEMA', '产品资格包版本不受支持')
    repo = app.repository
    with repo.transaction() as c:
        # A release fills missing installation capabilities. An existing reviewed
        # installation is published by the explicit upgrade tool, never overwritten.
        for tid in package['tasks']:
            if not c.execute('select 1 from tasks where task_id=?', (tid,)).fetchone():
                now = utcnow()
                c.execute('insert into tasks(task_id,revision,generation,lifecycle,phase,science_state,kind,title,created_at,updated_at) values(?,1,1,?,?,?,?,?,?,?)',
                          (tid, 'completed', 'deliver', 'ready', 'validation', '产品资格依据', now, now))
            elif repo.task(c, tid)['kind'] != 'validation':
                raise DomainError('PRODUCT_PROOF_TASK', '资格依据与用户任务身份冲突')
        allowed = {'profile_validation','validation','validation_manifest','validation_corpus','reader_profile','software_capability_validation'}
        for item in package['objects']:
            if item['kind'] not in allowed or content_hash(item['payload']) != item['content_sha256']:
                raise DomainError('PRODUCT_PROOF_OBJECT', '资格依据内容无法核验')
            old = c.execute('select content_sha256 from objects where task_id=? and kind=? and object_id=? and version=?',
                            (item['task_id'],item['kind'],item['id'],item['version'])).fetchone()
            if old and old[0] != item['content_sha256']:
                raise DomainError('PRODUCT_PROOF_CONFLICT', '不可变资格依据发生冲突')
            if not old:
                c.execute('insert into objects values(?,?,?,?,?,?,?)',
                          (item['task_id'],item['kind'],item['id'],item['version'],item['content_sha256'],canonical(item['payload']),utcnow()))
        installed = []
        for key, value in package['settings'].items():
            existing = c.execute('select payload from settings where key=?',(key,)).fetchone()
            if existing and upgrade and key.startswith('profile:'):
                prior, _ = app.profile_authority.load(c,key.split(':',1)[1],check_connection=False)
                ref = value['validation_ref']
                incoming = repo.object(c,ref['task_id'],'profile_validation',ref['id'],ref['version'])
                if incoming['scope'] != prior['scope']:
                    raise DomainError('PRODUCT_PROOF_SCOPE', '升级不能改变既有科学范围')
                before = prior.get('execution_profiles',[prior.get('execution')])
                after = incoming.get('execution_profiles',[incoming.get('execution')])
                if any(e not in after for e in before):
                    raise DomainError('PRODUCT_PROOF_EXECUTION', '升级不能丢弃已批准执行版本')
            if not existing or upgrade:
                c.execute('insert into settings values(?,?,1) on conflict(key) do update set payload=excluded.payload,revision=settings.revision+1',(key,canonical(value)))
                installed.append(key)
        # Verify exactly the same scientific integrity gate as ordinary calls,
        # before credentials exist. Account/service eligibility is checked at use.
        for key in installed:
            if key.startswith('profile:'):
                app.profile_authority.load(c,key.split(':',1)[1],check_connection=False)
        c.execute('insert or ignore into settings values(?,?,1)',(marker,canonical({'installed':installed,'sha256':pin['sha256']})))
    return installed
