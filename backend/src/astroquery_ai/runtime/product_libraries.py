"""First-install defaults, using the existing pinned scientific importers."""
from pathlib import Path
import hashlib
import os
import tempfile
import shutil
import zipfile
from .codec import loads
from .errors import DomainError
from .paths import resource_root


def unpack(archive, destination, expected):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise DomainError('PRODUCT_LIBRARY_HASH', '随产品提供的科学库文件校验失败')
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise DomainError('PRODUCT_LIBRARY_PATH', '科学库包含不允许的文件路径')
        package.extractall(destination)


def ensure_libraries(app):
    with app.repository.read() as c:
        if c.execute("select 1 from settings where key='active_registry'").fetchone():
            return
    resources = resource_root()
    defaults = loads((resources/'qualifications/manifest.json').read_bytes()).get('default_knowledge')
    if not defaults:
        raise DomainError('PRODUCT_LIBRARY_MISSING', '产品缺少默认知识库发布物')
    temporary = Path(tempfile.mkdtemp(prefix='aq-install-')).resolve()
    directory = Path(chr(92)*2+'?'+chr(92)+str(temporary)) if os.name=='nt' else temporary
    try:
        from astroquery_ai.registry.distribution import install_distribution
        release_id = install_distribution(app.registry, resources / 'property_registry/production')
        knowledge = directory/'knowledge'
        unpack(resources/defaults['archive'],knowledge,defaults['sha256'])
        kb=app.knowledge.import_release(knowledge,activate=False)
        from astroquery_ai.tools.activate_reviewed_pair import activate
        activate(app,release_id,kb['release_id'])

    finally:
        assert temporary.parent == Path(tempfile.gettempdir()).resolve() and temporary.name.startswith('aq-install-')
        shutil.rmtree(directory)
