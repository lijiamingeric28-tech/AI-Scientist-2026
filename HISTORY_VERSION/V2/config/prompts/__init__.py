"""
Prompt模板定义

包含意图澄清子图和检索子图的所有Prompt模板
"""

# ========== Agent A: Evaluate_Intent ==========

SCHEMA_GENERATION_PROMPT = """
你是科学数据查询的意图分析专家。用户的查询是：
"{query}"

领域：{domain}

请分析这个查询，生成一个槽位检查清单（slot schema）。

必须严格按照以下JSON格式返回：
{{
  "entities": {{
    "required": true,
    "description": "目标实体（材料、天体、化合物等）",
    "examples": ["Al-7075", "超新星", "化合物X"],
    "filled": false
  }},
  "properties": {{
    "required": true,
    "description": "目标属性（力学性能、物理常数等）",
    "examples": ["屈服强度", "光变曲线", "熔点"],
    "filled": false
  }},
  "conditions": {{
    "required": false,
    "description": "约束条件（温度范围、时间范围等）",
    "examples": ["200-400°C", "2015-2025年"],
    "filled": false
  }}
}}

注意：
1. 每个槽位必须包含：required（布尔值）、description（字符串）、examples（数组）、filled（布尔值）
2. 根据查询的复杂度，判断每个槽位是否必填（required）
3. 只返回JSON，不要其他文字
"""

EXTRACTION_PROMPT = """
用户的原始查询："{query}"

对话历史：
{chat_history}

槽位清单：
{schema}

当前已提取参数：
{current_params}

请从查询和对话历史中提取信息，更新参数。只提取明确提到的信息，不要猜测。

必须严格按照以下JSON格式返回：
{{
  "entities": ["实体1", "实体2"],
  "properties": ["属性1", "属性2"],
  "conditions": {{"温度": "200-400°C", "年份": "2015-2025"}}
}}

注意：
1. entities和properties必须是数组（即使只有一个元素）
2. conditions必须是对象（键值对）
3. 如果某个槽位没有信息，返回空数组[]或空对象{{}}
4. 只返回JSON，不要其他文字
"""

FORCE_FILL_PROMPT = """
用户的原始查询："{query}"

槽位清单：
{schema}

当前已提取参数：
{current_params}

缺失的必填项：
{missing_slots}

用户已经被追问3次，但仍无法提供完整信息。请你根据查询内容和上下文，对缺失的必填项进行合理推测填充。

要求：
1. 尽量基于查询内容推测
2. 如果完全无法推测，使用通用值（如"material"、"general properties"）
3. 保持已填充的参数不变

输出JSON格式的完整extracted_parameters。
"""

# ========== Agent B: Ask_User_Guided ==========

CLARIFICATION_PROMPT = """
你是科学数据查询的交互助手。用户的原始查询是：
"{query}"

当前已提取的参数：
{current_params}

槽位检查清单：
{schema}

缺失的信息：
{missing_slots}

请生成一个友好的追问，帮助用户补充缺失信息。要求：
1. 问题要具体、引导性强
2. 如果可能，提供2-4个常见选项供用户选择
3. 使用用户友好的语言，避免技术术语

输出JSON格式：
{{
    "question": "您的追问文本",
    "options": ["选项1", "选项2", ...]
}}
"""

PARSE_RESPONSE_PROMPT = """
你是对话理解助手。用户刚才被问：
"{question}"

提供的选项：
{options}

用户的回答：
"{user_input}"

请理解用户的意图，将回答规范化为清晰的文本。要求：
1. 如果用户选择了某个选项（如"1"、"A"、"第一个"、"Ia型"），返回对应选项的完整文本
2. 如果用户自由输入（未选择选项），提取关键信息并规范化
3. 如果回答不明确或无关，返回原文本

只输出规范化后的文本，不要解释。

示例：
- 用户输入"1" -> 输出"Ia型"
- 用户输入"我要第二个" -> 输出"II型"
- 用户输入"Ia" -> 输出"Ia型"
- 用户输入"200到300度" -> 输出"200-300°C"
"""

# ========== Agent C: Confirm_Intent ==========

MODIFICATION_PROMPT = """
你是参数修改助手。当前的查询参数是：
{current_params}

用户的输入是：
"{user_input}"

请判断用户的意图，并执行相应操作：

1. **确认（confirm）**：用户表示接受当前参数
   - 关键词："确认"、"ok"、"没问题"、"可以"、"继续"
   - 返回：action="confirm", updated_params=当前参数

2. **修改（modify）**：用户要求修改某些参数
   - 示例："把温度改成300-500°C"、"再加一个延伸率"、"去掉year条件"
   - 返回：action="modify", updated_params=修改后的参数

3. **拒绝（reject）**：用户不满意，想重新开始
   - 关键词："拒绝"、"重新开始"、"不对"、"取消"
   - 返回：action="reject", updated_params=空字典

输出JSON格式：
{{
    "action": "confirm/modify/reject",
    "updated_params": {{...}}
}}
"""

# ========== 检索子图Prompt（子图2） ==========
# 检索子图的Prompt定义在独立文件中
from . import retrieval

# ========== 提取子图Prompt（子图3） ==========
# 提取子图的Prompt定义在独立文件中
from . import extraction
