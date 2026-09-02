"""
工具：将extracted_parameters格式化为用户友好的确认表单
"""
import logging

logger = logging.getLogger(__name__)


def format_confirmation_display(
    params: dict,
    compromise_flag: bool,
    original_query: str,
    schema: dict = None
) -> str:
    """
    将extracted_parameters格式化为用户友好的确认表单展示文本

    Args:
        params: extracted_parameters
        compromise_flag: 是否包含AI推测
        original_query: 用户原始查询
        schema: 槽位检查清单（可选，用于字段说明）

    Returns:
        Markdown格式的展示文本

    Example:
        >>> format_confirmation_display(
        ...     {"entities": ["Al-7075"], "properties": ["yield_strength"]},
        ...     False,
        ...     "帮我找铝合金数据"
        ... )
    """
    display = "# 请确认您的查询意图\n\n"
    display += f"**原始查询：** {original_query}\n\n"
    display += "## 提取的参数\n\n"

    # 展示entities
    if params.get("entities"):
        display += "### 目标实体（entities）\n"
        for entity in params["entities"]:
            display += f"- {entity}\n"
        display += "\n"

    # 展示properties
    if params.get("properties"):
        display += "### 目标属性（properties）\n"
        for prop in params["properties"]:
            display += f"- {prop}\n"
        display += "\n"

    # 展示conditions
    if params.get("conditions"):
        display += "### 约束条件（conditions）\n"
        for key, value in params["conditions"].items():
            display += f"- {key}: {value}\n"
        display += "\n"

    # 警告标记
    if compromise_flag:
        display += "⚠️ **注意：** 部分参数为AI推测，请仔细核对。\n\n"

    # 操作说明
    display += "---\n\n"
    display += "**操作说明：**\n"
    display += "- 直接输入\"确认\"或\"ok\"继续\n"
    display += "- 输入修改指令，如：\"把温度改成300-500°C\"\n"
    display += "- 输入\"拒绝\"或\"重新开始\"以放弃当前查询\n"

    logger.debug(f"Formatted confirmation display with compromise_flag={compromise_flag}")

    return display
