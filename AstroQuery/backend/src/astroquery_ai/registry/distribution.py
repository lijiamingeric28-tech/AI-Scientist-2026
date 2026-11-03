"""Read the published science inputs. External candidate imports still verify the entire author package."""
import lzma
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from astroquery_ai.runtime.codec import loads, utcnow
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.paths import resource_root

from .consumer import compile_verified_inputs
from .science_conditions import reindex_conditions


def load_verified_distribution(directory, manifest):
    pin_file = resource_root() / 'property_registry/production/release.json'
    pin = loads(pin_file.read_bytes())
    archive = directory / 'runtime-inputs.json.xz'
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (digest != pin['runtime_inputs_sha256'] or manifest['release_id'] != pin['release_id']
            or manifest['content_sha256'] != pin['manifest_content_sha256']):
        raise DomainError('PRODUCT_LIBRARY_HASH', '科学发布物与产品固定版本不一致')
    with lzma.open(archive, 'rb') as stream:
        payload = loads(stream.read())
    candidate = payload['candidate']
    if (payload.get('format') != 'reviewed-runtime-inputs/1'
            or candidate['report']['manifest_file_sha256'] != manifest['source_manifest_sha256']
            or payload['science']['config_sha256'] != manifest['science_config_sha256']):
        raise DomainError('PRODUCT_LIBRARY_HASH', '科学输入与接受配置不一致')
    candidate['science'] = reindex_conditions(payload['science'])
    result = compile_verified_inputs(candidate, manifest['source_manifest_sha256'],
        manifest['science_config_sha256'], payload['amendment'], manifest.get('support_policy'))
    if result['manifest'] != manifest:
        raise DomainError('CONSUMER_CONFIGURATION_CHANGED', '部署版未重现同一科学视图')
    return result, [pin_file, directory / 'manifest.json', archive]


def install_distribution(registry, package):
    manifest = loads((package / 'manifest.json').read_bytes())
    rid = manifest['release_id']
    parent = registry.root / 'releases'
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / rid
    with tempfile.TemporaryDirectory(dir=parent) as temp:
        staged = shutil.copytree(package, Path(temp) / 'release')
        registry.validate(staged)
        with registry.repository.transaction() as conn:
            prior = conn.execute('SELECT content_sha256 FROM registry_releases WHERE release_id=?', (rid,)).fetchone()
            if prior and prior[0] != manifest['content_sha256']:
                raise DomainError('IMMUTABLE_RELEASE', '同名科学发布物内容不一致', 409)
            if not directory.exists():
                os.replace(staged, directory)
            else:
                registry.validate(directory)
            if not prior:
                conn.execute('INSERT INTO registry_releases VALUES(?,?,?,?,?,?)',
                    (rid, manifest['content_sha256'], str(directory), 'property', 0, utcnow()))
        registry._consumer_cache.pop(str(staged), None)
    return rid
