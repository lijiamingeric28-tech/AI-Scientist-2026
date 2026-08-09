"""页面图检测 VLM 客户端 — 检测图表位置 + 判断与查询的相关性

独立于数据提取通路（数据提取 VLM 明确忽略图片）：
本客户端专门分析论文页面图片，找出其中的图表区域（bbox），
并判断每张图与用户查询（天体 + 性质）的相关性——供前端直接展示原始论文证据。
"""

import base64
import json
import time
from io import BytesIO
from typing import Dict, List, Optional

import dashscope
from dashscope import MultiModalConversation
from PIL import Image

from ..config.settings import settings
from .logger import get_logger

logger = get_logger(__name__)


def build_figure_detect_prompt(
    target_entity: str,
    property_spec: List[Dict],
) -> str:
    """构建页面图检测 + 相关性判断 prompt

    相关性锚点 = P1 标准化的 PropertySpec（name_cn 优先，property_id 兜底），
    与数据提取链路同源——figure 通路同样归一化到 PropertySpec。
    """
    if property_spec:
        props = ", ".join(
            p.get("name_cn") or p.get("property_id", "")
            for p in property_spec
        )
    else:
        props = "（未指定具体性质，判断图中是否展示该天体的任何物理数据）"
    return f"""你是天文学论文图表分析专家。分析给定的论文页面图片，找出其中所有图表，并判断哪些与用户查询相关。

## 用户查询
目标天体: {target_entity}
关注性质: {props}

## 任务
对页面中的每一张图（图表、图像、照片），输出：
1. **bbox**: 图在页面中的位置 [x_min, y_min, x_max, y_max]，坐标系为 0-1000 归一化（左上角原点）
2. **caption**: 图注文本（如 "Fig. 1. ..."），页面文字中含图注则原样给出，否则简述图的内容
3. **description**: 图的简短内容描述（这张图画了什么）
4. **is_relevant**: 该图是否与用户查询（天体 + 性质）相关
5. **relevance**: "high" | "medium" | "low"
6. **relevance_reason**: 相关性判断的一句话理由

## 规则
- 页面中可能有多张图，全部列出；没有图则返回空数组
- 只识别页面中明显独立的图表区域，不要把正文小插图、logo、页眉页脚算作图
- 相关性判断（宁缺毋滥——不确定时判为不相关）：
  - high: 图直接展示目标天体的数值数据——含该天体数据的光变曲线、光谱、图像、表格图，且与关注性质（星等、距离）直接相关
  - medium: 与目标天体或其性质相关，但不是直接数据展示（如多天体对比图、示意性图表）
  - low: 边缘相关（背景图、性质弱相关的图）
  - 不相关: 目标天体以外的内容、仪器/设备照片、流程图、作者照片、与关注性质无关的图 → is_relevant=false
- 宁可漏报，不可滥报：不确定某图是否相关时，判 is_relevant=false

输出严格 JSON：
{{"page": 页码, "figures": [{{"bbox": [...], "caption": "...", "description": "...", "is_relevant": true/false, "relevance": "high", "relevance_reason": "..."}}]}}"""


def call_qwen_figure_detect(
    image: Image.Image,
    page: int,
    target_entity: str,
    property_spec: List[Dict],
    max_retries: int = 3,
) -> Optional[Dict]:
    """调用 qwen3.7-flash 检测单页图片中的图表并判断相关性。

    Args:
        image: 页面渲染图（PIL Image）
        page: 页码（1-based）
        target_entity: 目标天体
        property_spec: P1 标准化的 PropertySpec（相关性判断锚点）
        max_retries: 限流/错误重试次数

    Returns:
        {"page": int, "figures": [...]} 或 None（全部失败）
    """
    prompt = build_figure_detect_prompt(target_entity, property_spec)
    # 与 bbox 同款模型（qwen3.7-flash）：便宜，100 并发已验证不触限流
    model = settings.bbox_vlm.model

    dashscope.api_key = settings.vlm.api_key

    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"image": f"data:image/png;base64,{img_base64}"},
            {"text": prompt},
        ],
    }]

    for attempt in range(1, max_retries + 1):
        try:
            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                temperature=0.0,  # 检测/判断需要确定性
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            if response.status_code == 200:
                result = response.output.choices[0].message.content
                data = _coerce_to_dict(result)
                if data:
                    data["page"] = page
                    return data
                logger.warning(f"[FigureDetect] 解析失败 (page {page}): {str(result)[:100]!r}")
                return None

            # 限流：指数退避重试
            elif hasattr(response, "code") and response.code in [
                "Throttling.RateQuota",
                "FlowControl.User",
                "FlowControl.System",
                429,
            ]:
                if attempt < max_retries:
                    wait = (2 ** (attempt - 1)) * 2
                    logger.warning(f"[FigureDetect] 限流，{wait}s 后重试 (attempt {attempt})...")
                    time.sleep(wait)
                    continue
                return None

            else:
                logger.error(
                    f"[FigureDetect] API error: {getattr(response, 'code', '?')} "
                    f"- {getattr(response, 'message', '?')}"
                )
                return None

        except Exception as e:
            logger.warning(f"[FigureDetect] 调用失败 (attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** (attempt - 1))

    return None


def _coerce_to_dict(data, depth: int = 0) -> Optional[dict]:
    """递归归一化 DashScope 多态返回 → dict（与 bbox_vlm_client 同款）"""
    if depth > 6:
        return None
    if isinstance(data, dict):
        if "text" in data and isinstance(data["text"], str):
            try:
                inner = json.loads(data["text"])
                if isinstance(inner, dict):
                    return inner
                if isinstance(inner, list) and inner:
                    return _coerce_to_dict(inner[0], depth + 1)
            except (json.JSONDecodeError, TypeError):
                pass
        return data
    if isinstance(data, str):
        try:
            return _coerce_to_dict(json.loads(data), depth + 1)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(data, list):
        if not data:
            return None
        return _coerce_to_dict(data[0], depth + 1)
    return None
