"""数据库查询节点"""

import time
import logging

from ..state import RetrievalState
from ..config import config
from ..utils import (
    load_catalog_config,
    load_catalog_metadata,
    load_catalog_units,
    extract_catalog_ids,
    build_database_source,
    build_database_records
)
from ..utils.column_mapper import map_columns_to_properties
from ..utils.vizier_client import query_with_fallback
from subgraphs.subgraph1.utils.llm_utils import get_llm_client

logger = logging.getLogger(__name__)


def database_query(state: RetrievalState) -> RetrievalState:
    """
    数据库查询节点

    步骤：
    1. 加载 27 个星表的配置（包含正则、元数据、单位）
    2. 从 SIMBAD 别名中提取各星表的标识符
    3. 顺序查询 VizieR（展示进度）
    4. LLM 映射列名到标准性质名（按表缓存）
    5. 构建 sources 和 records

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    simbad_info = state.get("simbad_info", {})
    # 别名来源：子图 2 入口 simbad_resolver 产出的 simbad_aliases（combine 原语义）。
    # 不要改读 simbad_info["ALIASES"] —— P1 的 SIMBAD 请求不含 ids 参数，从不产出该键（审计 A1）。
    aliases = state.get("simbad_aliases", []) or []
    target_entity = state["target_entity"]
    query_id = state["query_id"]
    property_spec = state.get("property_spec", [])

    logger.info(f"[Database Query] Query ID: {query_id}")
    logger.info(f"[Database Query] Aliases: {len(aliases)} found")
    logger.info(f"[Database Query] PropertySpec: {len(property_spec)} 个标准性质")

    state["database_query_status"] = "running"

    # Step 1: 加载配置
    try:
        catalog_config_path = config.get_catalog_config_path()
        catalog_metadata_path = config.get_catalog_metadata_path()
        catalog_units_path = config.get_catalog_units_path()

        logger.debug("[Database Query] Loading configs...")
        catalog_config = load_catalog_config(str(catalog_config_path))
        catalog_metadata = load_catalog_metadata(str(catalog_metadata_path))
        catalog_units_config = load_catalog_units(str(catalog_units_path))

        logger.info(f"[Database Query] Loaded {len(catalog_config)} catalog configs")

    except Exception as e:
        logger.error(f"[Database Query] Failed to load configs: {e}")
        # 只返回本节点更新的字段：error_log 是 Annotated[list, add]，
        # 返回整个 state 会把已累积的条目重复累加一次。
        return {
            "database_query_status": "failed",
            "database_sources": [],
            "database_records": [],
            "error_log": [{
                "node": "database_query",
                "error": f"Failed to load catalog configs: {str(e)}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }]
        }

    # Step 2: 提取星表标识符
    logger.info("[Database Query] Extracting catalog IDs from aliases...")
    catalog_ids = extract_catalog_ids(aliases, catalog_config)

    total_queries = sum(len(id_list) for id_list in catalog_ids.values())
    logger.info(f"[Database Query] Found {len(catalog_ids)} catalog types")
    logger.info(f"[Database Query] Total queries: {total_queries}")

    # Step 3: 配置 VizieR（多镜像 fallback，超时 10s）
    vizier_config = config.api['vizier']
    row_limit = vizier_config['row_limit']
    timeout = vizier_config.get('timeout', 30)

    # Step 4: 顺序查询
    database_sources = []
    database_records = []
    successful_catalogs = []
    failed_catalogs = []

    current_q = 0

    for cat_key, id_list in catalog_ids.items():
        for id_info in id_list:
            current_q += 1

            # 更新进度
            state["catalog_progress"] = {
                "completed": current_q - 1,
                "total": total_queries,
                "current_catalog": id_info['catalog_name']
            }

            logger.info(f"[Database Query] [{current_q}/{total_queries}] Querying {id_info['catalog_name']}")
            logger.debug(f"[Database Query]   Table: {id_info['vizier_table']}")
            logger.debug(f"[Database Query]   Key: {id_info['key_column']}={id_info['id']}")

            try:
                # 执行 VizieR 查询（带镜像 fallback）
                cat_result = query_with_fallback(
                    lambda v: v.query_constraints(
                        catalog=id_info['vizier_table'],
                        **{id_info['key_column']: id_info['id']}
                    ),
                    row_limit=row_limit,
                    timeout=min(timeout, 10),
                )

                if cat_result and len(cat_result) > 0:
                    table = cat_result[0]

                    logger.debug(f"[Database Query]   Result: {len(table)} rows, {len(table.colnames)} columns")

                    # 添加 source（只添加一次）
                    if cat_key not in successful_catalogs:
                        source = build_database_source(cat_key, catalog_metadata)
                        if source:
                            database_sources.append(source)
                            successful_catalogs.append(cat_key)
                            logger.debug(f"[Database Query]   Added source: {source['source_id']}")

                    # LLM 映射列名到标准性质名（只在有 PropertySpec 时执行）
                    # None → 无白名单，原始列名兜底；{} → 有白名单但无匹配，产出 0 条（D1 fix）
                    column_mapping = None
                    if property_spec:
                        # 构造列元数据
                        columns_meta = []
                        for col_name in table.colnames:
                            if col_name == id_info['key_column']:
                                continue  # 跳过主键列
                            col_meta = {
                                "name": col_name,
                                "unit": catalog_units_config.get(cat_key, {}).get(col_name, ""),
                                "ucd": table[col_name].meta.get("ucd", ""),
                                "description": table[col_name].meta.get("description", ""),
                            }
                            columns_meta.append(col_meta)

                        # 调用 LLM 映射
                        try:
                            llm_client = get_llm_client()
                            column_mapping = map_columns_to_properties(
                                vizier_table=id_info['vizier_table'],
                                columns_meta=columns_meta,
                                property_spec=property_spec,
                                llm_client=llm_client,
                            )
                            logger.debug(f"[Database Query]   Column mapping: {len(column_mapping)} 列有映射")
                        except Exception as map_exc:
                            logger.warning(f"[Database Query]   列名映射失败: {map_exc}")
                            # 映射失败不阻塞：置空映射（有白名单但无匹配 → 产出 0 条）
                            column_mapping = {}

                    # 添加 records（每个列一条record）
                    units_map = catalog_units_config.get(cat_key, {})

                    records = build_database_records(
                        table=table,
                        source_id=catalog_metadata[cat_key]['source_id'],
                        target_entity=target_entity,
                        id_info=id_info,
                        catalog_units=units_map,
                        entity_type=simbad_info.get("otype") or state.get("simbad_object_type") or "Unknown",
                        column_mapping=column_mapping,  # 新增参数
                    )
                    database_records.extend(records)

                    logger.info(f"[Database Query]   ✓ Success: {len(records)} records extracted")
                else:
                    logger.warning("[Database Query]   ✗ No data found")

            except Exception as e:
                error_msg = str(e)
                logger.warning(f"[Database Query]   ✗ Failed: {error_msg}")
                if id_info['catalog_name'] not in failed_catalogs:
                    failed_catalogs.append(id_info['catalog_name'])

            # 限流保护
            time.sleep(vizier_config['rate_limit_delay'])

    # Step 5: 更新状态
    state["database_query_status"] = "completed"
    state["database_sources"] = database_sources
    state["database_records"] = database_records
    state["successful_catalogs"] = successful_catalogs
    state["failed_catalogs"] = failed_catalogs

    state["catalog_progress"] = {
        "completed": total_queries,
        "total": total_queries,
        "current_catalog": "Completed"
    }

    logger.info("[Database Query] Completed!")
    logger.info(f"[Database Query]   Sources: {len(database_sources)}")
    logger.info(f"[Database Query]   Records: {len(database_records)}")
    logger.info(f"[Database Query]   Successful catalogs: {len(successful_catalogs)}")
    logger.info(f"[Database Query]   Failed catalogs: {len(failed_catalogs)}")

    # 只返回更新的字段
    return {
        "database_query_status": state.get("database_query_status"),
        "database_sources": state.get("database_sources", []),
        "database_records": state.get("database_records", []),
        "successful_catalogs": state.get("successful_catalogs", []),
        "failed_catalogs": state.get("failed_catalogs", []),
        "catalog_progress": state.get("catalog_progress", {})
    }
