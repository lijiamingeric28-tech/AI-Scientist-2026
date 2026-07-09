"""
全局常量定义
"""

# ========== 意图澄清子图 ==========

# 默认槽位Schema（generate_schema失败时使用）
DEFAULT_SCHEMA = {
    "entities": {
        "required": True,
        "description": "目标实体（材料、天体、化合物等）",
        "examples": [],
        "filled": False
    },
    "properties": {
        "required": True,
        "description": "目标属性（力学性能、物理常数等）",
        "examples": [],
        "filled": False
    },
    "conditions": {
        "required": False,
        "description": "约束条件（温度范围、时间范围、实验类型等）",
        "examples": [],
        "filled": False
    }
}

# 最大追问轮次
MAX_CLARIFICATION_TURNS = 3

# ========== LLM配置 ==========

# 模型选择
DEFAULT_MODEL = "qwen3.7-plus"
FAST_MODEL = "qwen-turbo"    # 用于简单任务
SMART_MODEL = "qwen-max"     # 用于复杂推理

# 超时配置
DEFAULT_TIMEOUT = 60  # 秒（增加到60秒）
LONG_TIMEOUT = 120     # 复杂任务

# 温度配置
LOW_TEMP = 0.1    # 确定性任务（如格式化、解析）
MID_TEMP = 0.5    # 平衡任务（如提取、推理）
HIGH_TEMP = 0.9   # 创意任务（如生成变体）
