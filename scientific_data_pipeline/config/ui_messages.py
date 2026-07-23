"""
UI交互消息配置

包含意图澄清子图中所有用户交互的提示文本
"""

# ========== 通用UI元素 ==========

SEPARATOR_LINE = "=" * 60
"""分隔线，用于视觉区分不同部分"""

NEWLINE_PREFIX = "\n"
"""换行前缀"""

# ========== Agent B: 追问交互 ==========

ASK_USER_INPUT_PROMPT = ">>> 请输入您的回答："
"""Agent B等待用户输入的提示文本"""

ASK_USER_WAITING_MESSAGE = "等待用户回答..."
"""Agent B等待状态的日志消息"""

# ========== Agent C: 确认交互 ==========

CONFIRM_INPUT_PROMPT = ">>> 请输入您的操作（确认/修改/拒绝）："
"""Agent C等待用户操作的提示文本"""

CONFIRM_WAITING_MESSAGE = "等待用户确认..."
"""Agent C等待状态的日志消息"""

# ========== 确认表单文本 ==========

CONFIRMATION_TITLE = "# 请确认您的查询意图\n\n"
"""确认表单的主标题"""

CONFIRMATION_ORIGINAL_QUERY_LABEL = "**原始查询：**"
"""原始查询的标签"""

CONFIRMATION_PARAMS_HEADER = "## 提取的参数\n\n"
"""参数部分的标题"""

CONFIRMATION_ENTITIES_HEADER = "### 目标实体（entities）\n"
"""实体部分的小标题"""

CONFIRMATION_PROPERTIES_HEADER = "### 目标属性（properties）\n"
"""属性部分的小标题"""

CONFIRMATION_CONDITIONS_HEADER = "### 约束条件（conditions）\n"
"""条件部分的小标题"""

CONFIRMATION_COMPROMISE_WARNING = "⚠️ **注意：** 部分参数为AI推测，请仔细核对。\n\n"
"""AI推测参数的警告信息"""

CONFIRMATION_INSTRUCTIONS_HEADER = "**操作说明：**\n"
"""操作说明的标题"""

CONFIRMATION_INSTRUCTIONS = """- 直接输入"确认"或"ok"继续
- 输入修改指令，如："把温度改成300-500°C"
- 输入"拒绝"或"重新开始"以放弃当前查询
"""
"""操作说明的具体内容"""

# ========== 关键词列表（用于兜底解析） ==========

CONFIRM_KEYWORDS = ["确认", "ok", "没问题", "可以", "继续", "yes"]
"""确认操作的关键词列表"""

REJECT_KEYWORDS = ["拒绝", "重新", "不对", "取消", "no"]
"""拒绝操作的关键词列表"""

# ========== 辅助函数 ==========

def format_list_items(items: list[str], prefix: str = "- ") -> str:
    """
    格式化列表项为Markdown格式

    Args:
        items: 项目列表
        prefix: 每项的前缀（默认为"- "）

    Returns:
        格式化后的字符串

    Example:
        >>> format_list_items(["item1", "item2"])
        "- item1\n- item2\n"
    """
    return "".join(f"{prefix}{item}\n" for item in items)


def format_dict_items(items: dict, prefix: str = "- ", separator: str = ": ") -> str:
    """
    格式化字典项为Markdown格式

    Args:
        items: 字典
        prefix: 每项的前缀（默认为"- "）
        separator: 键值分隔符（默认为": "）

    Returns:
        格式化后的字符串

    Example:
        >>> format_dict_items({"key1": "value1", "key2": "value2"})
        "- key1: value1\n- key2: value2\n"
    """
    return "".join(f"{prefix}{key}{separator}{value}\n" for key, value in items.items())


def build_confirmation_display(
    original_query: str,
    entities: list[str] = None,
    properties: list[str] = None,
    conditions: dict = None,
    compromise_flag: bool = False
) -> str:
    """
    构建完整的确认表单显示文本

    Args:
        original_query: 用户原始查询
        entities: 实体列表
        properties: 属性列表
        conditions: 条件字典
        compromise_flag: 是否包含AI推测

    Returns:
        完整的Markdown格式确认表单
    """
    display = CONFIRMATION_TITLE
    display += f"{CONFIRMATION_ORIGINAL_QUERY_LABEL} {original_query}\n\n"
    display += CONFIRMATION_PARAMS_HEADER

    if entities:
        display += CONFIRMATION_ENTITIES_HEADER
        display += format_list_items(entities)
        display += "\n"

    if properties:
        display += CONFIRMATION_PROPERTIES_HEADER
        display += format_list_items(properties)
        display += "\n"

    if conditions:
        display += CONFIRMATION_CONDITIONS_HEADER
        display += format_dict_items(conditions)
        display += "\n"

    if compromise_flag:
        display += CONFIRMATION_COMPROMISE_WARNING

    display += "---\n\n"
    display += CONFIRMATION_INSTRUCTIONS_HEADER
    display += CONFIRMATION_INSTRUCTIONS

    return display
