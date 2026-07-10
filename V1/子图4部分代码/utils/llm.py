"""
utils/llm.py

LLM 工厂模块 — 统一管理 LangChain ChatModel 实例。

支持 OpenAI 兼容接口（GPT-4o / DeepSeek / 本地模型等）。
配置从 configs/llm_config.yaml 读取。

结构化输出策略:
  1. method="function_calling" → 适用于 DeepSeek 等支持 tool calling 的模型
  2. method="json_schema"     → 适用于 OpenAI GPT-4o 等支持 response_format 的模型
  3. 回退: PydanticOutputParser → 通过 Prompt 要求 JSON + 手动解析 (适用于任何模型)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional, Type

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from configs import load_yaml
from utils.logger import get_logger

logger = get_logger(__name__)

# 缓存
_llm_instance: Optional[ChatOpenAI] = None
_config_cache: Optional[dict] = None

# ==========================================================
# LLM 调用统计
# ==========================================================

_stats: dict = {
    "total_calls": 0,           # 总调用次数（含重试）
    "success_calls": 0,         # 成功次数（首次策略成功）
    "fallback_calls": 0,        # 回退次数（策略1失败，用策略2/3成功）
    "failed_calls": 0,          # 全部策略失败次数
    "total_time_seconds": 0.0,  # 总耗时（含所有重试和回退）
    "total_thinking_seconds": 0.0,  # LLM 思考耗时（不含本地处理）
    "per_agent_calls": {},      # 按 agent 分组的调用次数 {agent_name: count}
    "per_agent_time": {},       # 按 agent 分组的耗时 {agent_name: seconds}
    "call_log": [],             # 每次调用的详细日志
}

_current_agent: str = "unknown"


def _load_config() -> dict:
    """加载 LLM 配置（带缓存）。"""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_yaml("llm_config.yaml")
        if not _config_cache:
            logger.warning("llm_config.yaml 为空或不存在，使用默认配置。")
            _config_cache = {
                "model": "gpt-4o",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "base_url": os.environ.get("OPENAI_BASE_URL", ""),
                "temperature": 0.0,
                "max_tokens": 4096,
                "timeout": 120,
                "max_retries": 3,
            }
    return _config_cache


def get_llm(
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    force_reload: bool = False,
) -> ChatOpenAI:
    """
    获取 LangChain ChatOpenAI 实例（单例模式）。

    Args:
        temperature: 覆盖配置中的温度。None 则使用配置值。
        max_tokens: 覆盖最大 token 数。None 则使用配置值。
        force_reload: 强制重新创建实例。

    Returns:
        ChatOpenAI 实例。
    """
    global _llm_instance

    if _llm_instance is not None and not force_reload:
        return _llm_instance

    config = _load_config()

    api_key = config.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = config.get("base_url", "") or os.environ.get("OPENAI_BASE_URL", "")

    if not api_key:
        logger.warning(
            "LLM API Key 未配置！请在 configs/llm_config.yaml 中设置 api_key，"
            "或设置环境变量 OPENAI_API_KEY。"
        )

    kwargs = {
        "model": config.get("model", "gpt-4o"),
        "api_key": api_key,
        "temperature": temperature if temperature is not None else config.get("temperature", 0.0),
        "max_tokens": max_tokens or config.get("max_tokens", 4096),
        "timeout": config.get("timeout", 120),
        "max_retries": config.get("max_retries", 3),
    }

    if base_url:
        kwargs["base_url"] = base_url

    _llm_instance = ChatOpenAI(**kwargs)

    logger.info("LLM 初始化完成: model=%s, temperature=%.1f, base_url=%s",
                kwargs["model"], kwargs["temperature"],
                base_url if base_url else "(OpenAI default)")

    return _llm_instance


# ==========================================================
# 结构化输出
# ==========================================================

class StructuredLLM:
    """
    结构化输出 LLM 包装器。

    自动选择最佳策略:
      1. function_calling (DeepSeek / 大多数模型支持)
      2. json_schema (OpenAI GPT-4o 支持)
      3. PydanticOutputParser (兜底，任何模型都支持)
    """

    def __init__(self, llm: ChatOpenAI, output_schema: Type[BaseModel]):
        self.llm = llm
        self.output_schema = output_schema
        self.parser = PydanticOutputParser(pydantic_object=output_schema)
        self._backend = None  # 延迟初始化

    def invoke(self, messages: list[dict]) -> BaseModel:
        """
        调用 LLM 并返回结构化输出。

        Args:
            messages: [{"role": "system", "content": "..."},
                       {"role": "user", "content": "..."}]

        Returns:
            Pydantic BaseModel 实例。
        """
        t_start = time.time()
        agent = _current_agent

        # 读取配置的方法偏好
        config = _load_config()
        preferred_method = config.get("structured_output_method", "auto")

        # ── 策略 1: function_calling ──
        if preferred_method in ("auto", "function_calling"):
            try:
                t_call = time.time()
                result = self._invoke_with_function_calling(messages)
                thinking_time = time.time() - t_call
                _record_success(agent, thinking_time, "function_calling")
                return result
            except Exception as e1:
                logger.debug("function_calling 失败 (%s)", _short_error(e1))

        # ── 策略 2: json_schema ──
        if preferred_method in ("auto", "json_schema"):
            try:
                t_call = time.time()
                result = self._invoke_with_json_schema(messages)
                thinking_time = time.time() - t_call
                _record_fallback(agent, thinking_time, "json_schema (fallback)")
                return result
            except Exception as e2:
                logger.debug("json_schema 失败 (%s)", _short_error(e2))

        # ── 策略 3: Prompt + PydanticOutputParser ──
        try:
            t_call = time.time()
            result = self._invoke_with_prompt_parsing(messages)
            thinking_time = time.time() - t_call
            strategy_used = "prompt_parsing (fallback)"
            _record_fallback(agent, thinking_time, strategy_used)
            return result
        except Exception as e3:
            thinking_time = time.time() - t_start
            _record_failed(agent, thinking_time, str(e3))
            raise

    def _invoke_with_function_calling(self, messages: list[dict]) -> BaseModel:
        """使用 function calling 获取结构化输出（DeepSeek 支持）。"""
        structured_llm = self.llm.with_structured_output(
            self.output_schema,
            method="function_calling",
        )
        result = structured_llm.invoke(messages)
        if isinstance(result, dict):
            return self.output_schema.model_validate(result)
        return result

    def _invoke_with_json_schema(self, messages: list[dict]) -> BaseModel:
        """使用 response_format json_schema 获取结构化输出（OpenAI 支持）。"""
        structured_llm = self.llm.with_structured_output(
            self.output_schema,
            method="json_schema",
        )
        result = structured_llm.invoke(messages)
        if isinstance(result, dict):
            return self.output_schema.model_validate(result)
        return result

    def _invoke_with_prompt_parsing(self, messages: list[dict]) -> BaseModel:
        """
        兜底方案：通过 Prompt 要求 LLM 输出 JSON，再手动解析。

        适用于不支持 function calling / json_schema 的模型。
        """
        modified = list(messages)

        # 添加 JSON 格式指令
        format_instructions = self.parser.get_format_instructions()

        if modified and modified[0].get("role") == "system":
            modified[0] = {
                "role": "system",
                "content": modified[0]["content"] + "\n\n" + format_instructions,
            }
        else:
            modified.insert(0, {
                "role": "system",
                "content": format_instructions,
            })

        response = self.llm.invoke(modified)
        content = response.content if hasattr(response, "content") else str(response)

        # 尝试提取 JSON（支持 ```json ... ``` 代码块）
        json_str = _extract_json(content)

        try:
            data = json.loads(json_str)
            return self.output_schema.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Prompt JSON 解析失败: %s\n原始响应: %s...", e, content[:300])
            raise


def get_structured_llm(
    output_schema: Type[BaseModel],
    temperature: Optional[float] = None,
) -> StructuredLLM:
    """
    获取带结构化输出的 LLM 包装器。

    自动选择最佳策略:
      - 优先: function_calling (DeepSeek / 大多数模型)
      - 次选: json_schema (OpenAI)
      - 兜底: Prompt JSON 解析 (任何模型)

    Args:
        output_schema: Pydantic v2 BaseModel 子类。
        temperature: 温度，默认 0.0。

    Returns:
        StructuredLLM 实例，调用 .invoke(messages) 返回 Pydantic 对象。

    Usage:
        class MyOutput(BaseModel):
            reason: str
            score: float

        llm = get_structured_llm(MyOutput)
        result: MyOutput = llm.invoke([
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
        ])
    """
    llm = get_llm(temperature=temperature if temperature is not None else 0.0)
    return StructuredLLM(llm, output_schema)


# ==========================================================
# Helpers
# ==========================================================

def _extract_json(text: str) -> str:
    """从 LLM 响应中提取 JSON 字符串。"""
    # 尝试提取 ```json ... ``` 代码块
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()

    # 尝试提取 { ... } 最外层
    brace_start = text.find('{')
    brace_end = text.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        return text[brace_start:brace_end + 1]

    # 回退到原始文本
    return text.strip()


def _short_error(e: Exception) -> str:
    """截取异常信息的前 80 字符。"""
    msg = str(e)
    return msg[:80] + "..." if len(msg) > 80 else msg


def reset_llm():
    """重置 LLM 实例缓存（配置变更后使用）。"""
    global _llm_instance, _config_cache
    _llm_instance = None
    _config_cache = None
    logger.info("LLM 实例缓存已重置。")


# ==========================================================
# 调用统计 API
# ==========================================================

def set_agent_context(agent_name: str):
    """设置当前 LLM 调用所属的 Agent 名称（供统计分组）。"""
    global _current_agent
    _current_agent = agent_name


def _record_success(agent: str, thinking_time: float, strategy: str):
    """记录一次成功的 LLM 调用。"""
    _stats["total_calls"] += 1
    _stats["success_calls"] += 1
    _stats["total_time_seconds"] += thinking_time
    _stats["total_thinking_seconds"] += thinking_time
    _stats["per_agent_calls"][agent] = _stats["per_agent_calls"].get(agent, 0) + 1
    _stats["per_agent_time"][agent] = _stats["per_agent_time"].get(agent, 0.0) + thinking_time
    _stats["call_log"].append({
        "agent": agent, "success": True, "strategy": strategy,
        "thinking_time": round(thinking_time, 3),
    })
    logger.info("[LLM Stats] %s | %s | %.2fs", agent, strategy, thinking_time)


def _record_fallback(agent: str, thinking_time: float, strategy: str):
    """记录一次回退成功的 LLM 调用。"""
    _stats["total_calls"] += 1
    _stats["fallback_calls"] += 1
    _stats["total_time_seconds"] += thinking_time
    _stats["total_thinking_seconds"] += thinking_time
    _stats["per_agent_calls"][agent] = _stats["per_agent_calls"].get(agent, 0) + 1
    _stats["per_agent_time"][agent] = _stats["per_agent_time"].get(agent, 0.0) + thinking_time
    _stats["call_log"].append({
        "agent": agent, "success": True, "strategy": strategy,
        "thinking_time": round(thinking_time, 3), "fallback": True,
    })
    logger.warning("[LLM Stats] %s | %s | %.2fs (回退)", agent, strategy, thinking_time)


def _record_failed(agent: str, elapsed: float, error: str):
    """记录一次完全失败的 LLM 调用。"""
    _stats["total_calls"] += 1
    _stats["failed_calls"] += 1
    _stats["total_time_seconds"] += elapsed
    _stats["per_agent_calls"][agent] = _stats["per_agent_calls"].get(agent, 0) + 1
    _stats["per_agent_time"][agent] = _stats["per_agent_time"].get(agent, 0.0) + elapsed
    _stats["call_log"].append({
        "agent": agent, "success": False, "strategy": "all_failed",
        "thinking_time": round(elapsed, 3), "error": _short_error_str(error),
    })
    logger.error("[LLM Stats] %s | ALL FAILED | %.2fs | %s", agent, elapsed, _short_error_str(error))


def get_llm_stats() -> dict:
    """获取 LLM 调用统计摘要。"""
    s = dict(_stats)
    s["per_agent_calls"] = dict(s["per_agent_calls"])
    s["per_agent_time"] = dict(s["per_agent_time"])
    if s["total_calls"] > 0:
        s["avg_thinking_time"] = round(s["total_thinking_seconds"] / s["total_calls"], 3)
        s["success_rate"] = round((s["success_calls"] + s["fallback_calls"]) / s["total_calls"] * 100, 1)
        s["first_strategy_rate"] = round(s["success_calls"] / s["total_calls"] * 100, 1)
    else:
        s["avg_thinking_time"] = 0.0
        s["success_rate"] = 0.0
        s["first_strategy_rate"] = 0.0
    return s


def reset_llm_stats():
    """重置 LLM 调用统计。"""
    global _stats
    _stats = {
        "total_calls": 0, "success_calls": 0, "fallback_calls": 0,
        "failed_calls": 0, "total_time_seconds": 0.0,
        "total_thinking_seconds": 0.0,
        "per_agent_calls": {}, "per_agent_time": {}, "call_log": [],
    }
    logger.info("LLM 调用统计已重置。")


def print_llm_stats():
    """打印格式化的 LLM 调用统计。"""
    s = get_llm_stats()
    print(f"\n{'='*60}")
    print(f"  LLM 调用统计")
    print(f"{'='*60}")
    print(f"  总调用次数:    {s['total_calls']}")
    print(f"  首次策略成功:  {s['success_calls']}")
    print(f"  回退后成功:    {s['fallback_calls']}")
    print(f"  全部失败:      {s['failed_calls']}")
    print(f"  成功率:        {s['success_rate']}%")
    print(f"  总耗时:        {s['total_time_seconds']:.2f}s")
    print(f"  总思考耗时:    {s['total_thinking_seconds']:.2f}s")
    print(f"  平均思考/调用: {s['avg_thinking_time']:.3f}s")
    if s["per_agent_calls"]:
        print(f"\n  按 Agent 分组:")
        for agent in sorted(s["per_agent_calls"].keys()):
            calls = s["per_agent_calls"][agent]
            t = s["per_agent_time"].get(agent, 0.0)
            avg = t / calls if calls > 0 else 0
            print(f"    {agent}: {calls} 次, 耗时 {t:.2f}s, 平均 {avg:.3f}s/次")
    print(f"{'='*60}")


def track_raw_llm_call(elapsed: float, agent: str | None = None):
    """记录一次原始 (非 structured) LLM 调用。"""
    agent_name = agent or _current_agent or "unknown"
    _stats["total_calls"] += 1
    _stats["success_calls"] += 1
    _stats["total_time_seconds"] += elapsed
    _stats["total_thinking_seconds"] += elapsed
    _stats["per_agent_calls"][agent_name] = _stats["per_agent_calls"].get(agent_name, 0) + 1
    _stats["per_agent_time"][agent_name] = _stats["per_agent_time"].get(agent_name, 0.0) + elapsed
    _stats["call_log"].append({
        "agent": agent_name, "success": True, "strategy": "raw_llm",
        "thinking_time": round(elapsed, 3),
    })
    logger.info("[LLM Stats] %s | raw_llm | %.2fs", agent_name, elapsed)


def _short_error_str(msg: str) -> str:
    return msg[:80] + "..." if len(msg) > 80 else msg
