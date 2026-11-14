"""Recover an original from its published location and exact hash, without scientific calls."""
import asyncio
import hashlib
from time import monotonic
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import DomainError
from .published_demos import save_artifact


def allowed(url, hosts):
    u = urlsplit(url)
    return (u.scheme == 'https' and u.hostname in hosts and u.port in (None, 443)
            and not u.username and not u.password)


async def download_original(urls, size, sha):
    hosts = {urlsplit(url).hostname for url in urls} | {'arxiv.org', 'www.arxiv.org', 'articles.adsabs.harvard.edu'}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=6), headers={'User-Agent':'AstroQuery/public-demo'}) as http:
        for start in urls:
            url = start
            try:
                for _ in range(5):
                    if not allowed(url, hosts):
                        break
                    async with http.stream('GET', url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get('location', ''))
                            continue
                        if response.status_code != 200:
                            break
                        data = bytearray()
                        async for block in response.aiter_bytes():
                            data.extend(block)
                            if len(data) > size:
                                break
                        if len(data) == size and hashlib.sha256(data).hexdigest() == sha:
                            return bytes(data)
                        break
            except (httpx.HTTPError, ValueError):
                continue
    raise DomainError('DEMO_ORIGINAL_UNAVAILABLE', '暂未从公开来源取得当时版本，可在来源资料中打开论文。', 410)


async def prepare_original(app, task_id, sha, media):
    spec = media.get(sha)
    if not spec:
        return
    path = app.artifacts.path(f'objects/{sha[:2]}/{sha}')
    if path.is_file():
        return
    locks = app.__dict__.setdefault('_demo_original_locks', {})
    async with locks.setdefault(sha, asyncio.Lock()):
        if path.is_file():
            return
        if spec.get('parent'):
            parent = spec['parent']
            if parent == sha or 'urls' not in media.get(parent, {}) or spec['operation'] not in ('page_image', 'figure_crop'):
                raise DomainError('DEMO_MEDIA_RECIPE', '图像缺少可验证的原件', 410)
            await prepare_original(app, task_id, parent, media)
            _, pdf = app.artifacts.read_owned(task_id, parent)
            data = await app.parsers.run(spec['operation'], pdf, **spec['options'])
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != sha:
                with app.repository.transaction() as conn:
                    conn.execute("UPDATE artifacts SET byte_size=?, sha256=? WHERE artifact_id=?", (len(data), actual_sha, sha))
            await asyncio.to_thread(save_artifact, path, data, sha, allow_derived_hash=True)
            return
        elif spec.get('urls'):
            with app.repository.read() as conn:
                row = conn.execute('SELECT a.byte_size FROM artifacts a JOIN artifact_refs r USING(artifact_id) WHERE a.artifact_id=? AND r.task_id=?', (sha,task_id)).fetchone()
            if not row or not 0 < row[0] <= 100 * 1024**2:
                raise DomainError('DEMO_ORIGINAL_SIZE', '未保存可验证的原件大小', 410)
            retries = app.__dict__.setdefault('_demo_source_retry_at', {})
            if monotonic() < retries.get(sha, 0):
                raise DomainError('DEMO_ORIGINAL_UNAVAILABLE', '原站暂未返回同一版本，可在来源资料中打开论文。', 410)
            slots = app.__dict__.setdefault('_demo_source_slots', asyncio.Semaphore(4))
            async with slots:
                try:
                    data = await download_original(spec['urls'], row[0], sha)
                except DomainError:
                    retries[sha] = monotonic() + 60
                    raise
        else:
            raise DomainError('DEMO_ORIGINAL_UNAVAILABLE', '此原件在当前安装中不可用', 410)
        await asyncio.to_thread(save_artifact, path, data, sha)
