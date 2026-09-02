"""配置文件加载工具"""

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


def load_catalog_config(config_path: str = "./config/catalog_config.json") -> Dict:
    """
    加载星表配置文件（正则表达式、VizieR 表名等）

    Args:
        config_path: 配置文件路径

    Returns:
        星表配置字典
    """
    config_file = Path(config_path)

    if not config_file.exists():
        logger.error(f"[load_catalog_config] 配置文件不存在: {config_path}")
        raise FileNotFoundError(f"Catalog config file not found: {config_path}")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        logger.info(f"[load_catalog_config] 成功加载配置文件: {config_path}")
        logger.debug(f"[load_catalog_config] 加载了 {len(config)} 个星表配置")

        return config

    except json.JSONDecodeError as e:
        logger.error(f"[load_catalog_config] JSON解析错误: {e}")
        raise
    except Exception as e:
        logger.error(f"[load_catalog_config] 加载配置文件失败: {e}")
        raise


def load_catalog_metadata(config_path: str = "./config/catalog_metadata.json") -> Dict:
    """
    加载星表元数据文件（描述、方法学等）

    Args:
        config_path: 元数据文件路径

    Returns:
        星表元数据字典
    """
    config_file = Path(config_path)

    if not config_file.exists():
        logger.error(f"[load_catalog_metadata] 元数据文件不存在: {config_path}")
        raise FileNotFoundError(f"Catalog metadata file not found: {config_path}")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # 过滤掉模板说明字段
        metadata = {k: v for k, v in metadata.items() if not k.startswith('_')}

        logger.info(f"[load_catalog_metadata] 成功加载元数据文件: {config_path}")
        logger.debug(f"[load_catalog_metadata] 加载了 {len(metadata)} 个星表元数据")

        return metadata

    except json.JSONDecodeError as e:
        logger.error(f"[load_catalog_metadata] JSON解析错误: {e}")
        raise
    except Exception as e:
        logger.error(f"[load_catalog_metadata] 加载元数据文件失败: {e}")
        raise


def load_catalog_units(config_path: str = "./config/catalog_units.json") -> Dict:
    """
    加载星表字段单位配置

    Args:
        config_path: 单位配置文件路径

    Returns:
        星表单位配置字典
    """
    config_file = Path(config_path)

    if not config_file.exists():
        logger.error(f"[load_catalog_units] 单位配置文件不存在: {config_path}")
        raise FileNotFoundError(f"Catalog units file not found: {config_path}")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            units = json.load(f)

        # 过滤掉模板说明字段
        units = {k: v for k, v in units.items() if not k.startswith('_')}

        logger.info(f"[load_catalog_units] 成功加载单位配置文件: {config_path}")
        logger.debug(f"[load_catalog_units] 加载了 {len(units)} 个星表单位配置")

        return units

    except json.JSONDecodeError as e:
        logger.error(f"[load_catalog_units] JSON解析错误: {e}")
        raise
    except Exception as e:
        logger.error(f"[load_catalog_units] 加载单位配置文件失败: {e}")
        raise
