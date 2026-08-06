"""测试 P1 性质标准化节点集成"""

import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import json
from combine.astroquery_ai.property_standardization import (
    query_simbad,
    load_rag_properties,
    select_properties_with_llm,
    build_property_spec,
    generate_target_schema,
    property_standardization_node
)

def test_simbad():
    print("\n" + "=" * 60)
    print("测试 1: SIMBAD 查询")
    print("=" * 60)

    result, err = query_simbad("M31")
    if err:
        print(f"❌ 失败: {err}")
        return False

    print(f"✓ MAIN_ID: {result.get('MAIN_ID')}")
    print(f"✓ OTYPE: {result.get('OTYPE')}")
    print(f"✓ OTYPES: {result.get('OTYPES')}")
    return True

def test_rag_load():
    print("\n" + "=" * 60)
    print("测试 2: RAG 性质库加载")
    print("=" * 60)

    simbad_result, _ = query_simbad("M31")
    if not simbad_result:
        print("❌ SIMBAD 查询失败")
        return False

    rag = load_rag_properties(simbad_result)
    if not rag:
        print("❌ RAG 加载失败")
        return False

    print(f"✓ otype: {rag.get('otype')}")
    print(f"✓ name_cn: {rag.get('name_cn')}")
    print(f"✓ properties: {len(rag.get('properties', []))} 个")

    # 检查单位
    props_with_unit = sum(1 for p in rag['properties'] if p.get('unit'))
    print(f"✓ 带单位的性质: {props_with_unit}/{len(rag['properties'])}")
    return True

def test_full_node():
    print("\n" + "=" * 60)
    print("测试 3: P1 完整节点")
    print("=" * 60)

    state = {
        "target_entity": "M31",
        "user_query": "查询 M31 的距离和金属丰度",
        "requested_properties": []
    }

    result = property_standardization_node(state)

    if "error_log" in result:
        print(f"❌ 节点失败: {result['error_log']}")
        return False

    simbad = result.get('simbad_info', {})
    prop_spec = result.get('property_spec', [])
    target_schema = result.get('target_schema', {})

    print(f"✓ SIMBAD main_id: {simbad.get('MAIN_ID')}")
    print(f"✓ PropertySpec: {len(prop_spec)} 个性质")

    if prop_spec:
        print("\n前 3 个性质:")
        for p in prop_spec[:3]:
            print(f"  - {p['property_id']} ({p.get('name_cn')}) unit={p.get('unit')}")

    print(f"\n✓ target_schema fields: {len(target_schema.get('fields', []))} 个")

    return True

if __name__ == "__main__":
    import os
    import sys

    # 检查 API key
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("⚠️ 未设置 DASHSCOPE_API_KEY，LLM 筛选将失败")
        print("请运行: set DASHSCOPE_API_KEY=your_key")
        sys.exit(1)

    all_pass = True

    if not test_simbad():
        all_pass = False

    if not test_rag_load():
        all_pass = False

    if not test_full_node():
        all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("✅ 所有测试通过")
    else:
        print("❌ 部分测试失败")
    print("=" * 60)
