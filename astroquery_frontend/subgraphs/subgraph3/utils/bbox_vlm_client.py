"""BBox 标注 VLM 客户端（qwen3.7-flash，DashScope SDK）。"""

import dashscope
from dashscope import MultiModalConversation
import base64
from io import BytesIO
import time
import json
from json_repair import repair_json
from PIL import Image
from typing import Optional, Dict
from ..config.settings import settings
from .logger import get_logger


logger = get_logger(__name__)


def _coerce_to_dict(data, depth: int = 0) -> Optional[dict]:
    """
    递归归一化 DashScope 的多态返回 → dict。

    处理链：str(JSON) → list → [{"text": "..."}] → text 内嵌 JSON → dict
    任意深度嵌套都能展开；展开失败或深度超限返回 None。
    """
    if depth > 6:
        return None
    if isinstance(data, dict):
        # dict 内若只有 text 键（再包一层），继续展开
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
            # M-26: json_repair 回退 — 与 vlm_extractor 对齐
            try:
                return _coerce_to_dict(json.loads(repair_json(data)), depth + 1)
            except (json.JSONDecodeError, TypeError):
                return None
    if isinstance(data, list):
        if not data:
            return None
        return _coerce_to_dict(data[0], depth + 1)
    return None


def build_bbox_prompt(extraction: dict, target_entity: str) -> str:
    """
    构建 bbox 标注专用提示词（两阶段定位引导）
    """
    field_name = extraction.get("field_name", "")
    field_value = extraction.get("field_value", "")
    field_unit = extraction.get("field_unit", "")
    context_snippet = extraction.get("context_snippet", "")
    full_value = f"{field_value} {field_unit}".strip()

    prompt = f"""你是一个精确的文档坐标标注专家。请在图片中定位指定的数据点并返回其边界框坐标。

## [PIN] 目标定位信息
- **目标天体**: {target_entity}
- **物理量类型**: {field_name}
- **目标数值**: {full_value}
- **上下文片段**: "{context_snippet[:200]}"

## [TARGET] 两阶段定位流程
### 第一阶段：初步定位（区域识别）
请先在图片中找到包含此数据的**大致区域**：
1. 这段文字可能出现在哪个段落、表格或图表标题中？
2. 在图片的大致什么位置（上部/中部/下部，左侧/中间/右侧）？
3. 周围有什么明显的视觉标记（如标题、表格边框、公式等）？

### 第二阶段：精确定位（坐标标注）
在初步定位的区域内，精确找到**数值本身**（{full_value}）：
1. 定位到具体的数字或符号
2. 标注紧密包裹该数值的最小矩形框
3. 坐标系统：左上角 (0,0)，右下角 (1000,1000)
4. 格式：[x_min, y_min, x_max, y_max]

## ⚠ 关键要求
- **只标注数值本身**，不包含周围的文字说明
- **紧密贴合**：矩形框应刚好包住数字和单位，不要留太多空白
- **禁止猜测**：如果图片中找不到该数值，返回 {{"bbox_2d": null, "found": false, "reason": "未找到目标数值"}}
- **禁止修改数值**：只定位给定的数值，不要标注其他相似数值

## [SEND] 输出格式（严格 JSON 对象——必须遵守）

**[ALERT] 结构铁律（违反则输出作废）**
1. 输出必须是**单个 JSON 对象**，以 `{{` 开头、以 `}}` 结尾——**绝对禁止**用数组 `[ ... ]` 包裹，禁止任何外层包装
2. **禁止** markdown 围栏（```json）、禁止任何解释文字、禁止输出示例
3. `bbox_2d` 必须是**恰好 4 个整数**的数组，范围 0-1000，且必须满足 x_min < x_max 且 y_min < y_max
4. `confidence` 必须是 0 到 1 之间的**数字**（不是字符串）
5. `found` 必须是布尔值 `true` 或 `false`（不是字符串 "true"）
6. 未找到时 `bbox_2d` 必须是 `null`（不是 `[]`、不是 `[0,0,0,0]`）
7. 允许且仅允许以下 5 个键，不得添加其他键

**成功定位时——严格按此骨架输出（只填值，不改结构）：**
```json
{{"stage1_analysis": "简短定位说明（≤100字）", "bbox_2d": [x_min, y_min, x_max, y_max], "confidence": 0.95, "found": true}}
```

**未找到时——严格按此骨架输出：**
```json
{{"stage1_analysis": "简短说明", "bbox_2d": null, "confidence": 0.0, "found": false, "reason": "未找到目标数值"}}
```

现在请开始标注。"""

    return prompt


def call_qwen_flash_bbox(
    image: Image.Image,
    extraction: dict,
    target_entity: str,
    max_retries: int = 3
) -> Dict:
    """
    调用 qwen3.7-flash 标注单个数据点的 bbox（两阶段定位）。
    统一走 DASHSCOPE key + Maas URL（OpenAI 兼容端点）。
    """
    # 模型名来自统一 Settings（默认 qwen3.7-flash，可用 DASHSCOPE_BBOX_MODEL 覆盖）
    model = settings.bbox_vlm.model
    temperature = 0.0  # bbox 标注需要确定性
    # L-08: 读配置（原硬编码 500 与 BBoxVLMConfig.max_tokens 重复，配置恒不生效）
    max_tokens = settings.bbox_vlm.max_tokens

    # DashScope SDK（直接连阿里云 qwen-vl）
    dashscope.api_key = settings.vlm.api_key

    # 构建 prompt
    prompt = build_bbox_prompt(extraction, target_entity)

    # 图片转 base64
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

    # DashScope 多模态消息格式
    messages = [
        {
            "role": "user",
            "content": [
                {"image": f"data:image/png;base64,{img_base64}"},
                {"text": prompt}
            ]
        }
    ]

    # 重试循环
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"[BBox VLM] Calling {model} (attempt {attempt}/{max_retries})")

            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )

            if response.status_code == 200:
                result = response.output.choices[0].message.content

                # 递归归一化：DashScope 返回格式不稳定（str / list / dict / [{"text": ...}] 任意嵌套），
                # 反复展开直到拿到含 bbox_2d 的 dict
                data = _coerce_to_dict(result)
                if data is None:
                    return {
                        "bbox_2d": None, "confidence": 0.0, "found": False,
                        "error": f"无法解析为 dict: {str(result)[:100]!r}"
                    }

                # 校验 bbox 格式
                bbox_2d = data.get("bbox_2d")
                if bbox_2d and isinstance(bbox_2d, list) and len(bbox_2d) == 4:
                    if all(isinstance(coord, (int, float)) and 0 <= coord <= 1000 for coord in bbox_2d):
                        logger.debug(f"[BBox VLM] Success: bbox={bbox_2d}")
                        return {
                            "bbox_2d": bbox_2d,
                            "confidence": data.get("confidence", 0.9),
                            "found": data.get("found", True),
                            "stage1_analysis": data.get("stage1_analysis", ""),
                            "error": None
                        }
                    else:
                        logger.warning(f"[BBox VLM] Invalid bbox range: {bbox_2d}")

                # 未找到或无效
                return {
                    "bbox_2d": None,
                    "confidence": data.get("confidence", 0.0),
                    "found": data.get("found", False),
                    "stage1_analysis": data.get("stage1_analysis", ""),
                    "error": data.get("reason", "Invalid bbox format")
                }

            # 处理限流
            elif hasattr(response, 'code') and response.code in [
                "Throttling.RateQuota",
                "FlowControl.User",
                "FlowControl.System",
                429
            ]:
                if attempt < max_retries:
                    wait_time = (2 ** (attempt - 1)) * 2  # 2s, 4s, 8s
                    logger.warning(f"[BBox VLM] Rate limit, retry in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {
                        "bbox_2d": None, "confidence": 0.0, "found": False,
                        "error": f"Rate limit after {max_retries} retries"
                    }

            # 其他 API 错误
            else:
                error_msg = f"API error: {response.code} - {response.message}"
                logger.error(f"[BBox VLM] {error_msg}")
                return {
                    "bbox_2d": None, "confidence": 0.0, "found": False,
                    "error": error_msg
                }

        except json.JSONDecodeError as e:
            logger.warning(f"[BBox VLM] JSON parse error (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                wait_time = (2 ** (attempt - 1)) * 2
                time.sleep(wait_time)
                continue
            else:
                return {
                    "bbox_2d": None, "confidence": 0.0, "found": False,
                    "error": f"JSON parse error: {e}"
                }

        except Exception as e:
            if attempt < max_retries:
                wait_time = (2 ** (attempt - 1)) * 2
                logger.warning(f"[BBox VLM] Exception, retry in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"[BBox VLM] Failed after {max_retries} attempts: {e}")
                return {
                    "bbox_2d": None, "confidence": 0.0, "found": False,
                    "error": str(e)
                }

    # 不应到达此处
    return {
        "bbox_2d": None, "confidence": 0.0, "found": False,
        "error": "Max retries exceeded"
    }
