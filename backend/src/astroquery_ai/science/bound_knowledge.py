"""Package author-labelled content with explicit reviewed registry bindings.

This adapter copies immutable content. It never invents a scientific mapping or
upgrades an author's review to independent source verification.
"""
from pathlib import Path
import hashlib

from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.runtime.errors import DomainError
from .knowledge_content import KnowledgeContent


def bound_content(directory, manifest, data):
    content = KnowledgeContent().load(directory / 'origin')
    expected = {'id': content['manifest']['release_id'], 'content_hash': content['manifest']['content_hash']}
    if manifest.get('content_release_ref') != expected:
        raise DomainError('KB_CONTENT_RELEASE_BINDING', '理论绑定不是该原始内容快照', 422)
    paths = {item['path'] for item in manifest['content_files']}
    required = {'origin/content-manifest.json', *('origin/' + p for p in content['manifest']['files'])}
    if required - paths:
        raise DomainError('KB_ORIGIN_FILES_MISSING', '绑定发布未完整收录原内容及审核文件', 422)
    if data['entries'] != content['entries'] or data['sources'] != content['sources']:
        raise DomainError('KB_CONTENT_REWRITTEN', '绑定不能改写原条目、来源或声明来源类别', 422)
    return content


def package_content(content_root, destination, *, release_id, registry_ref, bindings, reviews, synthetic=False):
    """Build only from supplied bindings/reviews; no inference and no activation."""
    content_root, destination = Path(content_root), Path(destination)
    content = KnowledgeContent().load(content_root)
    if not bindings:
        raise DomainError('KB_BINDINGS_MISSING', '只有原内容，缺少正式性质绑定，不能生成运行发布', 422)
    destination.mkdir(parents=True, exist_ok=False)
    files = []

    def write(role, relative, raw):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append({'role': role, 'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()})

    for relative in ['content-manifest.json', *content['manifest']['files']]:
        write('origin:' + relative, 'origin/' + relative, (content_root / relative).read_bytes())
    for role, value in {'entries': content['entries'], 'sources': content['sources'],
                        'bindings': bindings, 'reviews': reviews,
                        'index': {'authority': 'explicit_bindings_only'},
                        'coverage': {'content_release': content['report'], 'binding_count': len(bindings)}}.items():
        write(role, role + '.json', canonical(value))
    manifest = {'schema_version': 'insight-knowledge/2', 'status': 'ready_to_import',
        'release_id': release_id, 'synthetic': synthetic, 'registry_release_ref': registry_ref,
        'content_release_ref': {'id': content['manifest']['release_id'], 'content_hash': content['manifest']['content_hash']},
        'content_files': files}
    manifest['content_sha256'] = content_hash(manifest)
    (destination / 'manifest.json').write_bytes(canonical(manifest))
    return manifest
