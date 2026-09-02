"""
source_utils.py — V3.1: source_type-aware helper functions

提供 paper vs database 两种数据源的差异检测信号，
所有质量评估工具通过此模块统一判断，避免逻辑漂移。
"""
from __future__ import annotations
from typing import Any

# Database record 的 extraction_method 特征值
DATABASE_METHOD = "database_query"


def is_database_source(source: dict[str, Any] | None) -> bool:
    """判断 source 是否为 database 类型。"""
    return (source or {}).get("source_type") == "database"


def is_database_record(record: dict[str, Any] | None) -> bool:
    """判断 record 是否为 database 提取记录。"""
    return (record or {}).get("extraction_method") == DATABASE_METHOD


def is_paper_record(record: dict[str, Any] | None) -> bool:
    """判断 record 是否为 paper 提取记录 (非 database_query)。"""
    return not is_database_record(record)


def provenance_is_complete(record: dict[str, Any] | None) -> bool:
    """
    判断 record 的 provenance 是否完整。

    Paper: prov.page 非 None AND prov.bbox 为长度为4的列表
    Database: prov.db_table + key_column + key_value + raw_column 均非空
    空/None provenance → False
    """
    prov = (record or {}).get("provenance")
    if not prov or not isinstance(prov, dict):
        return False

    if is_database_record(record):
        return all(
            prov.get(k) for k in ("db_table", "key_column", "key_value", "raw_column")
        )
    # Paper
    return (
        prov.get("page") is not None
        and isinstance(prov.get("bbox"), list)
        and len(prov.get("bbox", [])) == 4
    )


def get_missing_provenance_fields(record: dict[str, Any] | None) -> list[str]:
    """返回缺失的 provenance 字段名列表 (用于报告)。"""
    prov = (record or {}).get("provenance")
    if not prov or not isinstance(prov, dict):
        return ["provenance"]
    missing = []
    if is_database_record(record):
        for k in ("db_table", "key_column", "key_value", "raw_column"):
            if not prov.get(k):
                missing.append(f"provenance.{k}")
    else:
        if prov.get("page") is None:
            missing.append("provenance.page")
        if not isinstance(prov.get("bbox"), list) or len(prov.get("bbox", [])) != 4:
            missing.append("provenance.bbox")
    return missing
