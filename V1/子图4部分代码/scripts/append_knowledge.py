# -*- coding: utf-8 -*-
"""追加 V4 知识库条目 (基于 70 次 websearch 调研, 理论为主数值锚点)。

用法: python scripts/append_knowledge.py
在 5 个知识库 yaml 的 entries 末尾追加新条目 (幂等: 按 id 去重)。
"""
import sys, io, yaml
sys.stdout.reconfigure(encoding='utf-8')
BASE = "data/insight_knowledge/astrophysics"

# ══════════════════════════════════════════════════════════
# reference_ranges.yaml +15
# ══════════════════════════════════════════════════════════
REFERENCE_RANGES = [
 dict(id="star_teff_luminosity_span", title="恒星 Teff/光度全域锚点", category="reference_range",
  tags=["star", "teff", "luminosity", "range"], applies_to={"fields": ["effective_temperature", "luminosity"], "entities": ["star"]},
  content="""正常恒星的有效温度与光度由核燃烧产能与表面辐射平衡共同决定, 跨度极大:
- Teff 约 2000-100000 K (M 矮星低温端 → O 型/白矮星高温端)
- 光度 1e-4 ~ 1e6 Lsun (褐矮星端 → 超巨星端)
超出此全域的 '恒星' 值几乎必为: 单位混淆、光度/星等混用, 或对象类型误判
(如星系/AGN 的光度被标成恒星字段)。
判定线索: 恒星光度与 Teff 满足 L ∝ R^2 T^4, 两者联合越界才可信。""",
  source="UNLV 主序表; OSU 恒星物理讲义", confidence="established"),
 dict(id="main_sequence_spectral_sequence", title="主序光谱型-温度序列", category="reference_range",
  tags=["main_sequence", "spectral", "teff"], applies_to={"fields": ["effective_temperature", "stellar_mass"], "entities": ["main_sequence_star"]},
  content="""OBAFGKM 是纯温度序: 表面温度决定电离态与分子平衡 (H Balmer 线 A0 最强,
TiO 分子带只出现在 M 型)。主序锚点: O 型 ~40000 K / 40 Msun, G 型 (太阳) ~5770 K,
M 型 ~3200 K / 0.3 Msun。
判定原理: 分型看吸收线相对强度; 金属丰度低会使金属线变弱、误判为更热型;
双星光谱叠加 (SB2) 会模糊线型。""",
  source="UNLV/UTK 主序数据表; LCO Types of Stars", confidence="established"),
 dict(id="ttaauri_star_parameters", title="T Tauri 星与前主序参数", category="reference_range",
  tags=["ttaauri", "pms", "yso"], applies_to={"fields": ["effective_temperature", "surface_gravity"], "entities": ["t_tauri_star", "young_stellar_object"]},
  content="""T Tauri 星是前主序 (PMS) 恒星, 仍在引力收缩、尚未点燃氢燃烧;
中心温度低于主序同型星, Teff 约 2590-5110 K (K0-M8.5), log g ~4。
经典 T Tauri (CTTS) 与弱线 T Tauri (WTTS) 的观测分界是 Hα 等值宽度 ~10 Å,
物理本质是吸积率是否高于 ~1e-8 Msun/yr — 吸积磁层把盘物质导向恒星表面。
判定线索: PMS 星 Teff 正常但年龄异常年轻 (<10 Myr), 或与分子云成协。""",
  source="Lada 1987; Hernández 2005; T Tauri 参数综述", confidence="established"),
 dict(id="white_dwarf_parameters", title="白矮星参数与简并本质", category="reference_range",
  tags=["white_dwarf", "degenerate"], applies_to={"fields": ["stellar_mass", "surface_gravity", "stellar_radius", "effective_temperature"], "entities": ["white_dwarf"]},
  content="""白矮星由电子简并压支撑, 无核聚变、只冷却, 是可靠的宇宙时钟。
质量分布主峰 ~0.6 Msun (单星演化产物), Chandrasekhar 极限 ~1.4 Msun (超限塌缩);
半径仅 ~0.01 Rsun (类地尺度), 表面重力 log g 7.0-8.5 (远高于主序的 ~4.4)。
光谱型由大气成分定: DA=H 大气 (Balmer 线), DB=He 大气。
判定线索: 高温 + 极低光度 + 高 log g 的组合即白矮星; 质量 >1.4 Msun 的
'白矮星' 记录必为错误 (应为中子星/黑洞或测量混淆)。""",
  source="Liebert 2005 ApJS; SDSS DR12 白矮星研究", confidence="established"),
 dict(id="giant_supergiant_radius", title="巨星/超巨星半径", category="reference_range",
  tags=["giant", "supergiant", "radius"], applies_to={"fields": ["stellar_radius"], "entities": ["red_giant_star", "supergiant", "red_supergiant"]},
  content="""巨星/超巨星是壳层氢/氦燃烧的膨胀态: 核心致密, 外包层因低表面重力而
剧烈膨胀。巨星半径 10-100 Rsun, 超巨星 >1000 Rsun (红超巨星可达 1500)。
物理原理: 同光谱型下巨星与矮星的判别是表面重力 (线展宽), 不是温度。
判定线索: 半径 ~1 Rsun 却标注超巨星 = 单位混淆 (Rsun/km); 半径 >2000 Rsun
的 '恒星' 需怀疑是大质量恒星+星风包层或双星混合。""",
  source="OSU HR 图讲义; PHY213 恒星性质讲义", confidence="established"),
 dict(id="galaxy_redshift_span", title="星系红移全域与演化", category="reference_range",
  tags=["galaxy", "redshift", "span"], applies_to={"fields": ["redshift"], "entities": ["galaxy"]},
  content="""星系红移覆盖 z 0-10: 近邻宇宙 z<0.1, 典型巡天 z~0.5-1.5, 宇宙正午 z~2-3,
亮类星体 z~6, 目前最深 z>10。
物理原理: z 由宇宙膨胀 (Hubble 流) + 光度演化共同决定; 红移本身不是距离,
距离需要宇宙学模型换算。
判定线索: 单一星系 z>10 需极高置信证据 (否则多为 photo-z 灾难性失败 —
尘埃中间红移星系可伪装成高 z 洁净星系); 负 z = 蓝移, 只可能出现在本星系群成员。""",
  source="Steed & Weinberg; SDSS downsizing; COSMOS", confidence="established"),
 dict(id="galaxy_stellar_mass_span", title="星系恒星质量跨数量级", category="reference_range",
  tags=["galaxy", "stellar_mass"], applies_to={"fields": ["stellar_mass"], "entities": ["galaxy"]},
  content="""星系恒星质量跨 7 个数量级: 矮星系 1e5-1e8 Msun, 银河系级 1e10-1e12 Msun,
团内巨椭圆 1e12-1e13 Msun。
物理原理: 恒星质量由 SED 拟合 × 质量光度比 (IMF 假设) 估计 — Salpeter vs
Kroupa IMF 相差 ~1.55 倍, 跨文献比较必须核对 IMF。
判定线索: 记录为 '恒星' 却给 1e11 Msun = 对象类型错误 (星系质量);
>1e13 Msun 的 '星系' 需怀疑团内暗物质质量混入或测量错误。""",
  source="Conroy 2013; Alonso-Herrero 2008", confidence="established"),
 dict(id="agn_luminosity_ladder", title="AGN 光度阶梯", category="reference_range",
  tags=["agn", "luminosity", "ladder"], applies_to={"fields": ["luminosity"], "entities": ["agn", "seyfert_galaxy"]},
  content="""AGN 光度跨越 5 个数量级, 由吸积率 (Eddington 比) 决定:
- 邻近低光度 Seyfert: X 波段 (2-10 keV) 1e40-1e43 erg/s
- 典型 Seyfert: 1e42-1e44 erg/s
- 类星体: L_bol 1e45-1e47 erg/s (接近 Eddington 吸积)
物理原理: L_Edd = 1.26e38 (M/Msun) erg/s 是辐射压平衡引力的上限 —
超过 Eddington 光度数倍的持续辐射需要非球对称吸积几何。
判定线索: 光度 >1e47 erg/s 的源若红移未知, 应先怀疑距离/光度单位混淆。""",
  source="Panessa XMM; Eddington 光度讲义 (JILA)", confidence="established"),
 dict(id="quasar_bolometric_anchor", title="类星体热光度锚点", category="reference_range",
  tags=["quasar", "bolometric"], applies_to={"fields": ["luminosity"], "entities": ["quasar", "blazar"]},
  content="""类星体是快速增长期的最亮 AGN, 热光度 log L_bol ~ 47 (1e47 erg/s) 量级,
约 1e5 倍银河系光度 — 其能量来自 SMBH 吸积盘引力势能释放。
物理原理: 峰值期吸积接近 Eddington (指数增长相), 光度函数 = Eddington 比分布
× 黑洞质量函数卷积; 高红移 (z>6) 的 1e47 erg/s 类星体要求 >1e9 Msun 黑洞
在宇宙第一十亿年内形成 (吸积物理的强约束)。
判定线索: L_bol 低于 1e43 erg/s 的 '类星体' 实为 Seyfert; 光度远超 1e47
需复核红移 (通常为 photo-z 低估)。""",
  source="Steed & Weinberg 2003; Shen 2009", confidence="established"),
 dict(id="agn_blackhole_mass_relation", title="AGN 黑洞质量锚点", category="reference_range",
  tags=["blackhole", "mbh", "sigma"], applies_to={"fields": ["stellar_mass"], "entities": ["agn", "quasar"]},
  content="""活动星系核的黑洞质量由 M_BH-σ 关系锚定: M_BH ≈ 1e8 (σ/200 km/s)^4 Msun,
散射 ~0.3-0.44 dex。物理机制: 动量驱动外流反馈 — 黑洞质量在反馈吹走核球气体
时被固定 (M ∝ σ^4); 或旋转坍缩模型。
典型值: 邻近 Seyfert 1e6-1e9 Msun, 亮类星体 ~1e9 Msun, 极端 >1e10。
判定线索: 记录的黑洞质量与宿主速度弥散明显不匹配 (差 >2 dex) 需复核;
>1e10 Msun 的 SMBH 极罕见 (仅 BCG/团内巨椭圆)。""",
  source="Tremaine 2002; Kormendy & Ho 2013", confidence="consensus"),
 dict(id="hii_region_physics", title="HII 区物理与电离平衡", category="reference_range",
  tags=["hii", "stromgren", "ionization"], applies_to={"fields": ["luminosity", "flux_density"], "entities": ["hii_region", "star_forming_region"]},
  content="""HII 区是被 O/B 星电离的氢区: 电离-复合平衡决定尺寸 —
Strömgren 半径 R_s = (3Q/4πα n^2)^(1/3), Q 为 Lyman 极限光子率, α 为 Case B
复合系数。电子温度 ~1e4 K, 典型密度 10-100 cm^-3 (致密丝可达 300+),
超致密 HII (UCHII) >1e4 cm^-3。
物理原理: 光子率固定时 n^2 R^3 = 常数 — '小又亮' 的 HII 区即高密度。
判定线索: HII 区尺寸与电离光度不匹配 (如 100 pc 级 HII 却只有毫级光度) 需复核。""",
  source="Kennicutt 2002; Kiel Strömgren 球讲义", confidence="established"),
 dict(id="snr_properties_range", title="超新星遗迹演化与谱指数", category="reference_range",
  tags=["snr", "remnant", "spectral_index"], applies_to={"fields": ["age", "flux_density"], "entities": ["supernova_remnant"]},
  content="""超新星遗迹经历自由膨胀 → Sedov 绝热 (R ∝ t^2/5) → 辐射冷却 → 消散,
寿命上限 ~1e5 yr。形态上分两类, 射电谱指数是核心判据 (S ∝ ν^-α):
- 壳层型 (SNR): 陡谱 α ~ -0.8 (Cas A), 激波同步加速
- 填充型 (plerion, 蟹状星云式): 平谱 α ~ +0.3, 脉冲星驱动
判定线索: 标注 SNR 却给 >1 Myr 年龄 = 与 HII 区混淆; 谱指数 +0.3 的
'壳层 SNR' 实为 plerion。""",
  source="Green 850μm 谱指数; NRAO 讲义; Katsuda 2012", confidence="established"),
 dict(id="brown_dwarf_boundaries", title="褐矮星质量边界", category="reference_range",
  tags=["brown_dwarf", "boundary", "fusion"], applies_to={"fields": ["effective_temperature", "stellar_mass"], "entities": ["brown_dwarf", "low_mass_star"]},
  content="""褐矮星是'失败的恒星': 核心点燃氘 (p+d→He3, 持续 4-50 Myr) 但无法稳定
氢燃烧。两个物理边界 (IAU 定义):
- 下限 13 M_jup: 氘燃烧所需质量
- 上限 73-80 M_jup (0.07-0.08 Msun): 氢燃烧最小质量
因持续冷却, 光谱型是温度与年龄的函数: L 型 (1300-2500 K) → T 型 (600-1300 K,
CH4 带) → Y 型 (<600 K, NH3 带)。
判定线索: 质量在 13-80 M_jup 之外却标褐矮星 = 与行星/极低质量恒星混淆;
锂测试 (60-65 M_jup 以上可烧锂) 用于证认。""",
  source="Wikipedia Brown dwarf; IAU 定义; 褐矮星综述", confidence="established"),
 dict(id="exoplanet_radius_gap", title="系外行星半径间隙", category="reference_range",
  tags=["exoplanet", "radius_gap"], applies_to={"fields": ["planet_radius", "planet_mass"], "entities": ["exoplanet"]},
  content="""Kepler 统计发现行星半径分布存在 ~2 R_earth 间隙: 超地球 (≤1.9 R⊕, 岩石)
与亚海王星 (≥2 R⊕, 挥发物包层) 被光致蒸发/核供能大气损失分开, 间隙位置
R ∝ P^-0.11 — 半径是行星大气保持历史的探针。
质量锚点: 1 M_jup = 317.8 M_earth, 1 R_jup = 11.2 R_earth。
判定线索: 半径 2-3 R⊕ 恰好落在间隙内的行星记录本身合理 (过渡态), 但质量
缺失时应标注不确定性; 热木星 P<10 天 (形成于数 AU 外后迁移而来)。""",
  source="CKS 样本; 2016A&A 589A 75M; TOI-1075b 研究", confidence="consensus"),
 dict(id="m31_galaxy_reference", title="M31 (仙女座) 参考参数", category="reference_range",
  tags=["m31", "andromeda", "local_group"], applies_to={"fields": ["distance", "metallicity", "stellar_mass"], "entities": ["galaxy"]},
  content="""M31 是本星系群最大旋涡星系, 常用作河外参考锚点:
- 距离 ~780 kpc (Cepheid/TRGB/SN Ia 多方法一致, 方法间差异 <10%)
- 恒星质量 ~1e11 Msun, 动力学质量 ~1.5e12 Msun (含暗物质晕)
- 金属丰度 [Fe/H] ~ -0.3 (盘), 旋臂富金属区近太阳值
- 与银河系相距 ~800 kpc, 接近速度 ~123 km/s (未来并合)
物理原理: 距离阶梯 (Cepheid PL → TRGB → SN Ia) 在此校准;
判定线索: 记录 M31 距离 7.8 kpc 或 78 Mpc = 单位/数量级混淆。""",
  source="McConnachie 2012; Local Group 综述; 距离阶梯文献", confidence="consensus"),
]

# ══════════════════════════════════════════════════════════
# astrophysical_models.yaml +12
# ══════════════════════════════════════════════════════════
ASTROPHYSICAL_MODELS = [
 dict(id="stellar_evolution_pathway", title="恒星结构与演化路径", category="physical_law",
  tags=["evolution", "stellar"], applies_to={"entities": ["star", "evolved_star"]},
  content="""恒星演化由质量决定终点: 主序 (核心氢燃烧) → 红巨星 (壳层氢) → 氦燃烧 →
AGB (热脉冲) → 行星状星云+白矮星 (<8 Msun) 或 超新星+中子星/黑洞 (>8 Msun)。
物理原理: 各阶段由核燃烧产能与引力收缩的平衡驱动; 简并压中断收缩后
触发热核爆发 (氦闪、热脉冲、超新星)。
判定线索: 记录的年龄与演化阶段矛盾 (如 1 Gyr 的红超巨星) 提示字段错位。""",
  source="恒星结构教科书; 演化路径综述", confidence="consensus"),
 dict(id="ms_lifetime_mass_relation", title="主序寿命-质量关系", category="empirical_relation",
  tags=["lifetime", "mass"], applies_to={"entities": ["main_sequence_star", "star"]},
  content="""主序寿命 τ ∝ M/L ∝ M^-2.5 (核燃料 ∝ 质量, 光度 ∝ M^3.5): 太阳 ~10 Gyr,
O 型星仅数百万年, M 矮星超宇宙年龄。
物理原理: 大质量星辐射压主导 → 光度陡增 → 燃料更快耗尽;
判定线索: 大质量星 (O/B) 记录 >1 Gyr 年龄 = 矛盾 (应已超新星);
年老星族中检测到大质量主序星 = 双星质量转移或并合产物 (蓝离散星)。""",
  source="质光关系教科书推论; UNLV 主序表", confidence="established"),
 dict(id="chandrasekhar_limit", title="Chandrasekhar 极限", category="physical_law",
  tags=["chandrasekhar", "degeneracy"], applies_to={"entities": ["white_dwarf", "supernova"]},
  content="""电子简并压支撑白矮星的极限质量 ~1.44 Msun (Chandrasekhar 1931)。
超过极限: 简并压不足以抵抗引力 → 塌缩 (中子星/黑洞) 或碳点燃热核爆炸 (SN Ia)。
物理原理: 简并压 ∝ ρ^(5/3) (非相对论) → ρ^(4/3) (相对论), 相对论简并压
无法稳定超过临界质量。
判定线索: 白矮星质量 >1.4 Msun 的记录必错 (除非是中子星误标);
SN Ia 峰值光度由 56Ni 产量定 — 超亮/超暗 Ia 偏离标准烛光需解释。""",
  source="Chandrasekhar 1931; SN Ia 物理综述", confidence="established"),
 dict(id="neutron_star_structure", title="中子星结构", category="physical_law",
  tags=["neutron_star", "tov"], applies_to={"entities": ["neutron_star", "pulsar"]},
  content="""中子星由中子简并压+强核力支撑: 半径 10-13 km, 密度 1e14-1e15 g/cm^3,
质量 1.1-2.5 Msun (实测最高 2.35, GW170817 约束 M_TOV ≤ 3.06)。
质量必须靠双星轨道测量 (Kepler 定律), 单独的光度无法定质量。
磁星表面磁场 1e14-1e15 G (超量子临界场 4.4e13 G), 能量来自磁场衰减。
判定线索: 质量 >3 Msun 的 '中子星' = 应为黑洞; 半径标成 10 km 的 '恒星'
记录几乎必为单位混淆 (km vs Rsun)。""",
  source="GW170817 约束; PSR J0348+0432 等; 中子星综述", confidence="consensus"),
 dict(id="agn_unified_model", title="AGN 统一模型", category="galactic_model",
  tags=["agn", "unified", "torus"], applies_to={"entities": ["agn", "seyfert_galaxy", "quasar", "blazar"]},
  content="""统一模型 (Antonucci & Miller 1985): 所有 AGN 由 SMBH + 吸积盘 + 尘埃 torus
构成, 观测类型 = 视线取向效应:
- 面向轴: Sy1/类星体 (宽线区可见)
- 侧视: Sy2 (torus 遮挡宽线区)
- 喷流正对: Blazar (相对论聚束)
基石证据: NGC 1068 偏振谱中隐藏的宽线; X 射线吸收柱 1e22-1e24 cm^-2。
判定线索: Sy1 与 Sy2 的 X 光度差异常被吸收修正掩盖 — 比较前必须做吸收修正;
射电响亮与否不是取向效应 (由喷流功率/黑洞自旋决定)。""",
  source="Antonucci 1993; Urry & Padovani 1995; Netzer", confidence="consensus"),
 dict(id="eddington_accretion", title="爱丁顿吸积与光度上限", category="physical_law",
  tags=["eddington", "accretion"], applies_to={"entities": ["agn", "quasar", "black_hole", "xray_binary"]},
  content="""爱丁顿光度 L_Edd = 4πGMm_p c/σ_T = 1.26e38 (M/Msun) erg/s 是辐射压平衡
引力的上限, 与距离无关 — 是第一性 sanity check 锚点:
- 由光度得黑洞质量下限 M ≥ 8e5 (L/1e44 erg/s) Msun
- 低光度 AGN Eddington 比 0.01-0.001 (ADAF 型吸积)
- 亮类星体接近 Eddington (λ ~ 0.45 实测上限)
判定线索: 持续光度 > L_Edd 数倍的记录需要非球对称吸积 (超 Eddington) 解释
或复核光度/质量; X 射线双星光度上限即 1.3e38 (M/Msun) erg/s。""",
  source="JILA Eddington 讲义; Trinity 模型; Alonso-Herrero 2008", confidence="established"),
 dict(id="galactic_chemical_evolution", title="星系化学演化", category="galactic_model",
  tags=["chemical", "metallicity"], applies_to={"fields": ["metallicity"], "entities": ["galaxy"]},
  content="""星系金属丰度随恒星形成历史累积: 恒星核合成产出金属, 超新星/星风回注 ISM。
两个丰度标尺不可混用: 星云氧标尺 12+log(O/H) (太阳 8.69) 与恒星铁标尺 [Fe/H];
[O/Fe] 在 [Fe/H]≈-1 处随 SN Ia 贡献而下降, 两标尺间不是常数偏移。
物理原理: 大质量星 (核塌缩 SN) 产 O/Mg, 白矮星 (SN Ia) 产 Fe — 丰度比是
恒星形成时标的探针。
判定线索: [Fe/H] 与 12+log(O/H) 混用 (数值差 ~8.7) 是常见单位错误;
[Fe/H] > +0.5 的星系记录需高置信证据。""",
  source="Asplund 2009; 化学演化综述; 氧丰度转换讨论", confidence="consensus"),
 dict(id="stromgren_sphere_model", title="Strömgren 球与 HII 区", category="galactic_model",
  tags=["stromgren", "hii"], applies_to={"entities": ["hii_region"]},
  content="""Strömgren 球模型: 电离源 (O/B 星) 周围电离-复合平衡形成电离区,
半径 R_s = (3Q/4πα n^2)^(1/3); 光子率固定时 n^2 R^3 = 常数。
α_B ≈ 2.4e-11 T^(-1/2) cm^3/s (Case B 复合, 弱温度依赖)。
物理原理: 电离区边界 = 复合率追上电离率之处 (Strömgren 1939)。
判定线索: '大而暗' 的 HII 区 (R 大但光度低) 说明密度极低 (n^2R^3 守恒),
'小而亮' 说明高密度 (UCHII) — 尺寸-密度反比是物理必然而非矛盾。""",
  source="Strömgren 1939; Kiel 讲义; Kennicutt 2002", confidence="established"),
 dict(id="snr_sedov_expansion", title="SNR Sedov 膨胀演化", category="physical_law",
  tags=["sedov", "snr"], applies_to={"entities": ["supernova_remnant"]},
  content="""超新星遗迹演化四阶段: 自由膨胀 (抛射物惯性) → Sedov 绝热 (R ∝ t^2/5,
激波扫入 ISM 质量主导) → 辐射冷却 (壳层形成) → 消散 (~1e5 yr)。
物理原理: Sedov 解 = 点爆炸在均匀介质中的自相似解, 激波压缩比 4:1,
激波后温度 ~1e7 K (X 射线热辐射)。
判定线索: 年轻 SNR (年龄 <1e3 yr) 应仍有高膨胀速度 (数千 km/s);
老年 SNR 壳层明显、中心无填充 — plerion (脉冲星驱动) 例外。""",
  source="Sedov 1959; SNR 演化讲义 (Oregon); Katsuda 2012", confidence="established"),
 dict(id="hierarchical_galaxy_formation", title="星系等级形成 (ΛCDM)", category="cosmological_model",
  tags=["lcdm", "hierarchy"], applies_to={"entities": ["galaxy", "galaxy_cluster"]},
  content="""ΛCDM 冷暗物质等级并合模型: 小结构先形成, 大结构 (星系团/超团) 由并合
组装; 大质量星系形成较晚 (downsizing 相反面是高质量 SMBH 先完成增长)。
物理原理: 暗物质晕引力坍缩 → 重子气体冷却落入 → 恒星形成;
并合触发恒星形成 (潮汐压缩汇聚气体)。
判定线索: 高红移 (z>3) 记录为 '成熟星系团' (富 X 射线 ICM) 与等级形成
预期矛盾, 需复核红移; 团质量与速度弥散应满足维里关系。""",
  source="ΛCDM 综述; Trinity; Boettner 2025", confidence="consensus"),
 dict(id="imf_initial_mass_function", title="初始质量函数 IMF", category="empirical_relation",
  tags=["imf", "salpeter"], applies_to={"entities": ["star"]},
  content="""恒星形成时的初始质量分布: Salpeter 幂律 ξ(M) ∝ M^-2.35 (0.1-100 Msun),
小质量星数量主导 → 星族平均质量 ~0.3 Msun。
物理原理: 恒星质量谱由湍流分子云的碎裂+吸积竞争决定 (尚无完整理论,
IMF 是经验律)。
应用含义: 由光度推恒星/星系质量必须假设 IMF — Salpeter vs Kroupa/Chabrier
相差 ~1.55 倍, 这是质量估计最大的系统不确定源。
判定线索: 跨文献比较恒星/星系质量必须核对 IMF 假设, 否则 1.5 倍差异
是正常系统差而非数据错误。""",
  source="Salpeter 1955; Kroupa 2001; Conroy 2013", confidence="consensus"),
 dict(id="ism_three_phase_model", title="ISM 三相模型", category="galactic_model",
  tags=["ism", "phase"], applies_to={"entities": ["ism_object"]},
  content="""McKee-Ostriker 三相模型: 超新星注入能量动态调节 ISM 压力平衡 (nT≈常数):
- 冷中性相 CNM: ~100 K, 10-50 cm^-3, 体积 1-4% (但持一半质量)
- 暖相 WNM/WIM: ~8000 K, 0.1-1 cm^-3 (约一半质量)
- 热电离相 HIM: ~5e5 K, 3e-3 cm^-3 (占大部分体积)
物理原理: 各相由加热 (UV/激波) 与冷却 (线辐射) 平衡决定;
相间通过蒸发/凝结交换物质。
判定线索: 温度+密度配对可唯一归属相态 — '冷而稀薄' 或 '热而稠密' 的
ISM 记录违反压力平衡, 需复核单位。""",
  source="McKee & Ostriker 1977; Begelman & McKee; ISM 讲义", confidence="consensus"),
]

# ══════════════════════════════════════════════════════════
# physical_laws.yaml +8
# ══════════════════════════════════════════════════════════
PHYSICAL_LAWS = [
 dict(id="blackbody_radiation_law", title="黑体辐射定律", category="physical_law",
  tags=["blackbody", "stefan"], applies_to={"fields": ["effective_temperature", "luminosity"], "entities": ["star"]},
  content="""斯特藩-玻尔兹曼定律: L = 4πR^2 σ T^4 — 恒星/尘埃的连续谱辐射基础;
维恩位移: λ_max ∝ 1/T (热源越热峰值越短)。
物理原理: 黑体辐射是热平衡辐射场, 光度=表面积×单位面积辐射功率。
应用: 由 (Teff, 半径) 或 (Teff, 光度) 推第三者; SED 拟合定 Teff。
判定线索: Teff 与颜色矛盾 (如 5000 K 却标为蓝源) = 消光未修正或字段错位;
恒星 SED 明显偏离黑体 (红外超) 提示尘埃盘/星风包层。""",
  source="恒星物理教科书; OSU HR 图讲义", confidence="established"),
 dict(id="mass_luminosity_relation", title="主序质光关系", category="empirical_relation",
  tags=["mass_luminosity"], applies_to={"entities": ["main_sequence_star"]},
  content="""主序质光关系 L ∝ M^3.5 (约 0.5-10 Msun 区间近似): 大质量端辐射压主导
趋向 L ∝ M^3, 低质量端对流主导斜率变平。
物理原理: 流体静力学平衡 + 辐射扩散近似 (光度 ∝ 内部温度梯度 × 半径)。
应用: 由质量估光度/寿命 (τ ∝ M^-2.5), 或反之;
判定线索: 主序星质量-光度组合明显偏离关系 (>1 dex) = 双星混合、
非主序成员, 或单位错误。""",
  source="质光关系教科书; UNLV 主序表", confidence="established"),
 dict(id="eddington_luminosity", title="爱丁顿光度界限", category="physical_law",
  tags=["eddington"], applies_to={"entities": ["star", "black_hole", "agn"]},
  content="""爱丁顿光度 L_Edd = 4πGMm_p c/σ_T ≈ 1.26e38 (M/Msun) erg/s: 辐射压
(电子 Thomson 散射) 平衡引力的上限, 与距离无关。
物理原理: 超过 L_Edd 时辐射压驱动外流, 吸积被截断 (对球对称吸积)。
应用: 恒星/黑洞质量的下限锚点; AGN 与 X 射线双星的 sanity check;
判定线索: L > L_Edd 数倍的持续辐射需要超 Eddington 几何解释 (盘风、
喷流) 或复核光度/质量 — 这是数据质量核查的第一性工具。""",
  source="JILA 讲义; Eddington 1916 原始推导", confidence="established"),
 dict(id="hubble_flow_law", title="Hubble 流与距离-红移", category="empirical_relation",
  tags=["hubble", "redshift"], applies_to={"fields": ["redshift", "distance"], "entities": ["galaxy"]},
  content="""Hubble-Lemaître 定律: v = H0 d (H0 ≈ 67-73 km/s/Mpc); z << 1 时 cz ≈ H0 d。
物理原理: 宇宙膨胀使星系退行, 红移是尺度因子之比 z = a(t_obs)/a(t_emit) - 1;
z > 0.1 后线性近似失效, 需宇宙学模型 (ΛCDM) 换算距离。
判定线索: z 与距离明显矛盾 (如 z=0.5 却标 10 Mpc) = 单位/换算错误;
同一对象的多个红移源差异 >3-5% 属测量系统差, 更大差异提示双星/并合/透镜。""",
  source="Planck 2020; 宇宙学教科书", confidence="established"),
 dict(id="doppler_redshift_law", title="多普勒红移与视向速度", category="empirical_relation",
  tags=["doppler", "radial_velocity"], applies_to={"fields": ["radial_velocity"], "entities": ["star", "galaxy"]},
  content="""多普勒效应: 谱线位移 Δλ/λ = v/c (非相对论) — 视向速度测量的基础。
物理原理: 光源沿视线运动压缩/拉伸波长; 热运动与湍流展宽限制精度。
应用: 恒星/星系 RV 测量 (精度 ~0.1-10 km/s 视谱分辨率);
双星轨道 (SB1 只给 m sin^3 i, SB2 可得两星质量 — 倾角需食/天体测量)。
判定线索: 负 RV (蓝移) 只可能来自本星系群成员 (宇宙学红移恒为正);
RV 与星系 z 矛盾 = 星系内运动 vs 宇宙学红移混淆。""",
  source="多普勒效应讲义; RV 测量方法文献", confidence="established"),
 dict(id="virial_mass_theorem", title="维里定理与动力学质量", category="physical_law",
  tags=["virial", "dynamics"], applies_to={"entities": ["galaxy", "galaxy_cluster", "galaxy_group"]},
  content="""维里定理: 束缚系统的 2⟨T⟩ + ⟨U⟩ = 0 → 动力学质量 M ≈ σ^2 R / G
(σ 速度弥散, R 特征半径)。
物理原理: 平衡系统的动能与势能之比固定 (各向同性无碰撞气体)。
应用: 星系团/椭圆星系质量估计 — 团质量 ~1e14-1e15 Msun 中 ~84% 是暗物质,
~13% 热 ICM, 星系本身仅 ~1%。
判定线索: 动力学质量与光度质量差异 >10 倍 = 暗物质主导 (正常) 或
非平衡态 (并合中, 维里定理失效); 团 X 光度与温度应满足 L_X ∝ T^3。""",
  source="维里定理讲义; 星系团质量综述 (Peterson)", confidence="established"),
 dict(id="radius_temp_luminosity", title="恒星半径-温度-光度关系", category="physical_law",
  tags=["radius", "teff", "luminosity"], applies_to={"fields": ["stellar_radius", "effective_temperature", "luminosity"], "entities": ["star"]},
  content="""L = 4πR^2 σ T^4 联立 Teff/半径/光度: 任取两者可推第三者 — 恒星参数的
一致性校验基础 (HR 图的坐标即 T 与 L)。
物理原理: 黑体辐射 + 几何 (光度=表面积×表面辐射通量)。
判定线索: 三者矛盾 (如 1 Rsun + 5000 K 却标 1e5 Lsun) = 单位混用
(常见: Rsun↔km、Lsun↔erg/s、Teff↔K 混淆);
红超巨星: 3000-4500 K + 200-1500 Rsun + 1e4-1e6 Lsun 的组合应自洽。""",
  source="恒星物理教科书; HR 图讲义", confidence="established"),
 dict(id="schwarzschild_radius", title="Schwarzschild 半径", category="physical_law",
  tags=["blackhole", "schwarzschild"], applies_to={"entities": ["black_hole"]},
  content="""Schwarzschild 半径 r_s = 2GM/c^2 ≈ 2.95 (M/Msun) km — 事件视界尺度。
物理原理: 牛顿逃逸速度 v = (2GM/r)^(1/2) 达光速的半径 (广义相对论精确解)。
尺度: 恒星质量 BH (5-100 Msun) → 15-300 km (与中子星同尺度);
SMBH (1e6-1e10 Msun) → 0.02-200 AU。
判定线索: 黑洞'密度' ∝ 1/M^2 — 大质量黑洞是低密度物体 (可低于水),
这是常见直觉误区; 记录的黑洞质量与半径组合不满足 r_s 关系 = 单位错误。""",
  source="JILA 黑洞讲义; Schwarzschild 1916", confidence="established"),
]

# ══════════════════════════════════════════════════════════
# measurement_theory.yaml +10
# ══════════════════════════════════════════════════════════
MEASUREMENT_THEORY = [
 dict(id="mk_spectral_classification", title="MK 光谱分类原理", category="measurement_principle",
  tags=["mk", "classification"], applies_to={"fields": ["spectral_type"], "entities": ["star"]},
  content="""MK 分类 = 温度序 (OBAFGKM, 谱线相对强度) × 光度级 (I-V, 线宽/强度)。
物理原理: 温度决定电离态与分子平衡; 光度级由表面重力 (线展宽) 判别 —
同光谱型巨星与矮星温度相同但重力不同。
判定线索: SpT 与 Teff 矛盾 (如标 M 型却给 20000 K) = 字段错位;
金属丰度低会使金属线变弱、误判为更热型; 双星 (SB2) 模糊线型。
测量方法: 目视比较标准星谱 + 自动分类 (MKCLASS/机器学习)。""",
  source="Gray 2005; MK 分类原始文献", confidence="established"),
 dict(id="agn_emission_line_diagnostics", title="AGN 谱线诊断 (BPT 图)", category="measurement_principle",
  tags=["bpt", "agn", "diagnostics"], applies_to={"entities": ["agn", "seyfert_galaxy", "liner", "emission_line_galaxy"]},
  content="""BPT 图 ([OIII]/Hβ vs [NII]/Hα) 区分电离机制: Kewley 2001 最大星暴线上
需要 ≥30-50% AGN/激波贡献; Kauffmann 2003 经验线与 Kewley 线之间为 composite;
[SII]/Hα、[OI]/Hα 分离 Seyfert 与 LINER。
物理原理: 恒星形成 (O/B 星电离) 与 AGN (幂律电离) 产生不同的线强度比 —
AGN 硬光子产生更高的 [OIII]/Hβ 与 [OI]/Hα。
关键误区: LINER 不是单一物理类 — 低光度 AGN / post-AGB 老年恒星 / 激波
三机制共存; 宽 Hα + 硬 X 射线指向 AGN 型。""",
  source="Kewley 2001; Kauffmann 2003; 两类 LINER (0902.1023)", confidence="consensus"),
 dict(id="sersic_profile_fitting", title="Sérsic 剖面拟合", category="measurement_principle",
  tags=["sersic", "profile"], applies_to={"entities": ["galaxy"]},
  content="""Sérsic 剖面 I(r) = I_e exp[-b_n ((r/r_e)^(1/n) - 1)]: n=1 指数盘 (旋涡),
n=4 de Vaucouleurs (椭圆), 中间值过渡形态。
物理原理: 表面亮度分布反映恒星轨道分布与松弛程度;
测量方法: 二维剖面拟合 (GALFIT 等), r_e 有效半径, n 形态参数。
判定线索: 单分量拟合残差大的星系 = 核球+盘双组分 (n 值需分别拟合);
LSB 星系 μ0(B) ≥ 23 mag/arcsec^2 是操作定义 (表面亮度受限巡天的物理根源)。""",
  source="Sérsic 1963; GALFIT 文档; UTK 星系讲义", confidence="established"),
 dict(id="iras_farir_photometry", title="IRAS 远红外测光口径", category="measurement_principle",
  tags=["iras", "farir", "photometry"], applies_to={"entities": ["far_infrared_source", "infrared_source"]},
  content="""IRAS 60/100 μm 测光需注意: Cirrus 污染 (银河系红外 Cirrus 背景)、
色修正 (不同 SED 假设)、SES 误差列 (噪声)、q_* 质量标志 (质量等级,
q=2 表示可靠, 低质量需标注)。
物理原理: 远红外 = 尘埃再辐射 (消光免疫的恒星形成示踪);
IRAS 色-色图 (log(S60/S25) > 0.57 星暴 / 0-0.57 AGN) 是 AGN-恒星形成
最佳单色判据。
判定线索: q_* 标志低的通量不可直接用于定量分析;
FIR 光度 >1e13 Lsun 且无红移 = 需复核 (ULIRG 极罕见)。""",
  source="IRAS Explanatory Supplement 1988; Helou; de Grijp", confidence="consensus"),
 dict(id="extragalactic_distance_ladder", title="河外距离阶梯", category="measurement_principle",
  tags=["distance", "ladder"], applies_to={"fields": ["distance"], "entities": ["galaxy"]},
  content="""河外距离由阶梯逐级校准: 几何视差 (Gaia) → Cepheid PL 关系 → TRGB →
SN Ia (Phillips 关系) → Tully-Fisher; 每级误差累积增大。
物理原理: 各级标准烛光/尺子在不同距离域可校准; 交叉验证约束系统差。
判定线索: 同一星系的距离记录方法不同时, 差异 <10% 属正常 (M31 ~780 kpc
Cepheid/TRGB/SN Ia 一致); 孤立方法异常值需复核;
距离与红移应满足 Hubble 流 (z=0.001 对应 ~4.3 Mpc)。""",
  source="距离阶梯综述; McConnachie 2012; Benedict 2002", confidence="established"),
 dict(id="radial_velocity_measurement", title="径向速度测量", category="measurement_principle",
  tags=["radial_velocity", "doppler"], applies_to={"fields": ["radial_velocity"], "entities": ["star", "galaxy"]},
  content="""RV 由谱线多普勒位移测量: Δλ/λ = v/c; 精度受谱分辨率与信噪比限制
(典型 0.1-10 km/s, 高精度 spectrograph 可达 m/s 级)。
误差来源: 波长定标漂移、恒星活动 (星斑伪信号)、大气视向速度、
双星轨道相位 (同一源不同历元 RV 不同)。
物理原理: 谱线位置 vs 实验室波长; 天基 (Gaia RVS) 与地基联合。
判定线索: 同一恒星的 RV 记录差异 >50 km/s = 双星或测量错误;
星系 RV 与红移矛盾 = 本动速度 vs 宇宙学红移混淆。""",
  source="RV 测量方法文献; HARPS/ESPRESSO 综述", confidence="established"),
 dict(id="2mass_jhk_photometry", title="2MASS JHK 测光列语义", category="measurement_principle",
  tags=["2mass", "jhk", "photometry"], applies_to={"entities": ["near_infrared_source", "galaxy"]},
  content="""2MASS XSC 列语义 (VII/233/xsc): J 1.25μm / H 1.65μm / K 2.16μm (Vega 零点);
J.K20e = 20 mag/arcsec^2 等照度椭圆口径星等; Jconc 集中度、Jb/a 轴比、
Jpa 位置角、Jmu 表面亮度、Jfe/Jext 标志位。
物理原理: 近红外对尘埃不敏感, 示踪恒星质量主导成分;
判定线索: K20e 是等照度口径 — 与 PSF 口径星等不可直接比较;
Jfe 标志位非零 = 星等质量存疑;
2MASS 零点与 Vega 一致, 跨目录同波段 (同为 2MASS) 可直接比较。""",
  source="Cutri 2003 2MASS Explanatory Supplement; VizieR VII/233", confidence="consensus"),
 dict(id="metallicity_measurement", title="金属丰度测量与双标尺", category="measurement_principle",
  tags=["metallicity", "feh"], applies_to={"fields": ["metallicity"], "entities": ["star", "galaxy"]},
  content="""金属丰度两个标尺: 恒星 [Fe/H] (谱线等效宽度/曲线增长分析) 与
星云 12+log(O/H) (氧禁线比, 电子温度法); 太阳 12+log(O/H)=8.69,
换算 Z/Zsun = 10^(A-8.69)。
物理原理: Fe 由 SN Ia 主导, O/Mg 由核塌缩 SN 主导 — [O/Fe] 是恒星形成
时标探针, 两标尺间不是常数偏移。
判定线索: [Fe/H] 与 12+log(O/H) 数值混用 (差 ~8.7) 是常见单位错误;
[Fe/H] < -3 的恒星记录需高置信证据 (极贫金属星极罕见)。""",
  source="Asplund 2009; 氧丰度转换讨论; 谱线分析文献", confidence="consensus"),
 dict(id="galaxy_kinematics_measurement", title="星系动力学测量", category="measurement_principle",
  tags=["kinematics", "rotation"], applies_to={"entities": ["galaxy"]},
  content="""星系动力学: 旋转曲线 (HI 21cm / Hα 长缝) 与速度弥散 σ;
logD25 等光度直径、logR25 轴比、i 倾角用于几何修正。
物理原理: 旋转速度 + 半径 → 动力学质量 (维里/盘模型);
平坦旋转曲线 = 暗物质晕主导。
判定线索: 旋转速度与形态矛盾 (矮星系 300 km/s 不可能) = 单位错误
(km/s vs km); 倾角未知时 v_rot 是下界 (投影效应);
团成员速度弥散 ~800-1000 km/s 是团级特征 (群 ~150 km/s)。""",
  source="星系动力学讲义; HI 21cm 观测文献", confidence="established"),
 dict(id="photometric_redshift_galaxy", title="星系测光红移", category="measurement_principle",
  tags=["photoz", "redshift"], applies_to={"fields": ["redshift"], "entities": ["galaxy"]},
  content="""photo-z 由宽带/窄带测光 SED 模板拟合 (χ²) 或机器学习估计;
典型精度: 宽带 0.03-0.05 (σ(Δz/(1+z))), 多/窄带 0.007-0.02;
spec-z 精度 1e-3-1e-4 (基准方法)。
误差机制: 颜色-红移简并 (尘埃中间红移星系可伪装高 z 洁净星系 →
灾难性失败)、模板库不完备、测光定标误差; 现代方法输出整条 PDF。
判定线索: photo-z 与 spec-z 差异 >0.1 (1+z) 需标记;
z > 4 的 photo-z 误差 >0.2 是常态 — 高红移结论必须有 spec-z 或
多波段独立证据; 两步法 (先 photo-z 再固定 z 拟合) 会低估不确定度。""",
  source="Ilbert 2009 COSMOS; EDisCS; PAU; Conroy 2013", confidence="consensus"),
]

# ══════════════════════════════════════════════════════════
# methodology.yaml +8
# ══════════════════════════════════════════════════════════
METHODOLOGY = [
 dict(id="simbad_otype_classification_rule", title="Simbad 对象类型分类规则", category="methodology",
  tags=["simbad", "otype", "taxonomy"], applies_to={"entities": ["star", "galaxy", "agn", "radio_source", "xray_source"]},
  content="""Simbad 对象类型分类 (otypes.list) 的规则:
- 层级分类 (最多 4 级, 如 Star→Variable→Pulsating→Cepheid)
- 物理本质优先于波长: 只有本质未知时才用波长类 (Radio/IR/UV/X/gamma)
- 一个天体可携带多个 otype (主类型 + 附加波长类)
- CANDI 列 = 候选类型 (需确认)
判定意义: 波长类标签 (Rad/IR/X 等) 是'未知本质'的占位符而非物理类型 —
记录里只有 'IR source' 而无物理类型时, 应视为待证认对象;
'err'/'mul'/'?' 分别表示伪影/混合/未知。""",
  source="Simbad guide chF; Oberto 2018; IVOA Object Types Vocabulary", confidence="consensus"),
 dict(id="extragalactic_catalog_crossmatch", title="河外多目录交叉证认", category="methodology",
  tags=["crossmatch", "catalog"], applies_to={"entities": ["galaxy"]},
  content="""河外目录交叉证认需按位置精度分级:
- IRAS (60/100 μm): 位置误差 30-120″ (远红外 PSF 大)
- PGC/HYPERLEDA: 光学位置 ~1-3″
- 2MASS XSC: 近红外位置 3-10″
- NED/ANames/IDType: 别名与目录身份解析
物理原理: 不同波段的源可能对应不同物理成分 (IRAS 尘埃、2MASS 恒星质量、
光学星族), 位置重合 ≠ 同一对象 (投影污染)。
判定线索: 高精度 (2MASS) 与低精度 (IRAS) 匹配半径必须按较差分级,
盲目用单一半径会造成误匹配 (IRAS 源错配到相邻 2MASS 源)。""",
  source="VizieR 目录文档; 交叉证认方法文献; Contini 1998", confidence="consensus"),
 dict(id="sample_selection_bias", title="样本选择效应", category="methodology",
  tags=["selection", "bias"], applies_to={"entities": ["galaxy", "agn", "quasar"]},
  content="""巡天选择效应决定样本物理构成:
- IRAS 60 μm 选择 → 尘埃恒星形成星系偏置 (冷色星暴优先)
- 2MASS K 波段 → 红/质量星系偏置
- 可见光 → 星族主导
- WISE W1-W2 ≥ 0.8 → AGN (但要求 MIR 中 AGN 占优, 宿主 >50% 时失效)
- 蓝/UV 超 (Markarian) → 主要命中星暴核 (82% 星暴 vs 9% Seyfert)
物理原理: 各波段示踪不同物理成分 (尘埃/恒星质量/电离);
判定线索: 跨目录比较统计性质时必须说明选择函数;
表面亮度受限巡天 (LSB 星系) 与星等受限巡天的完备性完全不同。""",
  source="Helou; Stern 2012; Markarian 星系光谱分类", confidence="consensus"),
 dict(id="photometric_system_conversion", title="测光系统转换", category="method_comparison",
  tags=["photometry", "vega", "ab"], applies_to={"fields": ["apparent_magnitude"], "entities": ["star", "galaxy"]},
  content="""测光零点系统: Vega (2MASS/BVRI, 恒星为 0) vs AB (SDSS/JWST, 常数通量);
同一源两系统差值随颜色变化 (Vega-AB: u~0.9, g~0.1, z~-0.5 mag 量级)。
物理原理: 零点定义不同 (Vega 星 = 0 mag vs 1e-23 erg/s/Hz 常数)。
换算: mag ↔ Jy 需波段有效频率。
判定线索: 跨系统比较星等必须先转换 — G (Gaia) 与 V 差 0.1-0.5 mag 随
颜色变化, 直接相减会误判变光; 2MASS JHK 同为 Vega 可直接比较;
光变曲线跨系统拼接是变星研究的常见错误源。""",
  source="Jordi 2010; 2MASS Explanatory Supplement; SDSS 文档", confidence="consensus"),
 dict(id="multi_source_redshift_compare", title="多来源红移比较", category="method_comparison",
  tags=["redshift", "compare"], applies_to={"fields": ["redshift"], "entities": ["galaxy"]},
  content="""同一星系多个红移来源的比较规则:
- spec-z 精度 1e-3-1e-4 (基准); photo-z 3-6%
- 目录间 spec-z 差异 <0.001 属测量系统差
- photo-z vs spec-z 差异 >0.1 (1+z) = 灾难性失败 (颜色简并)
物理原理: 不同测量方法误差机制独立 (谱线位移 vs SED 模板);
判定线索: 汇总多来源红移时用中位数/加权平均并报告离散度;
单一 photo-z 高红移结论必须标注不确定性;
z > 4 时 photo-z 与 spec-z 系统性偏差是常态而非数据错误。""",
  source="COSMOS/EDisCS photo-z 研究; PAU 窄带", confidence="consensus"),
 dict(id="m31_distance_comparison", title="M31 距离多方法比较", category="methodology",
  tags=["m31", "distance"], applies_to={"fields": ["distance"], "entities": ["galaxy"]},
  content="""M31 距离 ~780 kpc 是河外距离阶梯的校准锚点:
- Cepheid PL 关系 (Leavitt 律): 周期-光度关系的物理基础是 P ∝ ρ^(-1/2)
  脉动周期-密度关系 + 质光关系
- TRGB: 红巨星分支拐点的 I 带绝对星等近似恒定
- SN Ia: Phillips 关系 (峰值光度-下降速率)
方法间差异 <10% 属正常 (系统误差层级不同);
判定线索: 单方法孤立异常 (如 700 vs 900 kpc) 需复核而非取平均 —
通常指向 Cepheid 金属丰度修正或 TRGB 污染 (AGB 星混入);
距离 7.8 kpc 或 78 Mpc 的记录 = 单位/数量级错误。""",
  source="McConnachie 2012; Ferrarese 1996; Benedict 2002", confidence="consensus"),
 dict(id="agn_host_galaxy_interpretation", title="AGN 宿主星系解读", category="methodology",
  tags=["agn", "host"], applies_to={"entities": ["agn", "quasar"]},
  content="""AGN 宿主星系性质解读:
- 典型 X 选 AGN (z~0.5-1.4) 宿主恒星质量 7.8e10-1.2e11 Msun (大质量星系)
- 高红移类星体宿主 (3-5)e11 Msun — 高红移宿主偏亮是选择效应
- M_BH 与宿主恒星质量比 ~0.5% (经典核球/椭圆适用)
物理原理: AGN 与宿主共同演化 (M_BH-σ 反馈); 光度选择偏向亮宿主;
判定线索: 宿主质量与 M_BH 明显不匹配 (差 >2 dex) = 伪核球
(pseudobulge) 或并合中星系 (M_BH-σ 不适用);
M_BH/M_bulge 0.1% 是旧值 (样本污染), 现代值 0.5%。""",
  source="Alonso-Herrero 2008; Kormendy & Ho 2013", confidence="consensus"),
 dict(id="catalog_documentation_check", title="目录文档核对", category="best_practice",
  tags=["catalog", "documentation"], applies_to={"entities": ["galaxy", "star"]},
  content="""使用 VizieR/目录数据前的核对清单:
- 核对列描述/readme: 单位、口径 (等照度 vs PSF)、质量标志列 (q_*)
- waveband 与 research_methodology 字段: 确认波段与测量方法
- 版本口径: 同一目录不同发布 (IRAS v2.1 vs PSC) 数值可能不同
- 质量标志: q_* = 2 可靠, 低质量标志需标注或排除
物理原理: 目录列语义 (尤其口径与质量标志) 决定数值可比性;
判定线索: 跨目录比较前必须确认口径一致 (K20e vs K_psf 不可混用);
红外源 (IRAS) 位置误差大, 与高精度目录匹配需分级半径。""",
  source="VizieR 文档; IRAS Explanatory Supplement; 2MASS XSC", confidence="consensus"),
]

FILES = [
    ("reference_ranges.yaml", REFERENCE_RANGES),
    ("astrophysical_models.yaml", ASTROPHYSICAL_MODELS),
    ("physical_laws.yaml", PHYSICAL_LAWS),
    ("measurement_theory.yaml", MEASUREMENT_THEORY),
    ("methodology.yaml", METHODOLOGY),
]


def main():
    total = 0
    for fname, entries in FILES:
        path = f"{BASE}/{fname}"
        with io.open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        existing = [e.get("id") for e in doc.get("entries", [])]
        added = [e for e in entries if e.get("id") not in existing]
        if not added:
            print(f"{fname}: 全部已存在, 跳过")
            continue
        doc.setdefault("entries", []).extend(added)
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120)
        print(f"{fname}: +{len(added)} 条 (原有 {len(existing)})")
        total += len(added)
    print(f"共新增 {total} 条")


if __name__ == "__main__":
    main()
