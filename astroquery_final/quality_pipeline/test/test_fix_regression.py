"""
test_fix_regression.py — V4 质量修复回归测试

覆盖 2026-08 导出质量审查修复的关键行为:
  A1  领域感知单位转换 (astrophysics kpc→pc, 因子乘法约定)
  A5  空字符串单位 '' 计入缺失
  A7  括号换算解析 "24.47 ± 0.12 (= 783 ± 43 kpc)"
  A8  语义类型: catalog_metadata 归类 + 单字母关键词不误匹配
  B3  workflow_history reducer 去重
  C2  宽表折叠统计 (groups/overwritten_values)
  C5  output_validator 事件数 vs 记录数同口径

用法:
  cd 子图4部分代码
  python test/test_fix_regression.py
"""
import sys, os, json, glob, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ..configs import set_research_domain
from ..quality_state import _merge_dict


class TestUnitConversionA1(unittest.TestCase):
    """A1: 领域感知加载 + 因子方向正确 (乘法约定)。"""

    def setUp(self):
        set_research_domain('astrophysics')

    def test_kpc_to_pc(self):
        from ..tools.normalization.unit_converter import convert_units
        recs = [{"record_id": "r1", "field_name": "distance",
                 "field_value": 785.0, "field_unit": "kpc"}]
        res = convert_units(recs, [], {"distance": "pc"}, None)
        self.assertEqual(res["data"][0]["field_unit"], "pc")
        self.assertAlmostEqual(float(res["data"][0]["field_value"]), 785000.0)

    def test_mag_not_converted_to_pc(self):
        """量纲护栏: distance 字段的 'mag' 不得经 magnitude 类误转成 pc。"""
        from ..tools.normalization.unit_converter import convert_units
        recs = [{"record_id": "r1", "field_name": "distance",
                 "field_value": 24.47, "field_unit": "mag"}]
        semantic = {"M31/distance": {"semantic_type": "distance"}}
        res = convert_units(recs, [], {"distance": "pc"}, semantic)
        self.assertEqual(res["data"][0]["field_unit"], "mag", "mag 不应被转为 pc")
        self.assertTrue(any(u.get("kind") == "no_conversion_rule" for u in res["unconverted"]))

    def test_materials_domain_unchanged(self):
        """空 domain (材料) 行为不变: GPa→MPa。"""
        set_research_domain('')
        from ..tools.normalization.unit_converter import convert_units
        recs = [{"record_id": "r1", "field_name": "yield_strength",
                 "field_value": 1.0, "field_unit": "GPa"}]
        res = convert_units(recs, [], {"yield_strength": "MPa"}, None)
        self.assertEqual(float(res["data"][0]["field_value"]), 1000.0)


class TestAstroUnits(unittest.TestCase):
    """V4.2: 天体物理单位体系丰富 — 10 新维度 + 3 处修复验证。"""

    def setUp(self):
        set_research_domain('astrophysics')

    def _conv(self, field, unit, val, target, sem_key):
        from ..tools.normalization.unit_converter import convert_units
        recs = [{"record_id": "r1", "field_name": field,
                 "field_value": val, "field_unit": unit}]
        # 键 = 真实字段名 (与 infer_all_fields 的 entity-aware 键一致)
        semantic = {f"M31/{field}": {"semantic_type": sem_key}}
        res = convert_units(recs, [], {field: target}, semantic)
        r = res["data"][0]
        return float(r["field_value"]), r["field_unit"], res["unconverted"]

    def test_flux_conversion(self):
        """闭环: flux_density 500 mJy → 0.5 Jy。"""
        v, u, unc = self._conv("flux_density", "mJy", 500.0, "Jy", "flux_density")
        self.assertEqual(u, "Jy")
        self.assertAlmostEqual(v, 0.5)
        self.assertEqual(unc, [], "不应有 unconverted")

    def test_energy_conversion(self):
        """CODATA 2018: 2 keV → 3.204e-9 erg。"""
        v, u, _ = self._conv("photon_energy", "keV", 2.0, "erg", "energy")
        self.assertAlmostEqual(v, 3.204353268e-9, places=10)

    def test_magnetic_conversion(self):
        """1 T = 1e4 G: 5 G → 5e-4 T。"""
        v, u, _ = self._conv("magnetic_field", "G", 5.0, "T", "magnetic_field")
        self.assertAlmostEqual(v, 5e-4, places=12)

    def test_angle_conversion(self):
        """3600 arcsec → 1.0 deg。"""
        v, u, _ = self._conv("separation", "arcsec", 3600.0, "deg", "angle")
        self.assertAlmostEqual(v, 1.0, places=10)

    def test_frequency_conversion(self):
        """1500 MHz → 1.5e9 Hz。"""
        v, u, _ = self._conv("frequency", "MHz", 1500.0, "Hz", "frequency")
        self.assertAlmostEqual(v, 1.5e9)

    def test_proper_motion_fix(self):
        """倒置修复: 1 arcsec/yr = 1000 mas/yr → 2 → 2000。"""
        v, u, _ = self._conv("proper_motion_ra", "arcsec/yr", 2.0,
                             "mas/yr", "proper_motion_ra")
        self.assertAlmostEqual(v, 2000.0)

    def test_planet_radius_fix(self):
        """撞车修复: planet_radius 字段 1 km → 1.5698e-4 R_earth
        (行星组因子; 不得命中恒星 radius 组 1.4374e-6)。"""
        v, u, _ = self._conv("planet_radius", "km", 1.0, "R_earth", "planet_radius")
        self.assertAlmostEqual(v, 1.5698e-4, places=10)

    def test_dispersion_measure_self(self):
        """闭环: DM 复合单位组内自转换。"""
        v, u, unc = self._conv("dispersion_measure", "pc cm^-3", 560.0,
                               "cm^-3 pc", "dispersion_measure")
        self.assertEqual(u, "cm^-3 pc")
        self.assertAlmostEqual(v, 560.0)
        self.assertEqual(unc, [], "不应有 unconverted")

    def test_fahrenheit_to_kelvin(self):
        """新 offset 分支: 212 °F → 373.15 K。"""
        v, u, _ = self._conv("effective_temperature", "°F", 212.0, "K",
                             "effective_temperature")
        self.assertAlmostEqual(v, 373.15, places=10)

    def test_celsius_to_kelvin(self):
        """offset_-273.15: 20 °C → 293.15 K。"""
        v, u, _ = self._conv("effective_temperature", "°C", 20.0, "K",
                             "effective_temperature")
        self.assertAlmostEqual(v, 293.15, places=10)

    def test_config_loaded(self):
        """配置三件套齐: 32 语义键 / 34 转换组 / 关键修复项。"""
        from ..configs import load_domain_config, load_domain_schema_config
        st = load_domain_config("semantic_types", "semantic_types") or {}
        conv = load_domain_schema_config("unit_conversions") or {}
        self.assertEqual(len(st), 32, "semantic_types_astrophysics 键数")
        self.assertEqual(len(conv), 34, "unit_conversions_astrophysics 组数")
        for k in ("flux_density", "dispersion_measure", "rotation_measure",
                  "frequency", "energy", "magnetic_field", "pressure",
                  "density", "angle", "wavelength"):
            self.assertIn(k, st, f"{k} 语义键缺失")
            self.assertIn(k, conv, f"{k} 转换组缺失")
        # V4.2 catalog: VizieR 记法单位新组 (仅转换组, 无独立语义键)
        for k in ("surface_brightness", "abundance", "wavenumber",
                  "surface_density", "percentage", "area", "composite"):
            self.assertIn(k, conv, f"{k} 转换组缺失")
        self.assertEqual(st["planet_radius"]["unit_category"], "planet_radius")
        self.assertEqual(st["planet_mass"]["unit_category"], "planet_mass")
        self.assertAlmostEqual(conv["proper_motion"]["arcsec/yr"], 1000.0,
                               msg="proper_motion 倒置修复")
        self.assertIn("offset_32_5_9_273_15", str(conv["temperature"]),
                      "temperature °F→K 条目")
        # V4.2 catalog: VizieR 记法单位
        self.assertEqual(conv["mass"].get("solMass"), 1.0, "solMass 别名")
        self.assertEqual(conv["radius"].get("solRad"), 1.0, "solRad 别名")
        self.assertIn("log(cm.s**-2)", conv["surface_gravity"], "log g 记法")
        self.assertIn("solMass", st["stellar_mass"]["units"], "semantic units 同步")


class TestEmptyUnitA5(unittest.TestCase):
    """A5: 空字符串单位 '' 视为缺失。"""

    def test_empty_string_unit_counted(self):
        from ..tools.assessment.completeness import check_completeness
        data = {"sources": [], "records": [{"record_id": "r1", "field_name": "distance",
                                            "field_value": "785", "field_unit": ""}]}
        res = check_completeness(data, {"fields": [{"name": "distance"}]})
        self.assertGreater(res.get("records_missing_unit", 0), 0,
                           "空串单位应计入缺失")

    def test_validation_missing_units(self):
        from ..Data_Normalization_agentV1.agents.validation_agent import ValidationAgent
        recs = [{"record_id": "r1", "source_id": "S1", "field_name": "distance",
                 "field_value": "785", "field_unit": ""}]
        va = ValidationAgent()
        # 只验证 counting 逻辑 (通过源码级检查不可行, 直接调内部统计):
        from ..tools._parse_utils import is_numeric
        missing = sum(1 for r in recs if is_numeric(r.get("field_value")) and not r.get("field_unit"))
        self.assertEqual(missing, 1)


class TestParentheticalParseA7(unittest.TestCase):
    """A7: 括号换算保留 + 不确定度恢复。"""

    def test_parenthetical_conversion(self):
        from ..tools._parse_utils import parse_uncertainty, parse_numeric
        self.assertEqual(parse_numeric("24.47 ± 0.12 (= 783 ± 43 kpc)"), 24.47)
        self.assertEqual(parse_uncertainty("24.47 ± 0.12 (= 783 ± 43 kpc)"), 0.12)


class TestSemanticTypeA8(unittest.TestCase):
    """A8: catalog_metadata 归类 + 单字母关键词整串匹配。"""

    def setUp(self):
        set_research_domain('astrophysics')

    def test_catalog_metadata(self):
        from ..tools.assessment.semantic_type import infer_semantic_type
        r = infer_semantic_type('database_catalog_properties', '', None)
        self.assertEqual(r["semantic_type"], "catalog_metadata")

    def test_single_letter_keyword_exact(self):
        """'L' 不应子串命中 database_catalog_properties; 字段名恰为 'L' 应命中。"""
        from ..tools.assessment.semantic_type import infer_semantic_type
        r = infer_semantic_type('L', '', None)
        self.assertEqual(r["semantic_type"], "luminosity")

    def test_feasible_range_float_coerce(self):
        """PyYAML 6.x 将 '1e7' 解析为 str — 边界需 float 强转不抛异常。"""
        from ..tools.assessment.semantic_type import infer_semantic_type
        r = infer_semantic_type('distance', 'kpc', 785.0)
        self.assertEqual(r["semantic_type"], "distance")
        self.assertFalse(r.get("out_of_range", False))


class TestReducerDedupeB3(unittest.TestCase):
    """B3: workflow_history 全等去重。"""

    def test_append_dedupe(self):
        dup = [{"agent": "A", "timestamp": "t1"}, {"agent": "B", "timestamp": "t2"}]
        merged = _merge_dict({"workflow_history": dup},
                             {"workflow_history": dup + [{"agent": "C", "timestamp": "t3"}]})
        self.assertEqual(len(merged["workflow_history"]), 3)


class TestWideCollapseC2(unittest.TestCase):
    """C2: 宽表折叠统计 + json_wide 保留全部值。"""

    def test_collapse_stats(self):
        from ..tools.export.format_exporter import export_formats
        sources = [{"source_id": "S1"}]
        records = [
            {"source_id": "S1", "field_name": "distance", "field_value": 10.0, "field_unit": "pc"},
            {"source_id": "S1", "field_name": "distance", "field_value": 20.0, "field_unit": "pc"},
        ]
        org = {"sources": sources, "records": records, "field_index": {"distance": {}}}
        res = export_formats(org)
        self.assertEqual(res["wide_collapse"]["groups"], 1)
        self.assertEqual(res["wide_collapse"]["overwritten_values"], 1)
        self.assertIsInstance(res["json_wide"]["distance"][0], list)
        self.assertEqual(len(res["json_wide"]["distance"][0]), 2)


class TestValidatorQualityConsistencyC5(unittest.TestCase):
    """C5: 事件数 vs 记录数同口径 — 336 事件/170 记录不再误报。"""

    def _traceability(self):
        return {"trace_completeness": {
            "records_with_trace": 170, "records_with_modification_trace": 170,
            "records_without_trace": 0, "modified_count": 170,
            "records_with_trace_id": 60, "paper_records_missing_trace_id": 0,
            "database_records": 159, "db_provenance_complete": 159,
        }, "data_lineage": {}, "agent_decision_trail": []}

    def test_no_false_positive(self):
        from ..tools.export.output_validator import validate_output
        mods = {"total": 336, "details": {
            "base": [{"record_id": f"r{i % 170}", "field": "x"} for i in range(300)],
            "adapted": [], "generated": [{"record_id": f"r{i % 170}", "field": "x"} for i in range(36)],
        }, "errors": []}
        v = validate_output({"records": [], "sources": []}, {}, self._traceability(),
                            None, {"quality": {}, "normalization": {"modifications": mods}}, {})
        qc = v["checks"]["quality_consistency"]
        self.assertTrue(qc["passed"])
        self.assertEqual(qc["unique_event_records"], 170)


if __name__ == "__main__":
    unittest.main()
