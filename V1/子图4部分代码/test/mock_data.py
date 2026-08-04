"""
mock_data.py — V3.0 天文数据 Mock

提供天文领域 (FRB) 的多源测试数据, 包含 V2 Record 字段
(measurement_method, condition_tags, extraction_confidence, context_snippet).
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── V3.0: 直接用 dict 构造, 避免 Pydantic V1 模型限制 V2 字段 ──

def get_mock_data_json() -> dict:
    """返回天文领域 (FRB) 的多源测试数据 — V3.0 多源方差分析专用。

    设计意图:
      - FRB 121102: 3篇论文测量 DM, 不同波段 → condition_variance (正常, Export)
      - FRB 121102: 2篇论文测量 flux, 不同仪器 → methodological_variance (正常, Export)
      - FRB 180916: 2篇论文测量 DM, 不同年份 → temporal_variation (正常, Export)
      - 一条 anomaly: 低 extraction_confidence + 偏离较大的 redshift → extraction_error (Conflict)
      - 一条 duplicate: 相同 RA 值出现在两个 source 中
    """
    return {
        "schema_version": "2.0.0",
        "research_domain": "astrophysics",
        "sources": [
            {
                "source_id": "S001",
                "source_type": "paper",
                "doi": "10.1038/nature17140",
                "title": "A repeating fast radio burst",
                "authors": ["Spitler, L. G.", "Scholz, P."],
                "year": 2016,
                "journal": "Nature",
                "access_path": "./data/papers/S001.pdf",
                "retrieval_priority": 0.95,
                "abstract": "We report the discovery of a repeating fast radio burst FRB 121102...",
                "keywords": ["fast radio burst", "FRB", "radio transients"],
                "search_query": "repeating fast radio burst FRB detection",
                "search_rank": 1,
            },
            {
                "source_id": "S002",
                "source_type": "paper",
                "doi": "10.3847/2041-8213/ab4a7f",
                "title": "FRB 121102: Multi-band Observations with FAST and VLA",
                "authors": ["Li, D.", "Wang, P."],
                "year": 2023,
                "journal": "The Astrophysical Journal",
                "access_path": "./data/papers/S002.pdf",
                "retrieval_priority": 0.88,
                "abstract": "Multi-band observations of FRB 121102 using FAST L-band and VLA C-band...",
                "keywords": ["FRB 121102", "FAST", "VLA", "multi-wavelength"],
                "search_query": "FRB 121102 multi-band FAST VLA observation",
                "search_rank": 3,
            },
            {
                "source_id": "S003",
                "source_type": "paper",
                "doi": "10.1093/mnras/sty2622",
                "title": "The low-frequency perspective on FRB 121102",
                "authors": ["Marcote, B.", "Paragi, Z."],
                "year": 2018,
                "journal": "Monthly Notices of the Royal Astronomical Society",
                "access_path": "./data/papers/S003.pdf",
                "retrieval_priority": 0.82,
                "abstract": "Low-frequency observations of FRB 121102 at 150 MHz...",
                "keywords": ["FRB 121102", "LOFAR", "low-frequency"],
                "search_query": "FRB 121102 low frequency LOFAR observation",
                "search_rank": 5,
            },
        ],
        "records": [
            # ═══ FRB 121102 — dispersion_measure: 3 sources, 不同波段 (正常方差) ═══
            {
                "record_id": "S001_FRB121102_DM_0",
                "source_id": "S001",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "dispersion_measure",
                "field_value": "560",
                "field_unit": "cm^-3 pc",
                "trace_id": "doc1_p4",
                "provenance": {"page": 4, "bbox": [146, 1205, 1184, 1250]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.95,
                "context_snippet": "FRB 121102 observed with Arecibo at L-band. DM = 560 pc cm^-3...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["L-band", "Arecibo"],
            },
            {
                "record_id": "S002_FRB121102_DM_0",
                "source_id": "S002",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "dispersion_measure",
                "field_value": "565",
                "field_unit": "cm^-3 pc",
                "trace_id": "doc2_p3",
                "provenance": {"page": 3, "bbox": [100, 800, 1100, 840]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.90,
                "context_snippet": "We observed FRB 121102 with VLA at C-band (4-8 GHz). The DM is 565±3 pc cm^-3...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["C-band", "VLA"],
            },
            {
                "record_id": "S003_FRB121102_DM_0",
                "source_id": "S003",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "dispersion_measure",
                "field_value": "558",
                "field_unit": "cm^-3 pc",
                "trace_id": "doc3_p5",
                "provenance": {"page": 5, "bbox": [200, 600, 1000, 640]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.92,
                "context_snippet": "LOFAR low-frequency (150 MHz) observations of FRB 121102 give DM = 558 pc cm^-3...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["low-frequency", "LOFAR"],
            },

            # ═══ FRB 121102 — flux_density: 2 sources, 不同仪器 (正常方差) ═══
            {
                "record_id": "S001_FRB121102_flux_0",
                "source_id": "S001",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "flux_density",
                "field_value": "0.5",
                "field_unit": "Jy",
                "trace_id": "doc1_p4",
                "provenance": {"page": 4, "bbox": [146, 1300, 500, 1330]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.88,
                "context_snippet": "Peak flux density at 1.4 GHz: 0.5 Jy...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["L-band"],
            },
            {
                "record_id": "S002_FRB121102_flux_0",
                "source_id": "S002",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "flux_density",
                "field_value": "0.35",
                "field_unit": "Jy",
                "trace_id": "doc2_p4",
                "provenance": {"page": 4, "bbox": [100, 900, 500, 930]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.85,
                "context_snippet": "VLA C-band peak flux: 0.35 Jy...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["C-band"],
            },

            # ═══ FRB 180916 — dispersion_measure: 2 sources, 不同年份 (正常时间演化) ═══
            {
                "record_id": "S002_FRB180916_DM_0",
                "source_id": "S002",
                "entity_type": "FRB",
                "entity_name": "FRB 180916",
                "field_name": "dispersion_measure",
                "field_value": "349.2",
                "field_unit": "cm^-3 pc",
                "trace_id": "doc2_p6",
                "provenance": {"page": 6, "bbox": [100, 1000, 500, 1030]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.91,
                "context_snippet": "FRB 180916 DM measured as 349.2 pc cm^-3 in 2023 observation...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["L-band", "FAST"],
            },
            {
                "record_id": "S003_FRB180916_DM_0",
                "source_id": "S003",
                "entity_type": "FRB",
                "entity_name": "FRB 180916",
                "field_name": "dispersion_measure",
                "field_value": "348.8",
                "field_unit": "cm^-3 pc",
                "trace_id": "doc3_p7",
                "provenance": {"page": 7, "bbox": [200, 700, 500, 730]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.89,
                "context_snippet": "DM of FRB 180916 was 348.8 pc cm^-3 in 2018...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["L-band", "CHIME"],
            },

            # ═══ ANOMALY: 低 extraction_confidence + 偏离值 (应标记为 extraction_error) ═══
            {
                "record_id": "S001_FRB121102_redshift_0",
                "source_id": "S001",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "redshift",
                "field_value": "0.19",
                "field_unit": "",
                "trace_id": "doc1_p5",
                "provenance": {"page": 5, "bbox": [146, 1400, 400, 1430]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.25,
                "context_snippet": "The host galaxy redshift is uncertain, estimated at z ~ 0.19...",
                "measurement_method": "photometry",
                "condition_tags": ["optical"],
            },
            {
                "record_id": "S002_FRB121102_redshift_0",
                "source_id": "S002",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "redshift",
                "field_value": "0.192",
                "field_unit": "",
                "trace_id": "doc2_p8",
                "provenance": {"page": 8, "bbox": [100, 1200, 400, 1230]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.93,
                "context_snippet": "Host galaxy redshift confirmed at z = 0.1927 via Keck/DEIMOS spectroscopy...",
                "measurement_method": "spectroscopy",
                "condition_tags": ["optical", "Keck"],
            },

            # ═══ DUPLICATE: 相同 RA 值, 不同 source (应标记为 duplicate_observation) ═══
            {
                "record_id": "S001_FRB121102_RA_0",
                "source_id": "S001",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "right_ascension",
                "field_value": "05h31m58.7s",
                "field_unit": "",
                "trace_id": "doc1_p2",
                "provenance": {"page": 2, "bbox": [146, 500, 600, 530]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.95,
                "context_snippet": "Coordinates: RA = 05h31m58.7s, Dec = +33d08m52.5s...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["astrometry"],
            },
            {
                "record_id": "S003_FRB121102_RA_0",
                "source_id": "S003",
                "entity_type": "FRB",
                "entity_name": "FRB 121102",
                "field_name": "right_ascension",
                "field_value": "05h31m58.7s",
                "field_unit": "",
                "trace_id": "doc3_p2",
                "provenance": {"page": 2, "bbox": [200, 400, 600, 430]},
                "extraction_method": "vlm_text",
                "extraction_confidence": 0.90,
                "context_snippet": "Position: RA = 05h31m58.7s...",
                "measurement_method": "radio interferometry",
                "condition_tags": ["astrometry"],
            },
        ],
    }


def get_database_mock_data() -> dict:
    """返回 Gaia DR3 database 类型测试数据 — V3.1 database 兼容。

    Database schema 特征:
      - source_type: "database"
      - extraction_method: "database_query"
      - provenance: {db_table, key_column, key_value, raw_column}
      - 无 trace_id / extraction_confidence / context_snippet / measurement_method / condition_tags
      - field_name 使用原始 DB 列名 (Plx, Gmag, etc.)
    """
    return {
        "schema_version": "2.0.0",
        "research_domain": "astrophysics",
        "sources": [
            {
                "source_id": "SRC_DB_GAIA_DR3",
                "source_type": "database",
                "title": "Gaia DR3",
                "vizier_table_id": "I/355/gaiadr3",
                "description": "欧洲航天局 (ESA) 盖亚 (Gaia) 天体测量卫星第三版数据释放 (Data Release 3)。提供了前所未有精度的银河系及近邻天体三维位置、自洽运动与视差数据。",
                "reference_paper": "Gaia Collaboration et al., 2023, A&A, 674, A1",
                "bibcode": "2023A&A...674A...1G",
                "research_methodology": "基于空间光学天体测量学 (Space-based optical astrometry) 与 RVS 光谱学。利用双望远镜连续扫天，采用自洽天体测量网解算获得毫角秒至微角秒级精度的位置与视差，结合中分辨率光谱仪提取视向速度。",
                "observation_facility": "Gaia Space Observatory (ESA)",
                "waveband": "Optical (330 - 1050 nm, G/BP/RP bands)",
                "research_content": "主要包含 18 亿天体的高精度天体测量参数（RA, Dec, Parallax, PM）、三色测光 (G, BP, RP)、约 3300 万天体的视向速度 (RV) 等。",
            },
        ],
        "records": [
            # Gaia DR3 star: parallax (Plx)
            {
                "record_id": "REC_GAIA_DR3_5854013331201520640_Plx",
                "source_id": "SRC_DB_GAIA_DR3",
                "entity_type": "Star",
                "entity_name": "Gaia DR3 5854013331201520640",
                "field_name": "Plx",
                "field_value": "1.3421",
                "field_unit": "mas",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "I/355/gaiadr3",
                    "key_column": "Source",
                    "key_value": "5854013331201520640",
                    "raw_column": "Plx",
                },
            },
            # Gaia DR3 star: G-band magnitude
            {
                "record_id": "REC_GAIA_DR3_5854013331201520640_Gmag",
                "source_id": "SRC_DB_GAIA_DR3",
                "entity_type": "Star",
                "entity_name": "Gaia DR3 5854013331201520640",
                "field_name": "Gmag",
                "field_value": "15.234",
                "field_unit": "mag",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "I/355/gaiadr3",
                    "key_column": "Source",
                    "key_value": "5854013331201520640",
                    "raw_column": "Gmag",
                },
            },
            # Gaia DR3 star: BP magnitude
            {
                "record_id": "REC_GAIA_DR3_5854013331201520640_BPmag",
                "source_id": "SRC_DB_GAIA_DR3",
                "entity_type": "Star",
                "entity_name": "Gaia DR3 5854013331201520640",
                "field_name": "BPmag",
                "field_value": "15.891",
                "field_unit": "mag",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "I/355/gaiadr3",
                    "key_column": "Source",
                    "key_value": "5854013331201520640",
                    "raw_column": "BPmag",
                },
            },
            # Gaia DR3 star: effective temperature
            {
                "record_id": "REC_GAIA_DR3_5854013331201520640_Teff",
                "source_id": "SRC_DB_GAIA_DR3",
                "entity_type": "Star",
                "entity_name": "Gaia DR3 5854013331201520640",
                "field_name": "Teff",
                "field_value": "4520",
                "field_unit": "K",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "I/355/gaiadr3",
                    "key_column": "Source",
                    "key_value": "5854013331201520640",
                    "raw_column": "Teff",
                },
            },
            # Gaia DR3 star: radial velocity
            {
                "record_id": "REC_GAIA_DR3_5854013331201520640_RV",
                "source_id": "SRC_DB_GAIA_DR3",
                "entity_type": "Star",
                "entity_name": "Gaia DR3 5854013331201520640",
                "field_name": "RV",
                "field_value": "-24.5",
                "field_unit": "km/s",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "I/355/gaiadr3",
                    "key_column": "Source",
                    "key_value": "5854013331201520640",
                    "raw_column": "RV",
                },
            },
        ],
    }


def get_mixed_mock_data() -> dict:
    """返回 paper + database 混合测试数据。"""
    paper_data = get_mock_data_json()
    db_data = get_database_mock_data()

    return {
        "schema_version": "2.0.0",
        "research_domain": "astrophysics",
        "sources": paper_data["sources"] + db_data["sources"],
        "records": paper_data["records"] + db_data["records"],
    }
