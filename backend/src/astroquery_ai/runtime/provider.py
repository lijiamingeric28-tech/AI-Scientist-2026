"""Recognize supported provider services independently of account credentials."""
from urllib.parse import urlsplit
import re

from .codec import digest

BEIJING = {'provider': 'bailian', 'region': 'cn-beijing', 'service': 'production', 'protocol': 'openai-v1'}


def provider_identity(endpoint):
    try:
        url = urlsplit(endpoint)
        if (url.scheme != 'https' or url.username or url.password or url.query or url.fragment
                or url.port not in (None, 443) or url.path.rstrip('/') != '/compatible-mode/v1'):
            return None
        host = (url.hostname or '').lower()
    except (TypeError, ValueError):
        return None
    if host == 'dashscope.aliyuncs.com' or re.fullmatch(r'ws-[a-z0-9]+\.cn-beijing\.maas\.aliyuncs\.com', host):
        return dict(BEIJING)
    return None


def compatible(setting, endpoint):
    published = setting.get('provider_identity')
    if published is not None:
        return published == provider_identity(endpoint) and published == BEIJING
    return setting.get('endpoint_identity') in {digest(endpoint), digest(endpoint.rstrip('/'))}
