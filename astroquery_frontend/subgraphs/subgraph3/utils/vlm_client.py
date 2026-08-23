"""VLM API 客户端（Qwen3.7-Plus，DashScope SDK）。"""

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

    # V2.7: 输出示例按白名单动态生成——白名单含 dist_modulus 才展示 dist_modulus 示例，
    # 避免诱导 VLM 输出白名单外的字段（3C 273 dist_modulus 越界根因）。
    # 用普通字符串拼接（非 f-string），内部 JSON 花括号不需要转义。
    _distance_example = (
        '{'
        '  "page": 4,'
        '  "reasoning": "原文显示 136.2 pc，与 field_value 逐字符一致；'
        '该数值描述目标天体整体实际距离，单位 pc，符合 distance。",'
        '  "field_name": "distance",'
        '  "field_value": "136.2",'
        '  "field_unit": "pc",'
        '  "context_snippet": "the distance to the Pleiades is 136.2 pc...",'
        '  "measurement_method": "parallax",'
        '  "condition_tags": ["scope: global", "metric: distance"],'
        '  "extraction_method": "text",'
        '  "confidence": 0.98'
        '}'
    )
    _dm_example = (
        ','
        '{'
        '  "page": 7,'
        '  "reasoning": "原文显示 (m-M)0 = 5.58 ± 0.06 mag 是距离模数（单位 mag），'
        '与 distance（pc）不同，归入 dist_modulus。",'
        '  "field_name": "dist_modulus",'
        '  "field_value": "5.58 ± 0.06",'
        '  "field_unit": "mag",'
        '  "context_snippet": "we derive a distance modulus to the cluster of (m-M)0 = 5.58 ± 0.06 mag...",'
        '  "measurement_method": "photometric distance modulus",'
        '  "condition_tags": ["scope: global", "metric: distance_modulus"],'
        '  "extraction_method": "text",'
        '  "confidence": 0.98'
        '}'
    )
    _has_dm = property_spec and any(p.get("property_id") == "dist_modulus" for p in property_spec)
    example_entries = (
        "**输出示例**（仅格式参考）：\n"
        "```json\n"
        '{\n  "extractions": [\n'
        + _distance_example
        + (_dm_example if _has_dm else "")
        + '\n  ]\n}\n'
        "```"
    )

    prompt = f"""你是一个顶尖的天文学文献数据提取专家。我将按顺序向你展示一篇完整论文的所有页面图片。
{page_mapping_note}
════════════════════════════════════════
① 提取目标
════════════════════════════════════════
从论文中提取关于目标天体 **{target_entity}** 的物理性质数据。
本次允许的 field_name（白名单，只能从这些 property_id 中选）：
{property_whitelist}
**field_name 必须是上面列表中的 property_id，不得自由命名、不得臆造。**

════════════════════════════════════════
② 数据来源
════════════════════════════════════════
只从正文文本与表格（table）中提取；页面中的图片、图表、照片等图形元素一律忽略，不得作为提取来源。

════════════════════════════════════════
③ 提取原则
════════════════════════════════════════
1. **宏观整体**：只提取【{target_entity}】作为一个整体的物理属性（如整个星系的距离、总质量）；忽略内部子结构/局部区域（球状星团、特定恒星、HII区等）。
2. **实体排他**：不提取用于对比、校准或背景参考的其他天体数据。

════════════════════════════════════════
④ 禁止提取（违反即放弃该条）
════════════════════════════════════════
遇到以下情况直接放弃：
1. **公式/关系式/校准式**：如 "MG = 0.35[Fe/H] + 1.2"、函数表达式。
2. **统计量/计数**：样本数、成员星数、数据点个数（除非该计数本身就是目标量）。
3. **参考/推导辅助**：理论假设值、参考基准点、归一化常数、拟合参数。
4. **范围/区间/上下限/百分位**（除非目标性质本身以范围定义，如"质量范围"）。
5. **多值打包**：一个 field_value 塞多个不相关量（如 "G=12.84, Bp-Rp=0.49"）。
6. **单位不匹配**：数值单位与白名单该性质的标准单位明显不符时，不归入该字段。

════════════════════════════════════════
⑤ 单位与字段区分
════════════════════════════════════════
- field_unit 必须与实际数值一致。
- 同概念但表示不同（如 distance=pc 与 dist_modulus=mag）是不同字段，按单位归属，不得混放。
- 白名单没有对应字段时，遇到该量就放弃，不要硬塞进其他字段。

════════════════════════════════════════
⑥ 提取前自检（reasoning 必填）
════════════════════════════════════════
每个提取条目前，在 reasoning 中核对：
1) 是否明确归属【{target_entity}】？2) 是否为宏观整体属性？3) 是否为实际测量值（非公式/计数/参考）？
4) 数值与原文逐字符一致（在 reasoning 中原样复述数字后核对）？
任一不满足 → 放弃该条，不猜测、不修正后照提。
且 condition_tags 必须包含 "scope: global" 与 "metric: [具体物理量]" 标签。

════════════════════════════════════════
⑦ 输出 JSON
════════════════════════════════════════
{example_entries}

字段说明：
- **page**: 页码（1-based整数，严格对应图片顺序）
- **reasoning**: [必填] 提取前自检核对
- **field_name**: 必须来自①白名单的 property_id
- **field_value**: 提取的值（保持原文格式，包含不确定性）
- **field_unit**: 单位（与实际数值一致）
- **context_snippet**: 提取值周围的原文（约200字符，用于溯源）
- **measurement_method**: 观测、推导或统计方法
- **condition_tags**: 必须含 scope:global 和 metric:xxx 标签
- **extraction_method**: "text" | "table"
- **confidence**: 提取置信度（0.0-1.0）

如果通篇没有关于【{target_entity}】整体的合格数据，请果断返回 {{"extractions": []}}！
确保输出是合法的纯 JSON 格式。"""

    # 提供 num_images 时补充具体页码范围
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
    # 未指定时使用配置值
    model = model or settings.vlm.model
    temperature = temperature if temperature is not None else settings.vlm.temperature

    logger.debug(f"Calling VLM API with {len(images)} images")
    logger.debug(f"  Model: {model}, Temperature: {temperature}")

    # DashScope SDK（直接连阿里云 qwen-vl）
    dashscope.api_key = settings.vlm.api_key

    # 图片转 base64（只做一次，重试复用）
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

    # 重试循环（指数退避应对限流）
    timeout_retry_count = 0
    max_timeout_retries = settings.quality.max_timeout_retries

    for attempt in range(1, max_retries + 1):
        try:
            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.vlm.max_tokens,
                # L-08: 透传配置超时（SDK 识别 request_timeout 关键字，
                # 原恒用 SDK 默认 300s，配置 600s 不生效）
                request_timeout=settings.vlm.timeout,
                response_format={"type": "json_object"}
            )

            if response.status_code == 200:
                result = response.output.choices[0].message.content

                # 处理 DashScope API 的不同返回类型
                if isinstance(result, str):
                    logger.debug(f"API call successful, response length: {len(result)} chars")
                    return result
                elif isinstance(result, (list, dict)):
                    # API 返回结构化数据，转成 JSON 字符串
                    import json
                    result_str = json.dumps(result, ensure_ascii=False)
                    logger.debug(f"API returned structured data, converted to JSON string: {len(result_str)} chars")
                    return result_str
                else:
                    # 意外类型，尝试转字符串
                    result_str = str(result)
                    logger.warning(f"API returned unexpected type {type(result)}, converted to string")
                    return result_str

            # 检查限流错误
            elif hasattr(response, 'code') and response.code in [
                "Throttling.RateQuota",  # DashScope rate limit error
                "FlowControl.User",       # User-level flow control
                "FlowControl.System",     # System-level flow control
                429                        # HTTP 429 Too Many Requests
            ]:
                if attempt < max_retries:
                    # 指数退避：5s、10s、20s
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

            # 其他错误
            else:
                error_msg = f"API call failed: {response.code} - {response.message}"
                logger.error(error_msg)
                raise Exception(error_msg)

        except Exception as e:
            # 若是我们主动抛出的异常，直接重抛
            if "Rate limit exceeded" in str(e) or "API call failed" in str(e):
                raise

            # 超时单独处理（更多重试）
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

            # 其他异常（网络错误等）
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

    # 不应到达此处
    raise Exception("API call failed: max retries exceeded")
