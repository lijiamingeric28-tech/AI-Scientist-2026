"""
提取子图 Prompt 模板
"""

# ==========================================
# Agent 1: Normalization Prompt (简化版)
# ==========================================

NORMALIZATION_PROMPT = """You are a scientific terminology normalizer.

User input:
- Entities: {entities}
- Properties: {properties}

Tasks:
1. Normalize entity type to standard English term (lowercase, snake_case if needed)
   Example: "快速射电暴" → "FRB"
   Example: "铝合金" → "alloy"
   
2. Normalize property name to standard English term (snake_case)
   Example: "色散量" → "dispersion_measure"
   Example: "抗拉强度" → "tensile_strength"

Output JSON:
{{
  "entity_type": "...",
  "property_name": "..."
}}
"""

NORMALIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_type": {"type": "string"},
        "property_name": {"type": "string"}
    },
    "required": ["entity_type", "property_name"]
}


# ==========================================
# Agent 2: VLM Extraction Prompt (5字段版本)
# ==========================================

def generate_vlm_prompt(entity_type: str, property_name: str) -> str:
    """
    生成VLM提取Prompt
    
    Args:
        entity_type: 规范化的实体类型（如 "FRB"）
        property_name: 规范化的属性名称（如 "dispersion_measure"）
    
    Returns:
        VLM Prompt字符串
    """
    prompt = f"""This is a scientific paper about {entity_type}.

Please extract all actual observation/measurement data of {property_name} for {entity_type}.

Requirements:
1. Extract only actual observed/measured values
2. Ignore hypothetical discussions, theoretical predictions, or data cited from other papers
3. Ensure the entity name is correct
4. Ensure the property value is correct

Output JSON array, each object contains:
- entity_name: specific name of the entity (e.g., "FRB 20180301A", "Ti-6Al-4V")
- property_value: measured value (number or string)
- property_unit: unit (e.g., "pc/cm^3", "MPa")
- source_page: page number (only number, e.g., "3", not "page 3")
- extract_reason: explanation including:
  (1) Why this name is confirmed as {entity_type}
  (2) Why this value is confirmed as {property_name}

Return empty array [] if no data found.

Note:
- If uncertain about entity or property, do not extract
- source_page must be pure number
"""
    return prompt


VLM_EXTRACTION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string"},
            "property_value": {"type": "string"},
            "property_unit": {"type": "string"},
            "source_page": {"type": "string"},
            "extract_reason": {"type": "string"}
        },
        "required": [
            "entity_name",
            "property_value",
            "property_unit",
            "source_page",
            "extract_reason"
        ]
    }
}
