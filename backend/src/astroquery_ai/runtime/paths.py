"""Immutable resources and explicitly selected data; source layout lives here only."""
from __future__ import annotations

import json
import os
import sys
from importlib.resources import files
from pathlib import Path

from .errors import DomainError


def product_root() -> Path | None:
    source = Path(__file__).resolve().parents[2]
    if source.name != 'src' or source.parent.name != 'backend':
        return None
    candidate = source.parent.parent
    if (candidate / 'pyproject.toml').is_file():
        return candidate
    return None


def source_product() -> Path:
    root = product_root()
    if root is None:
        raise DomainError('SOURCE_LAYOUT_REQUIRED', '此维护命令需要产品源码目录', 422)
    return root


def _source_path(root: Path, name: str) -> Path:
    path = root / name
    previous = root / 'AstroQuery' / name
    if not path.exists() and previous.exists():
        return previous
    return path


def local_paths() -> dict:
    explicit = os.environ.get('ASTROQUERY_PATHS_FILE')
    source = product_root()
    path = Path(explicit) if explicit else _source_path(source, 'paths.local.json') if source else None
    if path is None or not path.is_file():
        if explicit:
            raise DomainError('PATH_CONFIGURATION_MISSING', '指定的路径配置不存在', 422)
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise DomainError('PATH_CONFIGURATION_INVALID', '路径配置须为对象', 422)
    if source is not None and not explicit and path.parent != source:
        # The previous source layout resolved relative locations from AstroQuery/.
        for key in ('data_root', 'dotenv_file', 'frontend_dist', 'build_root'):
            if value.get(key):
                value[key] = str(path.parent / Path(value[key]).expanduser())
    return value


def data_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    environment = os.environ.get('ASTROQUERY_DATA_ROOT')
    if environment:
        return Path(environment).expanduser().resolve()
    configured = local_paths().get('data_root')
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_dir():
            raise DomainError('CONFIGURED_DATA_ROOT_MISSING', '已选运行数据目录不存在；未创建空库替代', 422)
        return path
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'data'
    source = product_root()
    if source:
        return _source_path(source, 'runtime-data')
    base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return base / 'AstroQuery'


def resource_root() -> Path:
    source = product_root()
    if source:
        return source / 'resources'
    return Path(str(files('astroquery_ai_resources')))


def knowledge_content_root() -> Path:
    return resource_root() / 'insight_kb'


def dotenv_file() -> Path:
    configured = local_paths().get('dotenv_file')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / '.env'
    source = product_root()
    return _source_path(source, '.env') if source else data_root() / '.env'


def frontend_dist() -> Path:
    configured = local_paths().get('frontend_dist')
    if configured:
        return Path(configured).expanduser().resolve()
    source = product_root()
    return source / 'frontend/dist' if source else resource_root() / 'frontend'


def build_root() -> Path:
    configured = local_paths().get('build_root')
    return Path(configured).expanduser().resolve() if configured else source_product() / '.build'
