"""VLM API client for Qwen3.7-Plus (DashScope SDK)."""

import dashscope
from dashscope import MultiModalConversation
import base64
import time
from io import BytesIO
from typing import List
from PIL import Image
from ..config.settings import settings
from .logger import get_logger


logger = get_logger(__name__)


def build_extraction_prompt(
    target_entity: str,
    requested_properties: List[str],
    num_images: int = 0,
    property_spec: List[dict] = None
) -> str:
    """
    Build VLM extraction prompt with explicit page mapping (Macro-only/Whole-entity extraction).

    Args:
        target_entity: Target celestial object name (e.g., "M31")
        requested_properties: List of properties to extract (e.g., ["distance", "metallicity"])
        num_images: Number of images (for explicit page mapping)
        property_spec: PropertySpec 标准性质列表（约束 field_name 必须从中选取）
                      格式：[{property_id, name_cn, unit, ...}, ...]

    Returns:
        Complete prompt string with page mapping clarification
    """
    # 构造性质白名单指令
    if property_spec:
        # 使用 PropertySpec 构造白名单
        property_lines = []
        for p in property_spec:
            pid = p.get("property_id", "")
            name_cn = p.get("name_cn", "")
            unit = p.get("unit", "")
            desc = p.get("description", "")[:80]
            property_lines.append(f"  - {pid} ({name_cn}), 单位={unit}, {desc}")

        property_whitelist = "\n".join(property_lines)
        property_instruction = f"""请提取以下标准性质（field_name 必须使用列表中的 property_id）：
{property_whitelist}

**强制约束**：field_name 必须是上述列表中的 property_id，不得自由命名！"""
    elif requested_properties:
        # 降级：无 PropertySpec 时使用用户原始请求
        property_list = "、".join(requested_properties)
        property_instruction = f"请提取：{property_list} 相关性质"
    else:
        property_instruction = "请提取目标天体的所有宏观物理性质"

    # 页码防幻觉映射
    page_mapping_note = ""
    if num_images > 0:
        page_mapping_note = f"""
## 重要说明：图片顺序与页码对应关系
我将向你提供 **{num_images}张图片**，它们的顺序对应论文页码如下：
- 第1张图片 = page 1
- 第2张图片 = page 2
- ...
- 第{num_images}张图片 = page {num_images}

**请严格按照输入图片的顺序标注 page 字段，避免页码幻觉。**
"""

    prompt = f"""你是一个顶尖的天文学文献数据提取专家。我将按顺序向你展示一篇完整论文的所有页面图片。
{page_mapping_note}
## 🎯 任务目标
从论文中提取关于目标天体 **{target_entity}** 的物理性质数据。
提取指令：{property_instruction} (请自动识别论文中对应的具体物理指标名称)

## 🛑 核心提取铁律（违反将导致严重错误）

### 1. 锁定"宏观整体"，坚决忽略"微观局部" (降维减负指令)
- ✅ **提取**：只提取描述【{target_entity}】作为**一个整体（as a whole）**的物理属性（如整个星系的距离、总质量等）。
- ❌ **忽略**：绝对忽略目标天体内部的具体子结构、特定组成部分或局部区域（如：内部的具体球状星团、特定恒星、HII区等）。
- 🚨 **遇到罗列内部子结构数据的部分，请直接跳过，绝对不要提取这些细枝末节！**

### 2. 严格实体排他
- 绝不提取用来作为对比、校准或背景参考的其他天体的数据。

### 3. 确保数据物理真实性
- 绝不提取理论假设值、公式拟合用的"参考基准点 (reference value)"、"归一化常数"等非实际测量/推导值。遇到直接丢弃！

### 4. 规范命名空间
- 提取的数据 `condition_tags` 必须包含 `"scope: global"`。
- 必须通过标签指明具体的物理概念，如 `"metric: [具体物理量名称]"`。

## 🧠 强制思维链与 JSON 输出格式

提取前，请必须先在 `reasoning` 字段中简要核对：1) 是否明确归属目标天体？2) 是否为整体宏观属性？3) 是否为实际测量值？如果不符合，请果断放弃提取！
并在 `reasoning` 中原样复述你在原文或图中看到的数字字符串，然后与 `field_value` 的值逐字符核对；若两者不一致，直接放弃这条提取，不要猜测或修正后照提。

**输出示例**（仅作格式参考，非实际要求物理量）：
```json
{{
  "extractions": [
    {{
      "page": 4,
      "reasoning": "原文显示 24.42 ± 0.06 mag，与 field_value 逐字符一致；该数值描述的是目标天体整体的距离模数，并非内部某个子星团，且为实际观测推导值，并非参考基准。符合提取要求。",
      "field_name": "distance",
      "field_value": "24.42 ± 0.06",
      "field_unit": "mag",
      "context_snippet": "we derive a distance modulus to the galaxy of (m-M)0 = 24.42 ± 0.06 mag...",
      "measurement_method": "Horizontal branch luminosity",
      "condition_tags": ["scope: global", "metric: distance_modulus", "HST", "photometric"],
      "extraction_method": "text",
      "confidence": 0.98
    }}
  ]
}}
```

## 字段说明
- **page**: 页码（1-based整数，严格对应图片顺序）
- **reasoning**: [必填] 提取前进行的自我逻辑核对（如判别为微观局部，必须放弃提取）。
- **field_name**: 响应用户指令的物理量大类（简短英文小写下划线，如 "distance", "metallicity"）
- **field_value**: 提取的值（保持原文格式，包含不确定性）
- **field_unit**: 单位（如 "mag", "kpc", "dex"）
- **context_snippet**: 提取值周围的原文（约200字符，用于溯源）
- **measurement_method**: 观测、推导或统计方法
- **condition_tags**: 必须包含 scope:global 和 metric:xxx 标签
- **extraction_method**: "text" | "table" | "figure"
- **confidence**: 提取置信度（0.0-1.0）

## 最后警告
如果通篇论文全是内部子结构的枯燥表格，或者没有关于整体【{target_entity}】的合格数据，请极其果断地返回 {{"extractions": []}}！
确保输出是合法的纯 JSON 格式。"""

    # Add specific page range if num_images provided
    if num_images > 0:
        prompt += f"""

现在，请严谨地分析这篇论文的所有页面（共{num_images}张图片，对应page 1到page {num_images}），并返回 JSON 结果。
"""
    else:
        prompt += """

现在，请严谨地分析这篇论文的所有页面，并返回 JSON 结果。
"""

    return prompt


def call_qwen_vlm(
    images: List[Image.Image],
    prompt: str,
    model: str = None,
    temperature: float = None,
    max_retries: int = 3
) -> str:
    """
    Call Qwen3.7-Plus VLM API with rate limiting protection.

    Args:
        images: List of images (all pages of a paper)
        prompt: Extraction prompt
        model: Model name (default from settings)
        temperature: Temperature (default from settings)
        max_retries: Maximum retries for rate limiting errors (default 3)

    Returns:
        Model output as JSON string

    Raises:
        Exception: If API call fails after all retries
    """
    # Use settings if not specified
    model = model or settings.vlm.model
    temperature = temperature if temperature is not None else settings.vlm.temperature

    logger.debug(f"Calling VLM API with {len(images)} images")
    logger.debug(f"  Model: {model}, Temperature: {temperature}")

    # DashScope SDK（直接连阿里云 qwen-vl）
    dashscope.api_key = settings.vlm.api_key

    # Convert images to base64 (do this once, reuse for retries)
    image_contents = []
    for idx, img in enumerate(images):
        logger.debug(f"  Encoding image {idx + 1}/{len(images)}")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        image_contents.append({"image": f"data:image/png;base64,{img_base64}"})

    # DashScope 多模态消息格式
    messages = [
        {
            "role": "user",
            "content": image_contents + [{"text": prompt}]
        }
    ]

    logger.debug(f"Sending API request (total content items: {len(image_contents) + 1})")

    # Retry loop with exponential backoff for rate limiting
    timeout_retry_count = 0
    max_timeout_retries = settings.quality.max_timeout_retries

    for attempt in range(1, max_retries + 1):
        try:
            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.vlm.max_tokens,
                response_format={"type": "json_object"}
            )

            if response.status_code == 200:
                result = response.output.choices[0].message.content

                # Handle different return types from DashScope API
                if isinstance(result, str):
                    logger.debug(f"API call successful, response length: {len(result)} chars")
                    return result
                elif isinstance(result, (list, dict)):
                    # API returned structured data, convert to JSON string
                    import json
                    result_str = json.dumps(result, ensure_ascii=False)
                    logger.debug(f"API returned structured data, converted to JSON string: {len(result_str)} chars")
                    return result_str
                else:
                    # Unexpected type, try to convert to string
                    result_str = str(result)
                    logger.warning(f"API returned unexpected type {type(result)}, converted to string")
                    return result_str

            # Check for rate limiting errors
            elif hasattr(response, 'code') and response.code in [
                "Throttling.RateQuota",  # DashScope rate limit error
                "FlowControl.User",       # User-level flow control
                "FlowControl.System",     # System-level flow control
                429                        # HTTP 429 Too Many Requests
            ]:
                if attempt < max_retries:
                    # Exponential backoff: 5s, 10s, 20s
                    wait_time = (2 ** (attempt - 1)) * 5
                    logger.warning(
                        f"Rate limit hit (attempt {attempt}/{max_retries}), "
                        f"retrying in {wait_time}s... (code: {response.code})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    error_msg = f"Rate limit exceeded after {max_retries} attempts: {response.code} - {response.message}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

            # Other errors
            else:
                error_msg = f"API call failed: {response.code} - {response.message}"
                logger.error(error_msg)
                raise Exception(error_msg)

        except Exception as e:
            # If it's our own raised exception, re-raise
            if "Rate limit exceeded" in str(e) or "API call failed" in str(e):
                raise

            # Handle timeout separately with more retries
            error_str = str(e)
            if "Read timed out" in error_str or "timeout" in error_str.lower():
                timeout_retry_count += 1
                logger.warning(f"API timeout (retry {timeout_retry_count}/{max_timeout_retries}): {e}")

                if timeout_retry_count < max_timeout_retries:
                    time.sleep(10)
                    continue
                else:
                    error_msg = f"API timeout after {max_timeout_retries} timeout retries"
                    logger.error(error_msg)
                    raise Exception(error_msg)

            # For other exceptions (network errors, etc.)
            if attempt < max_retries:
                wait_time = (2 ** (attempt - 1)) * 5
                logger.warning(
                    f"API call exception (attempt {attempt}/{max_retries}), "
                    f"retrying in {wait_time}s... Error: {e}"
                )
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"API call failed after {max_retries} attempts: {e}")
                raise

    # Should not reach here
    raise Exception("API call failed: max retries exceeded")
