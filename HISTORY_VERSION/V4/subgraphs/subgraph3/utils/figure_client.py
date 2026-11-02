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
    return f"""你是天文学文献版面与科学图表分析专家。请分析给定的论文页面图片，检测科学图表并严格判断与用户查询的相关性。

## 用户查询
- 目标天体: {target_entity}
- 关注性质: {props}

---

## 阶段一：快速短路排查（无图/非目标页立即退出）
在进行深度分析前，先对整页进行 1 秒宏观扫视：
- 如果本页属于以下情况：
  1. **纯文字页、参考文献页、目录页**；
  2. **仅包含表格（Tables，带有行列网格线、数据列表、排版框的纯文字/数值表一律不算图）**；
  3. **仅包含数学公式块（Equations）**；
  4. **页面内没有任何科学图表或天文观测图像**。
👉 **立即终止后续思考，直接输出空结果：{{"page": 页码, "figures": []}}**。

---

## 阶段二：含图页面的思维链分析（仅在确认页面有科学图表时执行）

### 1. 目标图表筛选（严格排除表格）
- **必须提取的正例**：
  * 天文观测图像（CCD/FITS 曝光图、多波段合成图、射电等高线图、空间分布图）
  * 科学数据图表（色-星等图 CMD、光变曲线、能谱 SED、光谱图、拟合曲线、散点图、直方图）
  * 仪器与几何模型示意图（Diagrams）
- **严禁提取**：任何形式的表格（Table）、段落文本框。

### 2. 深入推理顺序（请按此顺序在脑中思考，并按此顺序生成字段）
1. **提取图注（caption）**：找到图表对应的 "Fig." 或 "Figure" 说明文字，完整提取图注文本。
2. **理解内容（description）**：简述该图核心画了什么物理参量、坐标系或天体图像。
3. **相关性裁决（is_relevant & reason）**：
   - `is_relevant: true` 必须同时满足：① 图表核心展示目标天体本身（{target_entity}）；② 图中直接呈现了与关注性质（{props}）相关的物理数据、曲线、光谱或观测图。
   - 若仅为非目标天体/对照星、无性质数据的纯寻星图、或与关注性质无关，一律判定 `is_relevant: false`，并在 `reason` 中说明具体排除理由。
4. **多面板合并与几何定界（bbox）**：
   - 多面板组合图（如包含子图 (a), (b), (c)）必须**合并为一张大图整体框选**，不得拆碎。
   - BBox 必须完整覆盖：**全部绘图区 + 四周所有坐标轴及刻度标签 + 图例（Legend） + 色彩标尺（Colorbar） + 图注说明文字**。
   - 坐标按 0-1000 归一化，格式为 `[x_min, y_min, x_max, y_max]`（左上原点，确保 x_min < x_max 且 y_min < y_max）。

---

## 输出格式（严格标准 JSON，不要 markdown 围栏，不要任何额外解释）
{{"page": 页码, "figures": [{{"bbox": [x_min, y_min, x_max, y_max], "caption": "图注原文", "description": "简要内容描述", "is_relevant": true, "reason": "判定理由"}}]}}

若本页无图、只有表格或不含任何科学图表，直接输出：
{{"page": 页码, "figures": []}}"""


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
