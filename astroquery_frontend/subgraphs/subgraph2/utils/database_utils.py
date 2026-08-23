"""数据库查询辅助函数"""

import re
import logging
import numpy as np
from typing import Dict, List

logger = logging.getLogger(__name__)


def extract_catalog_ids(aliases: List[str], catalog_config: Dict) -> Dict[str, List[Dict]]:
    """
    从别名列表中提取各星表的标识符

    Args:
        aliases: SIMBAD 返回的别名列表
        catalog_config: 星表配置（包含正则表达式）

    Returns:
        {
            "gaia_dr3": [
                {"id": "5854013331201520640", "full_alias": "Gaia DR3 5854013331201520640", ...}
            ],
            "2mass": [...]
        }
    """
    found_ids = {}

    logger.debug(f"[extract_catalog_ids] 开始从 {len(aliases)} 个别名中提取星表标识符")

    for alias in aliases:
        for cat_key, cat_info in catalog_config.items():
            pattern = cat_info['pattern']

            try:
                match = re.search(pattern, alias)

                if match:
                    if cat_key not in found_ids:
                        found_ids[cat_key] = []

                    catalog_id = match.group(1).strip()

                    # 专家审计修正（V2.4）：
                    # - ic: NGC2000 表的 Name 列存 "I4756"（大写 I 无空格），而 pattern
                    #   提取纯数字 4756，直接查会误中 NGC 4756 → 提取后补 "I" 前缀
                    # - nbgg: 组号列 Group 可能带内部空格（如 "11- 1"）→ 去空白对齐
                    if cat_key == "ic" and catalog_id.isdigit():
                        catalog_id = f"I{catalog_id}"
                    elif cat_key == "nbgg":
                        catalog_id = catalog_id.replace(" ", "")

                    # 去重：同一星表同一 ID 只保留一条。
                    # 同一天体常有多个别名（如 "3C 274" 和 "3C 274.0"），
                    # 不去重会导致对同一星表重复查询、产出重复 records。
                    existing = [x['id'] for x in found_ids[cat_key]]
                    if catalog_id in existing:
                        logger.debug(f"[extract_catalog_ids] 跳过重复 ID {cat_key}: {catalog_id}")
                        continue

                    found_ids[cat_key].append({
                        'id': catalog_id,
                        'full_alias': alias.strip(),
                        'catalog_name': cat_info['name'],
                        'vizier_table': cat_info['vizier_table'],
                        'key_column': cat_info['key_column']
                    })

                    logger.debug(f"[extract_catalog_ids] 匹配到 {cat_info['name']}: {catalog_id}")

            except re.error as e:
                logger.warning(f"[extract_catalog_ids] 正则表达式错误 ({cat_key}): {e}")
                continue

    logger.info(f"[extract_catalog_ids] 从别名中提取到 {len(found_ids)} 个星表的标识符")

    return found_ids


def build_database_source(cat_key: str, catalog_metadata: Dict) -> dict:
    """
    构建数据库 source（从元数据配置文件）

    Args:
        cat_key: 星表键名（如 "gaia_dr3"）
        catalog_metadata: 星表元数据配置

    Returns:
        database source dict
    """
    if cat_key not in catalog_metadata:
        logger.warning(f"[build_database_source] 未找到星表元数据: {cat_key}")
        return None

    meta = catalog_metadata[cat_key]

    source = {
        "source_id": meta.get("source_id", f"SRC_DB_{cat_key.upper()}"),
        "source_type": "database",
        "title": meta.get("title", ""),
        "vizier_table_id": meta.get("vizier_table_id", ""),
        "description": meta.get("description", ""),
        "reference_paper": meta.get("reference_paper"),
        "bibcode": meta.get("bibcode"),
        "research_methodology": meta.get("research_methodology", ""),
        "observation_facility": meta.get("observation_facility"),
        "waveband": meta.get("waveband", ""),
        "research_content": meta.get("research_content", "")
    }

    return source


def build_database_records(
    table,
    source_id: str,
    target_entity: str,
    id_info: Dict,
    catalog_units: Dict,
    entity_type: str = "Unknown",
    column_mapping: Dict[str, str] = None,
) -> List[Dict]:
    """
    从 VizieR 查询结果构建 database records（EAV 模型）

    关键功能：
    1. 将一行多列的数据拆解为多条 record（每个物理量一条）
    2. 使用 column_mapping 把列名归一到标准性质名
    3. 确保所有字段的数据类型符合下游要求
    4. 跳过空值和主键列

    Args:
        table: VizieR 返回的表格（astropy Table 对象）
        source_id: 数据库 source_id（如 "SRC_DB_GAIA_DR3"）
        target_entity: 用户输入的天体名称（如 "M31"）
        id_info: 星表标识符信息（包含 vizier_table, key_column, id）
        catalog_units: 该星表的单位配置字典（如 {"Plx": "mas", "Gmag": "mag"}）
        entity_type: SIMBAD otype（如 "AGN"、"GlC"、"SB*"），默认 "Unknown"
        column_mapping: 列名到标准性质名的映射（如 {"Plx": "parallax", "Gmag": "g_mag"}）
                        - None      → 无白名单，输出原始列名（兼容旧逻辑）
                        - {}        → 有白名单但 LLM 无任何匹配，产出 0 条（D1 fix）
                        - {col: prop} → 只输出映射列，field_name 用标准性质名

    Returns:
        records 列表（每个物理量一条 record）
    """
    records = []

    logger.debug(f"[build_database_records] 开始构建 records，表格有 {len(table)} 行，{len(table.colnames)} 列")
    if column_mapping:
        logger.debug(f"[build_database_records] 使用列名映射（{len(column_mapping)} 列有映射）")

    # 遍历表格的每一行
    for row_idx, row in enumerate(table):
        # 遍历表格的每一列
        for col_name in table.colnames:
            # 跳过主键列
            if col_name == id_info['key_column']:
                continue

            # 三态列名映射语义（D1 fix）：
            # - column_mapping is None → 无白名单，原始列名兜底输出
            # - column_mapping == {}   → 有白名单但 LLM 无匹配，产出 0 条
            # - 非空 dict             → 只输出映射列
            if column_mapping is not None:
                if col_name not in column_mapping:
                    continue
                if column_mapping.get(col_name) is None:
                    continue

            # 获取标准性质名（有映射用映射值，否则用原始列名）
            standard_property_id = (
                column_mapping[col_name] if column_mapping is not None else col_name
            )

            # 获取值
            val = row[col_name]

            # 处理掩码值（masked value）并转换为字符串
            if hasattr(val, 'mask') and val.mask:
                continue  # 跳过空值
            elif isinstance(val, (np.integer, np.floating)):
                # 数值类型转换为字符串 (M8 fix: 大整数保留精度 — str(float) 会把
                # 超 2^53 整数变 '5.85e+18', 浮点写 '123.0' 式, 下游回查失真)
                # M-22 fix: 浮点改 '.17g' 保留双精度全精度 — 'g' 默认仅 6 位有效
                # 数字 (1234.56789 → '1234.57'), 两来源截断同值会掩盖真实差异
                if isinstance(val, np.integer):
                    field_value = str(int(val))
                else:
                    field_value = format(float(val), '.17g')
            elif val is None:
                continue  # 跳过 None 值
            else:
                # 其他类型转换为字符串并去除空白
                field_value = str(val).strip()

            # 跳过空字符串
            if field_value == "" or field_value.lower() == "nan":
                continue

            # 获取单位（从配置文件）
            field_unit = catalog_units.get(col_name, "")

            # 生成 record_id（格式：REC_source_id_catalog_key_row_columnname）
            # 修复 C1：加入 row_idx 避免重复
            # 修复 C2：用原始列名 col_name 而非映射后的 standard_property_id——
            #   同一行多个列可能映射到同一性质（如 HIP 的 RAICRS/RA* 都→right_ascension），
            #   若用 standard_property_id 会生成相同 record_id，导致前端 React key 冲突
            record_id = f"REC_{source_id}_{id_info['id']}_{row_idx}_{col_name}"

            # 构建 record（符合下游 schema 要求）
            record = {
                "record_id": record_id,
                "source_id": source_id,
                "entity_type": entity_type,  # SIMBAD otype（如 AGN / GlC / SB*）
                "entity_name": target_entity,
                "field_name": standard_property_id,  # 标准性质名（不再是原始列名）
                "field_value": field_value,  # 字符串格式
                "field_unit": field_unit,  # 原始单位（不在上游换算）
                "extraction_method": "database_query",
                "provenance": {
                    "source_kind": "database",
                    "db_table": id_info['vizier_table'],
                    "key_column": id_info['key_column'],
                    "key_value": str(id_info['id']),
                    "raw_column": col_name,  # 原始列名留痕
                    "raw_unit": field_unit,  # 原始单位留痕
                    "row_index": row_idx,  # 行索引
                }
            }

            records.append(record)

    logger.debug(f"[build_database_records] 构建了 {len(records)} 条 records")

    return records
