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


# ── A10 fix: 单位归一化 (K≡Kelvin, yr≡year ...) ──
# 同义单位异写统一 — 用于单位一致性/单位不符检查: 全称/缩写/符号异写
# 不应误报 unit_mismatch (原实现 'K' vs 'Kelvin' 判不一致 → 误路由 Normalization)。
# 仅整串精确映射 (大小写不敏感); 未知单位原样返回, 保留大小写
# ('m' 米 与 'M' 兆 等不同量级单位不合并)。
_UNIT_SYNONYMS: dict[str, str] = {
    # 温度
    "kelvin": "K", "degk": "K", "degreekelvin": "K",
    "celsius": "C", "degc": "C", "degreecelsius": "C", "centigrade": "C",
    "fahrenheit": "F", "degf": "F",
    # 时间
    "second": "s", "seconds": "s", "sec": "s", "secs": "s",
    "minute": "min", "minutes": "min",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h",
    "day": "d", "days": "d",
    "year": "yr", "years": "yr", "yrs": "yr",
    "millisecond": "ms", "milliseconds": "ms",
    # 角度
    "degree": "deg", "degrees": "deg",
    "arcminute": "arcmin", "arcminutes": "arcmin",
    "arcsecond": "arcsec", "arcseconds": "arcsec",
    # 长度
    "meter": "m", "meters": "m",
    "centimeter": "cm", "centimeters": "cm",
    "millimeter": "mm", "millimeters": "mm",
    "kilometer": "km", "kilometers": "km",
    "micrometer": "um", "micrometers": "um", "micron": "um",
    "nanometer": "nm", "nanometers": "nm",
}


def canonical_unit(unit: str | None) -> str:
    """A10 fix: 单位字符串归一化 — 同义单位异写统一 (K≡Kelvin, °C≡C, yr≡year)。

    Examples:
        canonical_unit("K") == canonical_unit("Kelvin")  # → "K"
        canonical_unit("°C") == canonical_unit("C")      # → "C"
        canonical_unit("yr") == canonical_unit("year")   # → "yr"
    """
    if not unit:
        return ""
    u = str(unit).strip()
    u = u.replace("°", "").replace("℃", "C").replace("℉", "F")
    u = u.replace("⁻", "-").replace("⁺", "+")
    u = u.replace("³", "3").replace("²", "2").replace("⁰", "0")
    u = u.replace("·", "*").replace("×", "*")
    return _UNIT_SYNONYMS.get(u.lower(), u)


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
        # M4 fix: 补充材料整表检索 (matched_alias="whole_table" 或无 key_column,
        # 单天体 CDS J/ 表常见场景) 只要求表级溯源 — key_column/key_value 允许为空
        if prov.get("source_kind") == "supplement" or prov.get("matched_alias") == "whole_table":
            return bool(prov.get("db_table") and prov.get("raw_column"))
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
