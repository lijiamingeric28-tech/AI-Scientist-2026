"""
工具：检查必填槽位是否已全部填充
"""
import logging

logger = logging.getLogger(__name__)


def check_completeness(schema: dict, params: dict) -> tuple[bool, list[str]]:
    """
    检查必填槽位是否已全部填充

    Args:
        schema: 槽位检查清单
        params: 当前已提取参数

    Returns:
        (是否完整, 缺失的必填项列表)

    Example:
        >>> schema = {"entities": {"required": True}, "properties": {"required": True}}
        >>> params = {"entities": ["Al-7075"], "properties": []}
        >>> check_completeness(schema, params)
        (False, ["properties"])
    """
    missing = []

    # 容错处理：如果schema格式不正确，记录警告
    if not isinstance(schema, dict):
        logger.warning(f"Schema is not a dict: {type(schema)}, using default check")
        return False, ["entities", "properties"]

    for slot_name, slot_config in schema.items():
        # 容错：如果slot_config不是dict（可能是list或其他类型），跳过
        if not isinstance(slot_config, dict):
            logger.warning(f"Slot config for '{slot_name}' is not a dict: {type(slot_config)}, skipping")
            continue

        # 强制检查：entities 和 properties 必须必填，无论schema如何设置
        is_required = slot_config.get("required", False)
        if slot_name in ["entities", "properties"]:
            is_required = True
            logger.debug(f"Force {slot_name} to be required")

        if is_required:
            # 检查是否存在且非空
            if slot_name not in params or not params[slot_name]:
                missing.append(slot_name)

    is_complete = len(missing) == 0

    logger.debug(f"Completeness check: complete={is_complete}, missing={missing}")

    return is_complete, missing
