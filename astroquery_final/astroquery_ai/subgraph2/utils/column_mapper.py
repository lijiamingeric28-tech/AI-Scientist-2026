"""数据库列名到标准性质名的 LLM 映射（带缓存）

机制：
  - 按 (vizier_table, PropertySpec 指纹) 缓存映射结果
  - 一次请求判定该表全部列
  - 异步并发处理多表
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# 缓存文件：持久化到子图2配置目录
_CACHE_FILE = Path(__file__).parent.parent / "config" / "column_mapping_cache.json"


def _compute_property_spec_fingerprint(property_spec: List[Dict]) -> str:
    """计算 PropertySpec 的指纹（用于缓存键）"""
    # 只取 property_id，忽略描述等易变字段
    ids = sorted(p["property_id"] for p in property_spec)
    return hashlib.md5(json.dumps(ids, sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:12]


def _load_cache() -> Dict:
    """加载缓存"""
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[ColumnMapper] 缓存加载失败: {exc}")
        return {}


def _save_cache(cache: Dict) -> None:
    """保存缓存"""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[ColumnMapper] 缓存保存失败: {exc}")


def _get_llm_client() -> OpenAI:
    """从 subgraph1 配置创建 LLM 客户端"""
    from ...subgraph1.utils.llm_utils import get_llm_client
    return get_llm_client()


def _get_model_name() -> str:
    """从 subgraph1 配置读取模型名（与全系统对齐）"""
    from ...subgraph1.config import config as s1_config
    return s1_config.llm.get('model', 'qwen3.7-flash')


def map_columns_to_properties(
    vizier_table: str,
    columns_meta: List[Dict],  # [{name, unit, ucd, description}, ...]
    property_spec: List[Dict],  # [{property_id, name_cn, unit, ucd, description}, ...]
    llm_client: Optional[OpenAI] = None,
    model: str = "",
) -> Dict[str, str]:
    """
    调用 LLM 将 VizieR 表的列映射到标准性质名

    Args:
        vizier_table: VizieR 表 ID（如 "I/355/gaiadr3"）
        columns_meta: 该表全部列的元数据
        property_spec: 本次查询的标准性质列表
        llm_client: OpenAI 客户端（可选，不传则内部创建）
        model: 模型名（可选，默认用 subgraph1 配置）

    Returns:
        {列名: property_id | None}  # None 表示无匹配
    """
    # 检查缓存
    cache_key = f"{vizier_table}#{_compute_property_spec_fingerprint(property_spec)}"
    cache = _load_cache()

    if cache_key in cache:
        logger.info(f"[ColumnMapper] 缓存命中 {vizier_table}")
        return cache[cache_key]

    logger.info(f"[ColumnMapper] 开始映射 {vizier_table}（{len(columns_meta)} 列 → {len(property_spec)} 性质）")

    # 构造 prompt
    columns_desc = "\n".join(
        f"- {c['name']} | unit={c.get('unit', '')} | ucd={c.get('ucd', '')} | {c.get('description', '')[:80]}"
        for c in columns_meta
    )

    properties_desc = "\n".join(
        f"- {p['property_id']} | {p.get('name_cn', '')} | unit={p.get('unit', '')} | ucd={p.get('ucd', '')} | {p.get('description', '')[:80]}"
        for p in property_spec
    )

    prompt = f"""你是天文数据标准化专家。任务：将 VizieR 表的列映射到标准性质名。

## VizieR 表：{vizier_table}
列元数据（共 {len(columns_meta)} 列）：
{columns_desc}

## 标准性质列表（只能从中选择）
{properties_desc}

## 规则
1. 只输出能确定映射的列，无法判断的列不要出现在输出中
2. 映射依据：列名、UCD、单位、描述的综合匹配
3. UCD 优先但不唯一：UCD 匹配时，还需检查单位量纲是否一致
4. 输出格式：严格 JSON，不要任何解释文字或 markdown 围栏

输出示例：
{{"Plx": "parallax", "Gmag": "g_mag", "BP-RP": "bp_rp"}}

请判定并输出映射结果："""

    try:
        client = llm_client or _get_llm_client()
        response = client.chat.completions.create(
            model=model or _get_model_name(),
            messages=[
                {"role": "system", "content": "你是天文数据标准化专家，只输出 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=4096,
        )

        content = response.choices[0].message.content.strip()

        # 容忍 markdown 围栏
        content = re.sub(r"^```\w*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        mapping = json.loads(content)

        if not isinstance(mapping, dict):
            logger.error(f"[ColumnMapper] LLM 返回非字典: {type(mapping)}")
            return {}

        # 归一化：值必须在 property_spec 的 property_id 里，否则置 None
        valid_ids = {p["property_id"] for p in property_spec}
        result = {k: (v if v in valid_ids else None) for k, v in mapping.items()}

        logger.info(f"[ColumnMapper] 映射完成 {vizier_table}: {len(result)} 列有映射")

        # 只缓存有实际映射的列（空映射不写缓存——避免 LLM 临时失败/空响应
        # 被永久缓存，导致后续查询永远命中空结果不再重试）
        has_mapping = {k: v for k, v in result.items() if v}
        if has_mapping:
            cache[cache_key] = result
            _save_cache(cache)
        else:
            logger.warning(f"[ColumnMapper] {vizier_table} 无任何列映射成功，跳过缓存")

        return result

    except Exception as exc:
        logger.exception(f"[ColumnMapper] 映射失败 {vizier_table}")
        return {}
