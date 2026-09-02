# -*- coding: utf-8 -*-
"""Append new methodology entries to astrophysics/methodology.yaml (knowledge base expansion)."""
import yaml
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# L-22 fix: 相对定位 (同 append_knowledge.py), 换机器不再 FileNotFoundError
PATH = Path(__file__).parent.parent / "data" / "insight_knowledge" / "astrophysics" / "methodology.yaml"

with open(PATH, encoding="utf-8") as f:
    data = yaml.safe_load(f)

existing_ids = {e["id"] for e in data["entries"]}
print("existing ids:", sorted(existing_ids))

new_entries = [
    {
        "id": "bayesian_inference_astro",
        "title": "贝叶斯推断在天文中的应用",
        "category": "methodology",
        "tags": ["bayesian", "statistics", "prior", "posterior", "inference"],
        "applies_to": {
            "fields": ["redshift", "stellar_mass", "luminosity", "effective_temperature"],
        },
        "content": """贝叶斯推断流程: 后验 = 似然 x 先验 / 证据
posterior = P(theta|D) = L(D|theta) x pi(theta) / P(D)

1. 似然: 观测误差通常取高斯, L ~ exp(-chi2/2); 误差棒必须真实, 误差被低估会伪造后验显著性
2. 先验选择规则:
   - 位置参数 (红移、星等): 均匀先验 (需物理范围截断)
   - 尺度参数 (光度、质量等跨数量级): 对数均匀 (Jeffreys 先验, pi ~ 1/theta)
   - 有界物理参数: 检查后验是否堆积在边界 (提示先验截断过紧或模型错误)
3. 输出: 后验中位数/众数 + 68% 最高后验密度区间 (HPDI)

判定线索:
- 样本少/信噪比低时后验由先验主导, 必须报告先验形式
- 均匀先验在数据弱时低估不确定度 (置信区间过窄)
- 两来源参数不一致用贝叶斯因子 B 判断: B > 10 强证据, B < 0.1 强反证, 不能只看差几个 sigma
- 报告参数应给出完整后验分布或至少分位数, 而非仅最佳值""",
        "source": "Trotta 2008, Contemporary Physics; Foreman-Mackey et al. 2013, PASP",
        "confidence": "consensus",
    },
    {
        "id": "least_squares_fitting",
        "title": "最小二乘与卡方拟合",
        "category": "methodology",
        "tags": ["chi_square", "fitting", "least_squares", "statistics"],
        "applies_to": {
            "fields": ["redshift", "stellar_mass", "luminosity", "radial_velocity", "orbital_period"],
        },
        "content": """最小二乘拟合: 最小化加权残差平方和
chi2 = sum_i (y_i - f(x_i))^2 / sigma_i^2

1. 权重: 每点按 1/sigma_i^2 加权; 误差未知时先等权拟合, 用残差标准差估计误差后重拟合 (迭代)
2. 约化卡方: chi2_nu = chi2 / (N - k), N 为点数, k 为自由参数数
   - chi2_nu ~ 1: 拟合良好, 误差估计正确
   - chi2_nu >> 1: 模型不适用或误差被低估 (需查系统误差/遗漏项)
   - chi2_nu << 1: 误差被高估或过拟合
3. 参数置信区间: 1 参数 68% 区间对应 delta chi2 = 1 (2 参数时 delta chi2 = 2.30), 不是 delta chi2_nu = 1

判定线索:
- 残差应随机分布; 残差呈系统性弯曲 = 模型形式错误
- 简单把误差缩放至 chi2_nu = 1 来导出参数误差是错误做法 (Andrae 2010)
- 数据清洗中误差棒系统性偏小会伪造高显著结果, 先查误差来源再下结论""",
        "source": "Andrae, Schulze-Hartung & Melchior 2010, arXiv:1012.3754; Bevington & Robinson, Data Reduction and Error Analysis",
        "confidence": "consensus",
    },
    {
        "id": "cross_match_angular",
        "title": "角距匹配与误差椭圆",
        "category": "methodology",
        "tags": ["cross_match", "angular_separation", "error_ellipse", "astrometry", "matching_radius"],
        "applies_to": {
            "fields": ["right_ascension", "declination", "parallax", "proper_motion_ra", "proper_motion_dec"],
        },
        "content": """角距匹配 (cross-match) 几何:
大圆距离 sep = arccos(sin d1 sin d2 + cos d1 cos d2 cos(a1 - a2)); 小角距近似 sep ~ sqrt((dRA cos d)^2 + (dDec)^2)

1. 匹配半径参考: 高精度 (Gaia/Hipparcos) 1-5 arcsec; 中精度 (2MASS/SDSS) 3-10 arcsec; 低精度 (IRAS) 30-120 arcsec
   - 半径过小漏匹配; 过大误匹配 (邻近源污染)
2. 误差椭圆: 位置误差为椭圆 (长半轴 a, 短半轴 b, 位置角 PA); 两源综合误差 sigma = sqrt(sig1^2 + sig2^2) 沿分离方向投影
   - 95% 置信误差转 1 sigma: 乘 0.4085 (即除以 sqrt(2 ln 20))
3. 概率匹配: 归一化分离 sep/sigma > 3 判为不同源; 多候选用似然比/贝叶斯方法 (NWAY), 结合亮度与颜色排除

物理原理: 高斯位置误差卷积后, 归一化分离服从瑞利型分布, 阈值由两源误差共同决定

判定线索: 匹配前核对历元 (J2000 vs B1950) 与参考系 (ICRS vs FK5); 自行大的源需外推至相同历元; 已知系统误差 (如 0.2 arcsec) 平方相加""",
        "source": "Pineau et al. 2011/2017, A&A; CDS xMatch 文档; Budavari & Szalay 2008, ApJ",
        "confidence": "consensus",
    },
    {
        "id": "spectral_classification_mk",
        "title": "MK 光谱分类体系 (应用与校验)",
        "category": "methodology",
        "tags": ["spectral_type", "mk_classification", "stellar", "taxonomy", "effective_temperature"],
        "applies_to": {
            "fields": ["spectral_type", "effective_temperature", "surface_gravity"],
            "entities": ["star"],
        },
        "content": """MK 光谱分类应用与校验 (测量原理见 measurement_theory 的 mk_spectral_classification 条目):
格式: 光谱型[数字小数] + 光度级, 如 G2V, K0III, M5.5Ia
温度序 OBAFGKM (O 最热), 每型 0-9 细分; 光度级 I (超巨星) II (亮巨星) III (巨星) IV (亚巨星) V (主序) VI/sd (亚矮星)

典型主序有效温度 (K): O 28000-50000, B 10000-28000, A 7500-10000, F 6000-7500, G 5000-6000 (G2 ~ 5800), K 3500-5000, M 2500-3500

判定线索:
- SpT 与 Teff 矛盾 (标 M 型却给 20000 K) = 字段错位或解析错误
- 光度级对应 log g (dex): V ~ 4.0-4.5, III ~ 2.5-3.0, I ~ 0-1; 与 log g 不符需复核
- 同一源跨目录 SpT 差 1-2 子型属正常 (目视分类主观性); 差 > 3 子型或跨光度级 = 数据冲突
- 低金属丰度使金属线变弱, 易误判为更热型; 双星 (SB2) 线型模糊
- 格式校验: 正则 [OBAFGKM][0-9](\\.5)?(I|II|III|IV|V|VI|sd)? 筛出解析错误; 白矮星 D 型、褐矮星 L/T/Y 型超出主序列""",
        "source": "Morgan, Keenan & Kellman 1943; Gray & Corbally 2009, Stellar Spectral Classification; Pecaut & Mamajek 2013, ApJS",
        "confidence": "consensus",
        "ranges": {"effective_temperature": {"lo": 2500, "hi": 50000, "unit": "K"}},
    },
    {
        "id": "stellar_mass_function_imf",
        "title": "恒星初始质量函数 (IMF)",
        "category": "methodology",
        "tags": ["imf", "mass_function", "salpeter", "kroupa", "chabrier", "stellar_mass"],
        "applies_to": {
            "fields": ["stellar_mass", "luminosity"],
            "entities": ["star", "galaxy"],
        },
        "content": """恒星初始质量函数 IMF: 恒星形成时刻的质量分布, 对数形式 xi(log M) = dN/dlog M

1. Salpeter (1955): 单幂律 dN/dM ~ M^-2.35 (对数斜率 -1.35), 适用 0.4-10 Msun
2. Kroupa (2001): 分段幂律, 低质量端变平: 0.08-0.5 Msun 斜率 -1.3; 0.5-1 Msun 斜率 -2.3; > 1 Msun 恢复 Salpeter 斜率
3. Chabrier (2003): < 1 Msun 用对数正态分布 (峰值 ~0.2 Msun), > 1 Msun 幂律 -2.35

物理原理: 质量分布由湍流与反馈的统计决定, 大体普适但低质量端偏离单幂律

判定线索:
- 低质量端受亮度限制探测不全, 统计斜率必须做完整度/选择效应改正
- Salpeter 与 Kroupa 归一化的质量-光比相差约 1.5 倍, 两者不可混用
- 高速度弥散星系 (中心 sigma > 200 km/s) 倾向 bottom-heavy IMF (低质量占比更高)
- 由观测质量函数反推 IMF 需扣除恒星演化损失与未分辨双星效应""",
        "source": "Salpeter 1955, ApJ; Kroupa 2001, MNRAS; Chabrier 2003, PASP; La Barbera et al. 2013, MNRAS",
        "confidence": "consensus",
        "ranges": {"stellar_mass": {"lo": 0.08, "hi": 120, "unit": "Msun"}},
    },
    {
        "id": "source_detection_deblend",
        "title": "源检测与去混叠 (deblending)",
        "category": "methodology",
        "tags": ["source_detection", "deblending", "sextractor", "photometry", "segmentation"],
        "applies_to": {
            "fields": ["flux_density", "apparent_magnitude", "right_ascension", "declination"],
            "entities": ["star", "galaxy"],
        },
        "content": """源检测与去混叠流程 (SExtractor 范式):
1. 背景估计: 网格化去除天空面形 (mesh 尺寸影响亮源外延与拥挤场表现)
2. 阈值检测: 像素需高于 DETECT_THRESH (通常 1.5-3.5 sigma, 相对局部背景噪声) 且连通像素 >= DETECT_MINAREA (通常 4-10)
3. 去混叠: 多阈值树分裂 — DEBLEND_NTHRESH (层数, 默认 32); DEBLEND_MINCONT (最小对比度, 默认 0.005, 拥挤场降至 0.00005 可找回亮源翅膀中的弱源)
4. 测量: 等照度测光 vs Kron 自动孔径 (MAG_AUTO); 拥挤场用 PSF 拟合分离

判定线索:
- 阈值过低 -> 噪声假源; 过高 -> 丢弱源
- 拥挤场 (星系团、银道面) 未去混叠的测光系统性偏亮 (混合光)
- 分割图双峰/非对称 = 去混叠失败信号
- 点/延展判别: 星象尖锐度 CLASS_STAR < 0.5 为延展源; 混用不同孔径测光跨目录比较会引入系统差""",
        "source": "Bertin & Arnouts 1996, A&AS; SExtractor v2.x 文档",
        "confidence": "consensus",
    },
    {
        "id": "lomb_scargle_periodogram",
        "title": "Lomb-Scargle 周期图",
        "category": "methodology",
        "tags": ["periodogram", "period_search", "time_series", "lomb_scargle", "variability"],
        "applies_to": {
            "fields": ["orbital_period", "apparent_magnitude", "flux_density"],
            "entities": ["star", "galaxy", "agn"],
        },
        "content": """Lomb-Scargle 周期图: 非均匀采样时间序列周期搜索的标准方法, 等价于对正弦 y = A sin(2 pi f t) + B cos(2 pi f t) 做最小二乘拟合; 传统 FFT 在缺测/非等间隔数据上不可用

1. 功率谱峰值对应候选周期; 峰值高度本身不是显著性
2. 假警报概率 FAP: 噪声产生同高功率的几率
   - FAP < 0.01 (或 0.001) 才认为显著, 需考虑独立频率数修正
   - 计算: Baluev (2008) 解析公式 或 蒙特卡洛置换检验 (bootstrap)
3. 窗口函数: 采样模式产生混叠峰 — 地面观测 1 天混叠 (f_alias = f_true +- n/day), 月相 ~1/27 天; 分析前先检查窗口函数

判定线索:
- 周期接近观测基线长度或采样间隔倍数的峰不可信
- 谐波峰 (P/2, 2P) 常见, 需确认基频
- 报告必须给出 FAP 而非裸功率; 不同 FAP 方法结果差异大时取保守值
- 周期值跨目录比较: 核对采样基线是否覆盖周期 (基线过短测不到长周期)""",
        "source": "Lomb 1976, Ap&SS; Scargle 1982, ApJ; VanderPlas 2018, ApJS; Baluev 2008, MNRAS",
        "confidence": "consensus",
    },
    {
        "id": "extinction_correction_method",
        "title": "消光改正方法",
        "category": "methodology",
        "tags": ["extinction", "reddening", "color_excess", "E(B-V)", "rv"],
        "applies_to": {
            "fields": ["extinction", "apparent_magnitude", "absolute_magnitude"],
            "entities": ["star", "galaxy"],
        },
        "content": """消光改正流程:
1. 色余法: E(B-V) = (B-V)_obs - (B-V)_0; 本征色 (B-V)_0 由光谱型校准表给出
2. 消光换算: A_V = R_V x E(B-V); 弥散星际介质 R_V = 3.1 +- 0.2 (CCM 消光律), 视线方向实测 2.5-4.7 (大 R_V = 尘埃颗粒偏大)
3. 多波段: A_lambda 由消光律 (CCM/Fitzpatrick) 内插; 近红外 A_lambda ~ lambda^-1.6~-2.6, 对消光不敏感
4. 标准星法: 用光谱型已知的 OB 星测多波段色余, 拟合得到 R_V 与 A_V

判定线索:
- E(B-V) < 0 = 本征色估计错误或非恒星污染 (双星/发射线星)
- 银河系前景尘埃图 (SFD/3D 消光图) 与观测色余矛盾时, 用近红外交叉验证 (红外对消光不敏感)
- 远红外/射电波段无需光学消光改正
- 改正后颜色应落回恒星/星系本征色序列; 改正过量会使颜色异常过蓝""",
        "source": "Cardelli, Clayton & Mathis 1989, ApJ; Rieke & Lebofsky 1985, ApJ; Fitzpatrick 1999, PASP; Schlafly et al. 2016, ApJ",
        "confidence": "consensus",
    },
    {
        "id": "mcmc_sampling_astro",
        "title": "马尔可夫链蒙特卡洛 (MCMC) 参数采样",
        "category": "methodology",
        "tags": ["mcmc", "markov_chain", "monte_carlo", "sampling", "emcee", "posterior"],
        "applies_to": {
            "fields": ["redshift", "stellar_mass", "luminosity", "orbital_period", "effective_temperature"],
        },
        "content": """MCMC: 从后验分布采样的标准方法, 贝叶斯参数估计的默认工具 (常用 affine-invariant 集成采样器 emcee)

1. 配置: walkers 通常 30-100, 每链数万步量级; 初始位置散布整个先验范围
2. 收敛判据 (结果报告必须包含):
   - burn-in: 丢弃未收敛初始段 (通常前 10-30%)
   - 自相关时间 tau: 有效样本数 N_eff = N / tau, N_eff > 100 才可靠 (粗略)
   - 多链混合检验: Gelman-Rubin R_hat < 1.1
3. 输出: 后验中位数 + 16%/84% 分位或 HPDI; 参数高度相关时只报边缘分布会误导

判定线索:
- 结果缺少链长度与收敛诊断 = 可靠性存疑
- 后验峰堆积在参数边界 = 先验或模型问题
- 后验与最小二乘最佳值相差 > 3 sigma 且非对称 = 非高斯后验, 均值不可靠
- 与贝叶斯推断条目配套使用: 先验选择决定采样空间""",
        "source": "Foreman-Mackey et al. 2013, PASP (emcee); Hogg & Foreman-Mackey 2018, ApJS",
        "confidence": "consensus",
    },
    {
        "id": "pca_dimensionality_reduction",
        "title": "数据降维与可视化 (PCA)",
        "category": "methodology",
        "tags": ["pca", "dimensionality_reduction", "visualization", "spectra", "machine_learning"],
        "applies_to": {
            "fields": ["apparent_magnitude", "flux_density", "effective_temperature", "surface_gravity"],
            "entities": ["star", "galaxy"],
        },
        "content": """数据降维方法 (光谱/多波段测光高维观测):
1. 主成分分析 (PCA): 找方差最大正交方向
   - 光谱数据前 3-5 个主成分通常解释 > 90% 方差
   - 输入必须标准化 (均值 0, 方差 1), 否则亮端主导; 不能含 NaN (需先插补或迭代加权 PCA)
   - 用途: 光谱自动分类、SED 模板族构建、参数空间可视化
2. 非线性方法 t-SNE/UMAP: 适合可视化聚类结构; 超参数 (perplexity/n_neighbors) 影响结果, 需多组参数验证稳健性

判定线索:
- 降维后聚类边界清晰且物理量 (红移/温度/质量) 沿流形连续 = 结构真实
- 孤立离群簇先查数据错误 (单位/零点混用、坐标错位), 再考虑新物理
- 数据质量校验应用: 同一源多来源参数经 PCA 投影应邻近, 偏离远 = 冲突或错误
- 强相关维度直接作距离度量会放大冗余影响, 需先降维再聚类""",
        "source": "Jolliffe 2002, Principal Component Analysis; McInnes et al. 2018 (UMAP); VanderPlas 2018, ApJS",
        "confidence": "consensus",
    },
]

# L-23 fix: 幂等去重改真实过滤 (同 append_knowledge.py:550) — assert 在 -O 下被剥离,
# 重复执行会产生重复 id
added = [e for e in new_entries if e["id"] not in existing_ids]
for e in added:
    assert e["category"] in ("methodology", "best_practice", "method_comparison"), e["category"]
data["entries"].extend(added)

with open(PATH, "w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=200, default_flow_style=False)

print("total entries:", len(data["entries"]))
print("new ids:", [e["id"] for e in added])
