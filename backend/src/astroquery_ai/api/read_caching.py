"""Conditional responses for already validated, versioned GET projections."""
from hashlib import sha256

from fastapi import Request, Response

from astroquery_ai.runtime.codec import canonical


def conditional_json(request: Request, payload, *, namespace: str, identity=None):
    """Call only after authoritative scope/revision validation has succeeded.

    Hash the selected representation, including dynamic library revision and
    exact references supplied by the reader. This helper never caches reads or
    skips the caller's validity checks, including on an ETag match.
    """
    body = canonical(payload)
    context = canonical({'protocol': namespace, 'path': request.url.path,
                         'query': sorted(request.query_params.multi_items()), 'identity': identity})
    etag = 'W/"' + sha256(context + b'\0' + body).hexdigest() + '"'
    headers = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
    candidates = request.headers.get('if-none-match', '').split(',')
    if any(candidate.strip() == '*' or candidate.strip().removeprefix('W/') == etag[2:]
           for candidate in candidates):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type='application/json', headers=headers)
