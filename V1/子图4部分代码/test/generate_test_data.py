"""
generate_test_data.py

生成 1000 条 grounded_data 格式的测试样例。

故意引入以下问题以全面测试 Quality Pipeline:
  - 跨来源数值冲突 (同一字段不同文献差异 >20%)
  - 缺失单位 (field_unit = None)
  - 格式问题 (~前缀, 字符串值未清洗)
  - 重复记录 (相同 record_id)
  - 缺失溯源 (provenance 不完整)
  - 字段名别名 (未映射到标准 Schema)
  - 单位不一致 (MPa / GPa / psi 混用)

用法:
    python generate_test_data.py              # 生成 1000 条, 输出到 test_data_1000.json
    python generate_test_data.py --count 500  # 生成 500 条
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any

# 固定随机种子确保可复现
random.seed(42)

# ==========================================================
# 科学字段定义
# ==========================================================

FIELD_DEFINITIONS = {
    "yield_strength":       {"unit": "MPa",   "min": 100, "max": 800,  "alias": ["YS", "yield_stress", "σ_y"]},
    "tensile_strength":     {"unit": "MPa",   "min": 150, "max": 1000, "alias": ["UTS", "ultimate_tensile_strength"]},
    "elongation":           {"unit": "%",     "min": 2,   "max": 45,   "alias": ["EL", "elongation_at_break"]},
    "hardness":             {"unit": "HV",    "min": 50,  "max": 500,  "alias": ["HV", "Vickers", "microhardness"]},
    "temperature":          {"unit": "C",     "min": -50, "max": 600,  "alias": ["T", "test_temperature"]},
    "strain_rate":          {"unit": "s^-1",  "min": 0.0001, "max": 10, "alias": ["strain rate", "ε_dot"]},
    "fatigue_life":         {"unit": "cycles","min": 1e3,  "max": 1e8, "alias": ["N_f", "cycles_to_failure"]},
    "fracture_toughness":   {"unit": "MPa√m", "min": 10,  "max": 200, "alias": ["K_IC", "KIC"]},
    "density":              {"unit": "g/cm^3","min": 1.5,  "max": 10,  "alias": ["ρ", "rho"]},
    "thermal_conductivity": {"unit": "W/mK",  "min": 10,  "max": 500, "alias": ["k", "thermal_k"]},
}

STANDARD_UNITS = {
    "yield_strength": "MPa",
    "tensile_strength": "MPa",
    "elongation": "%",
    "hardness": "HV",
    "temperature": "C",
    "strain_rate": "s^-1",
    "fatigue_life": "cycles",
    "fracture_toughness": "MPa√m",
    "density": "g/cm^3",
    "thermal_conductivity": "W/mK",
}

# 错别单位混用
WRONG_UNITS = {
    "yield_strength":       ["GPa", "psi", "ksi"],
    "tensile_strength":     ["GPa", "psi", "ksi"],
    "hardness":             ["HB", "HRC"],
    "temperature":          ["K", "F"],
    "density":              ["kg/m^3"],
}

# ==========================================================
# 论文数据模板
# ==========================================================

MATERIALS = [
    "Al-7075", "Al-6061", "Ti-6Al-4V", "Inconel 718", "316L Stainless Steel",
    "AZ31 Magnesium", "Cu-Be C17200", "Al-2024", "Ti-5553", "CoCrMo Alloy",
    "Al-5083", "Mg-ZK60", "NiTi Shape Memory", "Al-Li 2195", "WC-Co Composite",
    "Cu-Cr-Zr", "Al-SiC MMC", "Fe-Mn-Al-C Steel", "Zr-2.5Nb", "Hastelloy X",
    "Al-7050", "CP-Ti Grade 2", "17-4 PH Steel", "Invar 36", "Monel 400",
    "Al-2219", "Ti-6242", "Haynes 282", "AlBeMet 162", "Cu-W Composite",
]

JOURNALS = [
    "Materials Science and Engineering: A",
    "Acta Materialia",
    "Metallurgical and Materials Transactions A",
    "Journal of Materials Science",
    "Materials & Design",
    "International Journal of Fatigue",
    "Scripta Materialia",
    "Journal of Alloys and Compounds",
    "Materials Characterization",
    "Engineering Fracture Mechanics",
]

AUTHORS_POOL = [
    ["Zhang, W.", "Li, H.", "Chen, Y."],
    ["Wang, X.", "Liu, J.", "Zhao, M."],
    ["Kim, S.", "Park, J.", "Lee, D."],
    ["Johnson, R.", "Smith, A.", "Brown, T."],
    ["Mueller, F.", "Schmidt, K.", "Weber, P."],
    ["Tanaka, Y.", "Sato, H.", "Yamamoto, K."],
    ["Garcia, M.", "Lopez, C.", "Martinez, D."],
    ["Andersson, B.", "Johansson, L.", "Lindberg, E."],
    ["Kumar, R.", "Singh, P.", "Patel, A."],
    ["Chen, X.", "Wu, Z.", "Huang, Y."],
    ["dos Santos, J.", "Oliveira, M.", "Costa, R."],
    ["Ivanov, D.", "Petrov, S.", "Fedorov, A."],
]

def generate_source(source_id: str, year: int, priority: float) -> dict[str, Any]:
    """生成一篇论文的 Source 元数据。"""
    material = random.choice(MATERIALS)
    journal = random.choice(JOURNALS)
    authors = random.choice(AUTHORS_POOL)
    title_templates = [
        f"Mechanical properties of {material} at elevated temperatures",
        f"Effect of aging treatment on {material} alloy",
        f"High-temperature tensile behavior of {material}",
        f"Microstructure and properties of processed {material}",
        f"Fatigue and fracture characteristics of {material}",
        f"Thermal-mechanical response of {material} under various conditions",
        f"Strain rate sensitivity of {material} alloy",
        f"Optimization of heat treatment for {material}",
        f"Correlation between processing and performance of {material}",
    ]

    return {
        "source_id": source_id,
        "source_type": "paper",
        "doi": f"10.{random.randint(1000,9999)}/j.{random.choice(['msea','actamat','mmta','jms'])}_{random.randint(2000,2026)}.{random.randint(100000,999999)}",
        "title": random.choice(title_templates),
        "authors": authors,
        "year": year,
        "journal": journal,
        "access_path": f"/cache/{source_id.replace('/', '_')}.pdf",
        "retrieval_priority": round(priority, 4),
    }

def generate_records(
    source_id: str,
    doc_idx: int,
    fields: list[str],
    page: int,
    add_noise: bool = True,
) -> list[dict[str, Any]]:
    """为一篇论文生成多条 Record。"""
    records = []
    table_id = random.randint(1, 5)

    for i, field_name in enumerate(fields):
        if field_name not in FIELD_DEFINITIONS:
            continue

        fd = FIELD_DEFINITIONS[field_name]
        base_value = round(random.uniform(fd["min"], fd["max"]), 2)
        row_num = i + 1

        # ── 引入噪声 ──
        noise_type = "clean"
        if add_noise:
            noise_type = random.choices(
                ["clean", "conflict", "missing_unit", "format_issue",
                 "alias", "wrong_unit", "duplicate", "missing_provenance"],
                weights=[50, 8, 8, 8, 6, 6, 5, 5],
                k=1,
            )[0]

        # 确定输出值
        if noise_type == "conflict" and random.random() < 0.5:
            # 故意制造冲突：值差异 >20%
            if random.random() < 0.5:
                value = round(base_value * random.uniform(0.6, 0.79), 2)
            else:
                value = round(base_value * random.uniform(1.21, 1.5), 2)
        else:
            value = base_value

        # 确定 field_name
        if noise_type == "alias":
            output_name = random.choice(fd["alias"])
        else:
            output_name = field_name

        # 确定单位
        if noise_type == "missing_unit":
            unit = None
        elif noise_type == "wrong_unit":
            wrong_units = WRONG_UNITS.get(field_name, [])
            unit = random.choice(wrong_units) if wrong_units else fd["unit"]
        else:
            unit = fd["unit"]

        # 确定提取方式
        method = random.choice(["llm_text", "llm_table"])

        # 确定溯源
        if noise_type == "missing_provenance":
            provenance = {"page": None, "bbox": None}
        else:
            x0 = random.randint(80, 200)
            y0 = 200 + row_num * 18
            provenance = {
                "page": page,
                "bbox": [x0, y0, x0 + random.randint(100, 180), y0 + 14],
            }

        # 确定 trace_id
        if noise_type == "format_issue":
            trace_id = f"doc{doc_idx}_p{page}_tb{table_id}_r{row_num}"
        else:
            trace_id = f"doc{doc_idx}_p{page}_tb{table_id}_r{row_num}"

        record = {
            "record_id": f"{source_id.replace('/', '_')}_{output_name}_{row_num}",
            "source_id": source_id,
            "field_name": output_name,
            "field_value": value,
            "field_unit": unit,
            "trace_id": trace_id,
            "provenance": provenance,
            "extraction_method": method,
        }

        # 格式噪声：加 ~ 前缀
        if noise_type == "format_issue":
            if random.random() < 0.5:
                record["field_value"] = f"~{value}"
            else:
                record["field_value"] = f"≈ {value}"

        records.append(record)

    return records

def generate_test_data(num_samples: int = 1000) -> dict[str, Any]:
    """
    生成 grounded_data 格式的测试数据。

    Args:
        num_samples: 目标总记录数。

    Returns:
        grounded_data JSON 字典。
    """
    print(f"生成 {num_samples} 条测试记录...")

    fields = list(FIELD_DEFINITIONS.keys())
    sources = []
    records = []
    records_per_paper = random.randint(3, 8)
    num_papers = max(10, num_samples // records_per_paper)

    stats = {
        "clean": 0, "conflict": 0, "missing_unit": 0,
        "format_issue": 0, "alias": 0, "wrong_unit": 0,
        "duplicate": 0, "missing_provenance": 0,
    }

    for i in range(num_papers):
        doi = f"10.{random.randint(1000,9999)}/paper_{i:04d}"
        year = random.randint(2000, 2026)
        priority = round(random.uniform(0.4, 1.0), 4)

        source = generate_source(doi, year, priority)
        sources.append(source)

        # 每个论文随机选择 3-8 个字段
        num_fields = min(records_per_paper, len(fields))
        selected_fields = random.sample(fields, num_fields)
        page = random.randint(3, 15)

        paper_records = generate_records(doi, i + 1, selected_fields, page, add_noise=True)
        records.extend(paper_records)

    # 裁剪到目标数量
    if len(records) > num_samples:
        records = records[:num_samples]

    # 添加一些精确重复记录 (5% 概率)
    num_dupes = max(1, int(len(records) * 0.03))
    for _ in range(num_dupes):
        if len(records) >= 2:
            src_idx = random.randint(0, len(records) - 1)
            dup = dict(records[src_idx])  # 浅拷贝
            records.append(dup)
            stats["duplicate"] += 1

    # 统计噪声分布
    for rec in records:
        fn = rec.get("field_name", "")
        unit = rec.get("field_unit")
        val = rec.get("field_value")
        prov = rec.get("provenance", {})

        if fn not in FIELD_DEFINITIONS and fn not in sum([fd["alias"] for fd in FIELD_DEFINITIONS.values()], []):
            continue
        if unit is None:
            stats["missing_unit"] += 1
        if isinstance(val, str) and ("~" in val or "≈" in val):
            stats["format_issue"] += 1
        if prov.get("page") is None and prov.get("bbox") is None:
            stats["missing_provenance"] += 1
        # 检查是否与标准名不同 (别名)
        if fn in FIELD_DEFINITIONS:
            pass  # clean
        else:
            stats["alias"] += 1  # 使用了别名

    result = {
        "schema_version": "1.0.0",
        "sources": sources,
        "records": records,
    }

    # 打印统计
    print(f"\n生成结果:")
    print(f"  论文数: {len(sources)}")
    print(f"  记录数: {len(records)}")
    print(f"  噪声分布:")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"    {k}: {v}")

    return result

def main():
    parser = argparse.ArgumentParser(description="生成 grounded_data 测试数据")
    parser.add_argument("--count", type=int, default=1000, help="目标记录数 (默认 1000)")
    parser.add_argument("--output", type=str, default="test_data_1000.json", help="输出文件名")
    args = parser.parse_args()

    data = generate_test_data(args.count)

    # 写入文件
    output_path = os.path.join(os.path.dirname(__file__), args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n写入: {output_path}")
    print(f"文件大小: {os.path.getsize(output_path) / 1024:.1f} KB")

if __name__ == "__main__":
    main()
