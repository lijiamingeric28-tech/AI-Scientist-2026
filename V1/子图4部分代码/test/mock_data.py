"""
mock_data.py

Mock GroundedData — 用于独立测试 Quality Pipeline。
正式联调时由前半部分 Extraction Pipeline 输出真实 GroundedData。
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.grounded_data import GroundedData
from models.source import Source
from models.record import Record, Provenance

mock_grounded_data = GroundedData(
    schema_version="1.0.0",

    sources=[
        Source(
            source_id="10.1016/j.msea.2023.145678",
            source_type="paper",
            doi="10.1016/j.msea.2023.145678",
            title="High-temperature tensile properties of 7075 aluminum alloy",
            authors=["Zhang, W.", "Li, H.", "Chen, Y."],
            year=2023,
            journal="Materials Science and Engineering: A",
            access_path="https://doi.org/10.1016/j.msea.2023.145678",
            retrieval_priority=0.95,
        ),
        Source(
            source_id="10.1007/s11661-022-06789",
            source_type="paper",
            doi="10.1007/s11661-022-06789",
            title="Effect of aging treatment on mechanical properties of Al-Zn-Mg-Cu alloy",
            authors=["Wang, X.", "Liu, J."],
            year=2022,
            journal="Metallurgical and Materials Transactions A",
            access_path="/cache/10.1007_s11661-022-06789.pdf",
            retrieval_priority=0.87,
        ),
    ],

    records=[
        # ── 论文1 ──
        Record(
            record_id="10.1016_j.msea.2023.145678_yield_strength_1",
            source_id="10.1016/j.msea.2023.145678",
            field_name="yield_strength",
            field_value=450,
            field_unit="MPa",
            trace_id="doc1_p3_tb2_r1",
            provenance=Provenance(page=3, bbox=[120, 340, 280, 355]),
            extraction_method="llm_text",
        ),
        Record(
            record_id="10.1016_j.msea.2023.145678_tensile_strength_1",
            source_id="10.1016/j.msea.2023.145678",
            field_name="tensile_strength",
            field_value=520,
            field_unit="MPa",
            trace_id="doc1_p3_tb2_r2",
            provenance=Provenance(page=3, bbox=[120, 356, 280, 371]),
            extraction_method="llm_table",
        ),
        Record(
            record_id="10.1016_j.msea.2023.145678_temperature_1",
            source_id="10.1016/j.msea.2023.145678",
            field_name="temperature",
            field_value=200,
            field_unit="°C",
            trace_id="doc1_p3_tb1_h1",
            provenance=Provenance(page=3, bbox=[100, 300, 150, 315]),
            extraction_method="llm_text",
        ),
        Record(
            record_id="10.1016_j.msea.2023.145678_elongation_1",
            source_id="10.1016/j.msea.2023.145678",
            field_name="elongation",
            field_value=12.5,
            field_unit="%",
            trace_id="doc1_p3_tb2_r3",
            provenance=Provenance(page=3, bbox=[120, 372, 280, 387]),
            extraction_method="llm_table",
        ),

        # ── 论文2 ──
        Record(
            record_id="10.1007_s11661-022-06789_yield_strength_2",
            source_id="10.1007/s11661-022-06789",
            field_name="yield_strength",
            field_value=438,
            field_unit="MPa",
            trace_id="doc2_p5_tb1_r3",
            provenance=Provenance(page=5, bbox=[90, 420, 250, 435]),
            extraction_method="llm_table",
        ),
        Record(
            record_id="10.1007_s11661-022-06789_tensile_strength_2",
            source_id="10.1007/s11661-022-06789",
            field_name="tensile_strength",
            field_value=505,
            field_unit="MPa",
            trace_id="doc2_p5_tb1_r4",
            provenance=Provenance(page=5, bbox=[90, 436, 250, 451]),
            extraction_method="llm_table",
        ),
        Record(
            record_id="10.1007_s11661-022-06789_temperature_2",
            source_id="10.1007/s11661-022-06789",
            field_name="temperature",
            field_value=120,
            field_unit="°C",
            trace_id="doc2_p5_tb1_h2",
            provenance=Provenance(page=5, bbox=[90, 396, 150, 411]),
            extraction_method="llm_text",
        ),
        Record(
            record_id="10.1007_s11661-022-06789_elongation_2",
            source_id="10.1007/s11661-022-06789",
            field_name="elongation",
            field_value=14.2,
            field_unit="%",
            trace_id="doc2_p5_tb1_r5",
            provenance=Provenance(page=5, bbox=[90, 452, 250, 467]),
            extraction_method="llm_table",
        ),
    ],
)

def get_mock_data_json() -> dict:
    """将 mock GroundedData 转为字典（模拟 JSON 输入）。"""
    return mock_grounded_data.model_dump()
