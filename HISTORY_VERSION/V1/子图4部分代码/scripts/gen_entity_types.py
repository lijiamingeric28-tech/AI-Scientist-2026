# -*- coding: utf-8 -*-
"""生成 entity_types_astrophysics 配置段 (V4: Simbad otypes.list 全量 154 类型)。

用法: python scripts/gen_entity_types.py > /tmp/entity_types_section.yaml
然后人工核对后追加到 configs/quality_rules.yaml 末尾。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

# (code, name, desc, parent, candi) — 8 大类, 层级对齐 otypes.list HIERARCHY 列
STARS = [
    ("*", "star", "Star", None, False),
    ("Ma*", "massive_star", "Massive Star", "*", True),
    ("bC*", "beta_cephei_variable", "beta Cep Variable", "Ma*", True),
    ("sg*", "supergiant", "Evolved Supergiant", "Ma*", True),
    ("s*r", "red_supergiant", "Red Supergiant", "sg*", True),
    ("s*y", "yellow_supergiant", "Yellow Supergiant", "sg*", True),
    ("s*b", "blue_supergiant", "Blue Supergiant", "sg*", True),
    ("WR*", "wolf_rayet_star", "Wolf-Rayet", "s*b", True),
    ("N*", "neutron_star", "Neutron Star", "Ma*", True),
    ("Psr", "pulsar", "Pulsar", "N*", False),
    ("Y*O", "young_stellar_object", "Young Stellar Object", "*", True),
    ("Or*", "orion_variable", "Orion Variable", "Y*O", False),
    ("TT*", "t_tauri_star", "T Tauri Star", "Y*O", True),
    ("Ae*", "herbig_ae_be_star", "Herbig Ae/Be Star", "Y*O", True),
    ("out", "outflow", "Outflow", "Y*O", True),
    ("HH", "herbig_haro_object", "Herbig-Haro Object", "out", False),
    ("MS*", "main_sequence_star", "Main Sequence Star", "*", True),
    ("Be*", "be_star", "Be Star", "MS*", True),
    ("BS*", "blue_straggler", "Blue Straggler", "MS*", True),
    ("SX*", "sx_phe_variable", "SX Phe Variable", "BS*", False),
    ("gD*", "gamma_dor_variable", "gamma Dor Variable", "MS*", False),
    ("dS*", "delta_scuti_variable", "delta Sct Variable", "MS*", False),
    ("Ev*", "evolved_star", "Evolved Star", "*", True),
    ("RG*", "red_giant_star", "Red Giant Branch star", "Ev*", True),
    ("HS*", "hot_subdwarf", "Hot Subdwarf", "Ev*", True),
    ("HB*", "horizontal_branch_star", "Horizontal Branch Star", "Ev*", True),
    ("RR*", "rr_lyrae_variable", "RR Lyrae Variable", "HB*", True),
    ("WV*", "type_ii_cepheid", "Type II Cepheid Variable", "Ev*", True),
    ("Ce*", "cepheid", "Cepheid Variable", "Ev*", True),
    ("cC*", "classical_cepheid", "Classical Cepheid Variable", "Ce*", False),
    ("C*", "carbon_star", "Carbon Star", "Ev*", True),
    ("S*", "s_star", "S Star", "Ev*", True),
    ("LP*", "long_period_variable", "Long-Period Variable", "Ev*", True),
    ("AB*", "agb_star", "Asymptotic Giant Branch Star", "Ev*", True),
    ("Mi*", "mira_variable", "Mira Variable", "AB*", True),
    ("OH*", "oh_ir_star", "OH/IR Star", "Ev*", True),
    ("pA*", "post_agb_star", "Post-AGB Star", "Ev*", True),
    ("RV*", "rv_tauri_variable", "RV Tauri Variable", "Ev*", True),
    ("PN", "planetary_nebula", "Planetary Nebula", "Ev*", True),
    ("WD*", "white_dwarf", "White Dwarf", "Ev*", True),
    ("Pe*", "chemically_peculiar_star", "Chemically Peculiar Star", "*", True),
    ("a2*", "alpha2_cvn_variable", "alpha2 CVn Variable", "Pe*", True),
    ("RC*", "r_crb_variable", "R CrB Variable", "Pe*", True),
    ("**", "double_star", "Double or Multiple Star", "*", True),
    ("EB*", "eclipsing_binary", "Eclipsing Binary", "**", True),
    ("El*", "ellipsoidal_variable", "Ellipsoidal Variable", "**", True),
    ("SB*", "spectroscopic_binary", "Spectroscopic Binary", "**", True),
    ("RS*", "rs_cvn_variable", "RS CVn Variable", "**", True),
    ("BY*", "by_dra_variable", "BY Dra Variable", "**", True),
    ("Sy*", "symbiotic_star", "Symbiotic Star", "**", True),
    ("XB*", "xray_binary", "X-ray Binary", "**", True),
    ("LXB", "low_mass_xray_binary", "Low Mass X-ray Binary", "XB*", True),
    ("HXB", "high_mass_xray_binary", "High Mass X-ray Binary", "XB*", True),
    ("CV*", "cataclysmic_binary", "Cataclysmic Binary", "**", True),
    ("No*", "classical_nova", "Classical Nova", "CV*", True),
    ("SN*", "supernova", "SuperNova", "*", True),
    ("LM*", "low_mass_star", "Low-mass Star", "*", True),
    ("BD*", "brown_dwarf", "Brown Dwarf", "LM*", True),
    ("Pl", "exoplanet", "Extra-solar Planet", "*", True),
    ("V*", "variable_star", "Variable Star", "*", True),
    ("Ir*", "irregular_variable", "Irregular Variable", "V*", False),
    ("Er*", "eruptive_variable", "Eruptive Variable", "V*", True),
    ("Ro*", "rotating_variable", "Rotating Variable", "V*", True),
    ("Pu*", "pulsating_variable", "Pulsating Variable", "V*", True),
    ("Em*", "emission_line_star", "Emission-line Star", "*", False),
    ("PM*", "high_proper_motion_star", "High Proper Motion Star", "*", False),
    ("HV*", "high_velocity_star", "High Velocity Star", "*", False),
]
STAR_SETS = [
    ("Cl*", "cluster_of_stars", "Cluster of Stars", None, True),
    ("GlC", "globular_cluster", "Globular Cluster", "Cl*", True),
    ("OpC", "open_cluster", "Open Cluster", "Cl*", False),
    ("As*", "stellar_association", "Association of Stars", None, True),
    ("St*", "stellar_stream", "Stellar Stream", "As*", False),
    ("MGr", "moving_group", "Moving Group", "As*", False),
]
ISM = [
    ("ISM", "ism_object", "Interstellar Medium Object", None, False),
    ("SFR", "star_forming_region", "Star Forming Region", "ISM", False),
    ("HII", "hii_region", "HII Region", "ISM", False),
    ("Cld", "cloud", "Cloud", "ISM", False),
    ("GNe", "nebula", "Nebula", "Cld", False),
    ("RNe", "reflection_nebula", "Reflection Nebula", "GNe", False),
    ("MoC", "molecular_cloud", "Molecular Cloud", "Cld", False),
    ("DNe", "dark_cloud", "Dark Cloud (nebula)", "Cld", False),
    ("glb", "globule", "Globule (low-mass dark cloud)", "Cld", False),
    ("CGb", "cometary_globule", "Cometary Globule / Pillar", "Cld", False),
    ("HVC", "high_velocity_cloud", "High-velocity Cloud", "Cld", False),
    ("cor", "dense_core", "Dense Core", "ISM", False),
    ("bub", "bubble", "Bubble", "ISM", False),
    ("SNR", "supernova_remnant", "SuperNova Remnant", "ISM", True),
    ("sh", "interstellar_shell", "Interstellar Shell", "ISM", False),
    ("flt", "interstellar_filament", "Interstellar Filament", "ISM", False),
]
GALAXIES = [
    ("G", "galaxy", "Galaxy", None, True),
    ("LSB", "low_surface_brightness_galaxy", "Low Surface Brightness Galaxy", "G", False),
    ("bCG", "blue_compact_galaxy", "Blue Compact Galaxy", "G", False),
    ("SBG", "starburst_galaxy", "Starburst Galaxy", "G", False),
    ("H2G", "hii_galaxy", "HII Galaxy", "G", False),
    ("EmG", "emission_line_galaxy", "Emission-line galaxy", "G", False),
    ("AGN", "agn", "Active Galaxy Nucleus", "G", True),
    ("SyG", "seyfert_galaxy", "Seyfert Galaxy", "AGN", False),
    ("Sy1", "seyfert_1_galaxy", "Seyfert 1 Galaxy", "SyG", False),
    ("Sy2", "seyfert_2_galaxy", "Seyfert 2 Galaxy", "SyG", False),
    ("rG", "radio_galaxy", "Radio Galaxy", "AGN", False),
    ("LIN", "liner", "LINER-type Active Galaxy Nucleus", "AGN", False),
    ("QSO", "quasar", "Quasar", "AGN", True),
    ("Bla", "blazar", "Blazar", "QSO", True),
    ("BLL", "bl_lac", "BL Lac", "Bla", True),
    ("GiP", "galaxy_in_pair", "Galaxy in Pair of Galaxies", "G", False),
    ("GiG", "galaxy_in_group", "Galaxy towards a Group of Galaxies", "G", False),
    ("GiC", "galaxy_in_cluster", "Galaxy towards a Cluster of Galaxies", "G", False),
    ("BiC", "brightest_cluster_galaxy", "Brightest Galaxy in a Cluster (BCG)", "GiC", False),
]
GALAXY_SETS = [
    ("IG", "interacting_galaxies", "Interacting Galaxies", None, False),
    ("PaG", "galaxy_pair", "Pair of Galaxies", None, False),
    ("GrG", "galaxy_group", "Group of Galaxies", None, True),
    ("CGG", "compact_group_of_galaxies", "Compact Group of Galaxies", "GrG", False),
    ("ClG", "galaxy_cluster", "Cluster of Galaxies", None, True),
    ("PCG", "protocluster", "Proto Cluster of Galaxies", None, True),
    ("SCG", "supercluster", "Supercluster of Galaxies", None, True),
    ("vid", "underdense_region", "Underdense Region of the Universe", None, False),
]
GRAVITATION = [
    ("grv", "gravitational_source", "Gravitational Source", None, False),
    ("Lev", "microlensing_event", "(Micro)Lensing Event", "grv", False),
    ("gLS", "gravitational_lens_system", "Gravitational Lens System (lens+images)", "grv", True),
    ("gLe", "gravitational_lens", "Gravitational Lens", "gLS", True),
    ("LeI", "lensed_image", "Gravitationally Lensed Image", "gLS", True),
    ("LeG", "lensed_galaxy_image", "Gravitationally Lensed Image of a Galaxy", "LeI", False),
    ("LeQ", "lensed_quasar_image", "Gravitationally Lensed Image of a Quasar", "LeI", False),
    ("BH", "black_hole", "Black Hole", "grv", True),
    ("GWE", "gravitational_wave_event", "Gravitational Wave Event", "grv", False),
]
SPECTRAL = [
    ("ev", "transient_event", "Transient Event", None, False),
    ("var", "variable_source", "Variable source", None, False),
    ("Rad", "radio_source", "Radio Source", None, False),
    ("mR", "metric_radio_source", "Metric Radio Source", "Rad", False),
    ("cm", "centimetric_radio_source", "Centimetric Radio Source", "Rad", False),
    ("mm", "millimetric_radio_source", "Millimetric Radio Source", "Rad", False),
    ("smm", "submillimetric_source", "Sub-Millimetric Source", "Rad", False),
    ("HI", "hi_source", "HI (21cm) Source", "Rad", False),
    ("rB", "radio_burst", "Radio Burst", "Rad", False),
    ("Mas", "maser", "Maser", "Rad", False),
    ("IR", "infrared_source", "Infra-Red Source", None, False),
    ("FIR", "far_infrared_source", "Far-IR source", "IR", False),
    ("MIR", "mid_infrared_source", "Mid-IR Source", "IR", False),
    ("NIR", "near_infrared_source", "Near-IR Source", "IR", False),
    ("Opt", "optical_source", "Optical Source", None, False),
    ("EmO", "emission_object", "Emission Object", "Opt", False),
    ("blu", "blue_object", "Blue Object", "Opt", False),
    ("UV", "uv_source", "UV-emission Source", None, False),
    ("X", "xray_source", "X-ray Source", None, False),
    ("ULX", "ultraluminous_xray_source", "Ultra-luminous X-ray Source", "X", True),
    ("gam", "gamma_ray_source", "Gamma-ray Source", None, False),
    ("gB", "gamma_ray_burst", "Gamma-ray Burst", "gam", False),
]
MISC = [
    ("mul", "blend", "Composite Object, Blend", None, False),
    ("err", "not_an_object", "Not an Object (Error, Artefact)", None, False),
    ("PoC", "part_of_cloud", "Part of Cloud", None, False),
    ("PoG", "part_of_galaxy", "Part of a Galaxy", None, False),
    ("?", "unknown_object", "Object of Unknown Nature", None, False),
    ("reg", "sky_region", "Region defined in the Sky", None, False),
]

# 语义类型关联 (sem) — 关联 semantic_types_astrophysics 键
SEM_MAP = {
    "star": ["effective_temperature","stellar_mass","stellar_radius","luminosity","age","surface_gravity","metallicity","radial_velocity","proper_motion_ra","proper_motion_dec","apparent_magnitude","spectral_type"],
    "massive_star": ["effective_temperature","stellar_mass","luminosity","age"],
    "supergiant": ["effective_temperature","stellar_mass","stellar_radius","luminosity","surface_gravity"],
    "red_supergiant": ["effective_temperature","stellar_radius","luminosity"],
    "blue_supergiant": ["effective_temperature","luminosity"],
    "wolf_rayet_star": ["effective_temperature","stellar_mass","luminosity"],
    "neutron_star": ["stellar_mass","stellar_radius","luminosity"],
    "pulsar": ["stellar_mass","age","dispersion_measure"],
    "young_stellar_object": ["effective_temperature","luminosity","age"],
    "t_tauri_star": ["effective_temperature","surface_gravity","luminosity","age"],
    "herbig_ae_be_star": ["effective_temperature","luminosity","age"],
    "main_sequence_star": ["effective_temperature","stellar_mass","stellar_radius","luminosity","surface_gravity"],
    "be_star": ["effective_temperature","stellar_mass","luminosity","rotational_velocity"],
    "evolved_star": ["effective_temperature","stellar_radius","luminosity","age","surface_gravity"],
    "red_giant_star": ["effective_temperature","stellar_radius","luminosity"],
    "horizontal_branch_star": ["effective_temperature","luminosity","metallicity","age"],
    "rr_lyrae_variable": ["effective_temperature","luminosity","metallicity"],
    "cepheid": ["effective_temperature","luminosity","age","distance"],
    "classical_cepheid": ["luminosity","distance","age"],
    "carbon_star": ["effective_temperature","luminosity"],
    "agb_star": ["effective_temperature","luminosity","stellar_radius"],
    "mira_variable": ["effective_temperature","luminosity"],
    "planetary_nebula": ["effective_temperature","luminosity","age"],
    "white_dwarf": ["effective_temperature","stellar_mass","stellar_radius","surface_gravity","age"],
    "double_star": ["stellar_mass","luminosity","orbital_period"],
    "eclipsing_binary": ["stellar_mass","luminosity","orbital_period"],
    "spectroscopic_binary": ["stellar_mass","radial_velocity","orbital_period"],
    "xray_binary": ["luminosity","orbital_period"],
    "low_mass_xray_binary": ["luminosity","orbital_period"],
    "high_mass_xray_binary": ["luminosity","orbital_period"],
    "cataclysmic_binary": ["luminosity","orbital_period"],
    "classical_nova": ["luminosity","age"],
    "supernova": ["luminosity","age","distance"],
    "low_mass_star": ["effective_temperature","stellar_mass","stellar_radius"],
    "brown_dwarf": ["effective_temperature","stellar_mass","stellar_radius"],
    "exoplanet": ["planet_radius","planet_mass","orbital_period"],
    "variable_star": ["luminosity"],
    "pulsating_variable": ["luminosity","effective_temperature"],
    "emission_line_star": ["effective_temperature","luminosity"],
    "cluster_of_stars": ["age","distance","metallicity"],
    "globular_cluster": ["age","metallicity","distance"],
    "open_cluster": ["age","distance","metallicity"],
    "stellar_association": ["age","distance"],
    "ism_object": ["extinction","distance"],
    "star_forming_region": ["age","luminosity","distance"],
    "hii_region": ["luminosity","flux_density","distance"],
    "cloud": ["extinction"],
    "nebula": ["extinction","luminosity"],
    "molecular_cloud": ["extinction","distance"],
    "supernova_remnant": ["age","flux_density","distance","luminosity"],
    "galaxy": ["redshift","stellar_mass","distance","metallicity","extinction","luminosity","apparent_magnitude","radial_velocity","flux_density"],
    "low_surface_brightness_galaxy": ["stellar_mass","luminosity","redshift"],
    "blue_compact_galaxy": ["luminosity","metallicity","redshift"],
    "starburst_galaxy": ["luminosity","redshift","stellar_mass","flux_density"],
    "emission_line_galaxy": ["luminosity","redshift","flux_density"],
    "agn": ["luminosity","redshift","stellar_mass","flux_density"],
    "seyfert_galaxy": ["luminosity","redshift","flux_density"],
    "seyfert_1_galaxy": ["luminosity","redshift","flux_density"],
    "seyfert_2_galaxy": ["luminosity","redshift","flux_density"],
    "radio_galaxy": ["flux_density","redshift","luminosity"],
    "liner": ["luminosity","redshift","flux_density"],
    "quasar": ["luminosity","redshift","stellar_mass","flux_density"],
    "blazar": ["luminosity","flux_density","redshift"],
    "bl_lac": ["luminosity","flux_density","redshift"],
    "galaxy_in_cluster": ["redshift","distance"],
    "brightest_cluster_galaxy": ["redshift","luminosity","stellar_mass"],
    "galaxy_cluster": ["redshift","distance","luminosity"],
    "galaxy_group": ["redshift","distance"],
    "supercluster": ["redshift"],
    "interacting_galaxies": ["luminosity","redshift","stellar_mass"],
    "gravitational_lens_system": ["redshift","distance"],
    "black_hole": ["stellar_mass","luminosity"],
    "gravitational_wave_event": ["distance","luminosity"],
    "radio_source": ["flux_density"],
    "radio_burst": ["flux_density","dispersion_measure"],
    "maser": ["flux_density","luminosity"],
    "infrared_source": ["flux_density","luminosity"],
    "far_infrared_source": ["flux_density","luminosity"],
    "mid_infrared_source": ["flux_density"],
    "near_infrared_source": ["flux_density","apparent_magnitude"],
    "optical_source": ["apparent_magnitude","flux_density"],
    "uv_source": ["flux_density","luminosity"],
    "xray_source": ["flux_density","luminosity"],
    "ultraluminous_xray_source": ["luminosity","flux_density"],
    "gamma_ray_source": ["flux_density","luminosity"],
    "gamma_ray_burst": ["flux_density","luminosity","distance"],
    "transient_event": ["flux_density","luminosity"],
    "variable_source": ["luminosity","apparent_magnitude"],
}

ALL = [("stars", STARS), ("star_sets", STAR_SETS), ("ism", ISM),
       ("galaxies", GALAXIES), ("galaxy_sets", GALAXY_SETS),
       ("gravitation", GRAVITATION), ("spectral", SPECTRAL), ("misc", MISC)]
total = sum(len(g[1]) for g in ALL)
# 逐条对齐 otypes.list: 恒星 67 + 星集 6 + ISM 16 + 星系 19 + 星系集 8
#                    + 引力 9 + 光谱 22 + 杂项 6 = 153 (..N 辅助行为注释, 非独立类型)
assert total == 153, f"expect 153, got {total}"

out = []
out.append("# ── 天体物理实体类型: Simbad otypes.list 全量 (V4) ──")
out.append("# 理论依据: otypes.list (2026-07-30, Strasbourg); 名称/层级对齐官方分类")
out.append("# 消费方: tools/insight/entity_types.py (normalize/infer/ancestors/typical_range)")
out.append("entity_types_astrophysics:")
out.append('  version: "1.0"')
out.append('  source: "Simbad otypes.list, generated 2026-07-30"')
out.append("  categories:")
for cat, _ in ALL:
    out.append(f"    {cat}: {cat}")
out.append("  default_entity_type: galaxy")
out.append("  # ── 推断映射 (context_builder 消费): DB 目录 → 实体类型 (vizier_table_id 前缀) ──")
out.append("  catalog_inference:")
out.append('    "III/135A": star      # HD 恒星目录')
out.append('    "II/125": galaxy      # IRAS PSC')
out.append('    "VII/237": galaxy     # HYPERLEDA')
out.append('    "VII/26D": galaxy     # UGC')
out.append('    "VII/233": galaxy     # 2MASS XSC')
out.append("  # ── 字段名精确匹配 → 实体类型 (优先级 2) ──")
out.append("  field_inference:")
for fn, et in [("distance", "galaxy"), ("metallicity", "galaxy"), ("stellar_mass", "galaxy"),
               ("mass", "galaxy"), ("extinction", "galaxy"), ("radial_velocity", "galaxy"),
               ("redshift", "galaxy"), ("sp_t", "star"), ("spectral_type", "star")]:
    out.append(f"    {fn}: {et}")
out.append("  # ── 语义类型 → 实体类型 (优先级 3) ──")
out.append("  field_class_inference:")
for fn in ["parallax", "proper_motion_ra", "proper_motion_dec", "effective_temperature",
           "surface_gravity", "stellar_radius", "rotational_velocity"]:
    out.append(f"    {fn}: star")
out.append("  # ── 类型表 (154): key = Simbad code (引号包裹, * ? 为 YAML 保留字符) ──")
out.append("  types:")
for cat, entries in ALL:
    out.append(f"    # {cat}:")
    for code, name, desc, parent, candi in entries:
        sem = SEM_MAP.get(name, [])
        p = f'"{parent}"' if parent else "null"
        out.append(f'    "{code}": {{name: {name}, desc: "{desc}", cat: {cat}, parent: {p}, '
                   f'candi: {"true" if candi else "false"}, '
                   f'bad: {"true" if name in ("blend", "not_an_object", "unknown_object") else "false"}, '
                   f'kws: [{name}], sem: [{", ".join(sem)}]}}')
out.append("  # ── 典型范围 (实体级 sanity check, 单位 = semantic_types 键 units[0]) ──")
out.append("  typical_ranges:")
ranges = {
    "star": [("effective_temperature", [2000, 100000]), ("stellar_mass", [0.1, 100]),
             ("stellar_radius", [0.1, 1000]), ("luminosity", [3e29, 4e39]), ("surface_gravity", [-0.5, 9])],
    "main_sequence_star": [("effective_temperature", [2400, 50000]), ("stellar_mass", [0.08, 150]), ("surface_gravity", [4.0, 5.0])],
    "supergiant": [("stellar_radius", [100, 1500]), ("surface_gravity", [0.0, 1.5]), ("effective_temperature", [3000, 50000])],
    "red_supergiant": [("effective_temperature", [3000, 4500]), ("stellar_radius", [200, 1500])],
    "white_dwarf": [("effective_temperature", [5000, 100000]), ("stellar_mass", [0.2, 1.4]),
                    ("stellar_radius", [0.005, 0.05]), ("surface_gravity", [7.0, 9.0])],
    "neutron_star": [("stellar_mass", [1.0, 2.5]), ("stellar_radius", [1e-5, 5e-5])],
    "brown_dwarf": [("effective_temperature", [300, 2200]), ("stellar_mass", [0.005, 0.08])],
    "t_tauri_star": [("effective_temperature", [2590, 5110]), ("surface_gravity", [3.5, 4.5])],
    "red_giant_star": [("stellar_radius", [10, 100]), ("effective_temperature", [3000, 5000])],
    "galaxy": [("redshift", [-0.01, 10]), ("stellar_mass", [1e6, 1e13]), ("distance", [0.1, 1e9]),
               ("metallicity", [-3.0, 1.0]), ("extinction", [0, 5]), ("luminosity", [1e38, 1e48])],
    "agn": [("luminosity", [1e40, 1e48]), ("stellar_mass", [1e7, 1e12]), ("redshift", [0, 10])],
    "quasar": [("luminosity", [1e45, 1e48]), ("stellar_mass", [1e8, 1e11]), ("redshift", [0.1, 8])],
    "supernova_remnant": [("age", [4e-7, 1e-4])],
    "cluster_of_stars": [("age", [0.01, 13]), ("distance", [100, 1e5])],
    "exoplanet": [("planet_radius", [1, 22]), ("planet_mass", [1, 4000])],
    "hii_region": [("luminosity", [1e35, 1e41]), ("distance", [10, 1e5])],
    "starburst_galaxy": [("luminosity", [1e41, 1e47]), ("redshift", [0, 4])],
    "pulsar": [("dispersion_measure", [1, 3000]), ("age", [1e-5, 1e-2])],
}
def _fmt(x):
    """PyYAML 6.x 把 1e+38/1e-05 解析为字符串 — 统一输出完整十进制。"""
    if x == int(x) and abs(x) >= 1e6:
        return f"{int(x)}.0"
    if abs(x) < 1e-3 and x != 0:
        return f"{x:.10f}"
    return repr(x)

for et, items in ranges.items():
    out.append(f"    {et}:")
    for key, (lo, hi) in items:
        out.append(f"      {key}: [{_fmt(lo)}, {_fmt(hi)}]")
out.append(f"# 共 {total} 个类型 (8 大类)")

sys.stdout.write("\n".join(out) + "\n")
print(f"# total_types={total}", file=sys.stderr)
