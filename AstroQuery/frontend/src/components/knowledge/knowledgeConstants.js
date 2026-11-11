/* AstroQuery Knowledge Base Constants & Initial Fallback Data
 * STRICT: NO emojis. Clean Monoline typography.
 */

export const KNOWLEDGE_CATEGORIES = [
  { id: 'all', label: '全部理论', color: 'var(--content-fg-secondary, #94a3b8)' },
  { id: 'physical_laws', label: '物理定律', color: '#3b82f6', altNames: ['物理定律', 'physical_law', 'physical_laws', 'law', 'physics'] },
  { id: 'equations_of_state_and_models', label: '状态方程与模型', color: '#8b5cf6', altNames: ['状态方程与模型', 'equations_of_state_and_models', 'equation_of_state', 'model', 'astrophysical_models', 'galactic_model'] },
  { id: 'measurement_and_extinction', label: '测量与消光', color: '#f59e0b', altNames: ['测量与消光', 'measurement_and_extinction', 'extinction', 'measurement', 'reddening'] },
  { id: 'observational_methodology', label: '观测方法学', color: '#10b981', altNames: ['观测方法学', 'observational_methodology', 'methodology', 'observation_method', 'telescope', 'astrometry'] },
  { id: 'reference_limits', label: '参考界限', color: '#f43f5e', altNames: ['参考界限', 'reference_limits', 'limit', 'boundary', 'criterion'] },
  { id: 'concepts_and_catalogs', label: '概念星表', color: '#06b6d4', altNames: ['概念星表', 'concepts_and_catalogs', 'concept', 'catalog', 'concepts', 'catalogs', 'profile'] },
  { id: 'user_private', label: '用户私有', color: '#eab308', altNames: ['用户私有', 'user_private', 'user', 'custom', 'private'] },
]

export function getCustomCategoryColor(catName) {
  if (!catName) return '#14b8a6'
  let hash = 0
  for (let i = 0; i < catName.length; i++) {
    hash = catName.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = Math.abs(hash % 360)
  return `hsl(${hue}, 72%, 46%)`
}

export function normalizeCategory(cat, dynamicList = []) {
  if (!cat) return 'physical_laws'
  const clean = String(cat).trim()
  const lower = clean.toLowerCase()
  for (const item of KNOWLEDGE_CATEGORIES) {
    if (item.id === 'all') continue
    if (item.id === lower || item.label.toLowerCase() === lower || item.altNames?.some(alt => alt.toLowerCase() === lower)) {
      return item.id
    }
  }
  for (const item of dynamicList) {
    if (item.id === clean || item.label === clean) {
      return item.id
    }
  }
  return clean
}

export function getCategoryInfo(categoryId, dynamicList = []) {
  const norm = normalizeCategory(categoryId, dynamicList)
  const builtIn = KNOWLEDGE_CATEGORIES.find(c => c.id === norm)
  if (builtIn) return builtIn
  const custom = dynamicList.find(c => c.id === norm || c.label === norm)
  if (custom) return { ...custom, color: custom.color || getCustomCategoryColor(custom.label || custom.id) }
  return {
    id: norm,
    label: norm,
    color: getCustomCategoryColor(norm),
    is_custom: true,
  }
}

export function isValidFormula(str) {
  if (!str || typeof str !== 'string') return false
  const trimmed = str.trim()
  if (!trimmed || trimmed.length > 150) return false
  if (trimmed.includes('\n')) return false
  // Contains common math symbols
  const hasMath = /[=\\_\^∝≈~<>\+\-\*\/]/.test(trimmed)
  if (!hasMath) return false
  // If Chinese characters count > 6, it is descriptive text not a standalone formula
  const chineseCount = (trimmed.match(/[\u4e00-\u9fa5]/g) || []).length
  if (chineseCount > 6) return false
  return true
}

// 天体物理常见性质、目录列标识与拓扑枢纽 ID 的统一学术中文对照表
export const PROPERTY_TRANSLATIONS = {
  prop_luminosity: '光度 (Luminosity)',
  prop_teff: '有效温度 (Teff)',
  prop_mass: '天体质量 (Mass)',
  prop_radius: '天体半径 (Radius)',
  prop_distance: '天体距离 (Distance)',
  prop_extinction: '星际消光 (Extinction)',
  prop_reddening: '色余红化 (Reddening)',
  prop_parallax: '天体测量视差 (Parallax)',
  prop_period: '轨道周期 (Period)',
  prop_metallicity: '金属丰度 (Metallicity)',
  prop_surface_gravity: '表面重力 (Surface Gravity)',
  prop_density: '物质密度 (Density)',
  prop_dispersion: '色散量 (Dispersion Measure)',
  prop_radial_velocity: '视向速度 (Radial Velocity)',
  stellar_radius: '恒星半径',
  effective_temperature: '有效温度',
  'effective temperature': '有效温度',
  teff: '有效温度 (Teff)',
  teff_gspphot: 'Gaia GSP-Phot 有效温度',
  temperature: '温度',
  luminosity: '光度',
  bolometric_luminosity: '热光度',
  l_bol: '热光度 (L_bol)',
  lum_bol: '热光度 (L_bol)',
  mass: '天体质量',
  stellar_mass: '恒星质量',
  pl_mass: '行星质量',
  pl_radius: '行星半径',
  radius: '天体半径',
  eff_radius: '等效半径',
  kron_radius: 'Kron 半径',
  einstein_radius: '爱因斯坦半径',
  distance: '天体距离',
  distance_gspphot: 'Gaia GSP-Phot 距离',
  distance_modulus: '距离模数',
  dist_modulus: '距离模数',
  luminosity_distance: '光度距离',
  angular_diameter_distance: '角直径距离',
  heliocentric_distance: '日心距离',
  redshift: '红移 (z)',
  z: '红移 (z)',
  photo_z: '测光红移',
  photometric_redshift: '测光红移',
  spec_z: '光谱红移',
  dispersion_measure: '色散量 (DM)',
  'dispersion measure': '色散量 (DM)',
  dm: '色散量 (DM)',
  metallicity: '金属丰度 [Fe/H]',
  fe_h: '金属丰度 [Fe/H]',
  'fe/h': '金属丰度 [Fe/H]',
  feh: '金属丰度 [Fe/H]',
  mh_gspphot: 'Gaia GSP-Phot 金属丰度',
  alpha_abundance: 'α 元素丰度',
  alpha_fe: '[α/Fe] 丰度比',
  chemical_abundance: '化学元素丰度',
  abundance: '元素丰度',
  oxygen_abundance: '氧元素丰度',
  surface_gravity: '表面重力 (log g)',
  'surface gravity': '表面重力 (log g)',
  logg: '表面重力 (log g)',
  log_g: '表面重力 (log g)',
  logg_gspphot: 'Gaia GSP-Phot 表面重力',
  density: '物质密度',
  central_density: '中心密度',
  orbital_period: '轨道周期',
  'orbital period': '轨道周期',
  period: '周期',
  spin_period: '自转周期',
  variability_period: '光变周期',
  radial_velocity: '视向速度',
  'radial velocity': '视向速度',
  rv: '视向速度',
  v_helio: '日心视向速度',
  velocity_dispersion: '速度弥散',
  extinction: '星际消光 (A_v)',
  a_v: '视觉消光 (A_V)',
  av: '视觉消光 (A_V)',
  ag_gspphot: 'Gaia G 波段消光',
  azero_gspphot: '550nm 单色消光 (A_0)',
  galactic_extinction: '银河系前景消光',
  interstellar_extinction: '星际消光',
  color_excess: '色余红化 E(B-V)',
  'color excess': '色余红化 E(B-V)',
  reddening: '星际红化',
  'e(b-v)': '色余 E(B-V)',
  e_bv: '色余 E(B-V)',
  ebv: '色余 E(B-V)',
  parallax: '天体测量视差',
  plx: '天体测量视差',
  gaia_parallax: 'Gaia 视差',
  trigonometric_parallax: '三角视差',
  flux_density: '流量密度',
  radio_flux_density: '射电流量密度',
  radio_flux: '射电流量',
  fnu: '频率流量密度 (F_ν)',
  f_lambda: '波长流量密度 (F_λ)',
  abs_mag: '绝对星等',
  absolute_magnitude: '绝对星等',
  apparent_magnitude: '视星等',
  bolometric_magnitude: '热星等',
  m_bol: '热星等 (M_bol)',
  surface_brightness: '表面亮度',
  age: '天体年龄',
  proper_motion: '自行',
  pmra: '赤经自行 (μ_α*)',
  pmdec: '赤纬自行 (μ_δ)',
  coordinates: '天球坐标',
  equatorial_coordinates: '赤道坐标',
  galactic_coordinates: '银道坐标',
  ra: '赤经 (RA)',
  dec: '赤纬 (Dec)',
  sky_position: '天区位置',
  spectral_type: '光谱型',
  sp_type: '光谱型',
  spectral_class: '光谱分类',
  spectral_index: '谱指数',
  radio_spectral_index: '射电谱指数',
  magnetic_field_strength: '磁场强度',
  mass_loss_rate: '质量损失率',
  star_formation_rate: '恒星形成率 (SFR)',
  morphology: '形态学分类',
  morph_type: '星系形态型',
  sersic_index: 'Sérsic 轮廓指数',
  equivalent_width: '等值宽度',
  ruwe: 'Gaia 天体测量拟合度 (RUWE)',
  vsini: '自转投影速度 (v sin i)',
  rotational_velocity: '自转速度',
  rotation_velocity: '自转速度',
  accretion_rate: '吸积率',
  eddington_ratio: '爱丁顿比',
  object_class: '天体分类',
  designation: '天体编号',
  angular_size: '角尺度',
  angular_separation: '角距',
  snr: '信噪比 (SNR)',
}

export function translateProperty(rawProp) {
  if (!rawProp) return ''
  const raw = String(rawProp).trim()
  const lower = raw.toLowerCase()
  if (PROPERTY_TRANSLATIONS[lower]) return PROPERTY_TRANSLATIONS[lower]
  const spaced = lower.replace(/_/g, ' ')
  if (PROPERTY_TRANSLATIONS[spaced]) return PROPERTY_TRANSLATIONS[spaced]
  // Clean band-magnitude or band-flux identifiers like w1_mag / j_mag / sdss_r_mag
  const magMatch = lower.match(/^(?:sdss_|ukidss_|wise_|2mass_|twomass_)?([ugrizjhkw1234]+)_mag(?:nitude)?$/)
  if (magMatch) return `${magMatch[1].toUpperCase()} 波段星等`
  const fluxMatch = lower.match(/^([a-z0-9]+)_flux(?:_density)?$/)
  if (fluxMatch) return `${fluxMatch[1].toUpperCase()} 波段流量`
  return raw
}

export function translateEdgeLabel(label) {
  if (!label) return '相互约束'
  const s = String(label).trim()
  if (s.startsWith('关联')) {
    const rest = s.slice(2).trim()
    if (!rest) return s
    const translated = translateProperty(rest)
    return `关联${translated}`
  }
  return s
}

export const INITIAL_KNOWLEDGE_ENTRIES = [
  {
    id: 'stefan_boltzmann_law',
    title: '斯特藩-玻尔兹曼辐射定律 (Stefan-Boltzmann Law)',
    category: 'physical_laws',
    formula: 'L = 4\\pi R^2 \\sigma T_{\\text{eff}}^4',
    description: '黑体总辐射能流与绝对温度的四次方成正比。在恒星物理学中，该定律建立了恒星光度 L、有效温度 Teff 与光球半径 R 之间的核心关系式。',
    conditions: ['局域热动平衡 (LTE) 辐射场', '各向同性近似球对称黑体表面'],
    parameters: [
      { name: 'T_eff', symbol: 'T_{\\text{eff}}', range: '[2000, 60000]', unit: 'K', desc: '恒星有效温度' },
      { name: 'R', symbol: 'R', range: '[0.01, 2000]', unit: 'R_\\odot', desc: '恒星半径' },
      { name: 'sigma', symbol: '\\sigma', range: '5.670374 \\times 10^{-8}', unit: 'W/(m^2 K^4)', desc: '斯特藩-玻尔兹曼常数' },
    ],
    properties: ['Luminosity', 'Effective Temperature', 'Radius', 'Temperature'],
    tags: ['光度', '有效温度', '恒星半径', '黑体辐射', '基本物理定律'],
    sources: 'Stefan (1879); Boltzmann (1884); Carroll & Ostlie (2017) Intro to Modern Astrophysics',
    user_preference: 'preferred',
    preferred: true,
    is_user: false,
  },
  {
    id: 'eddington_luminosity_limit',
    title: '爱丁顿光度极限 (Eddington Luminosity Limit)',
    category: 'reference_limits',
    formula: 'L_{\\text{Edd}} = \\frac{4\\pi G M c}{\\kappa_{\\text{es}}} \\approx 1.26 \\times 10^{38} \\left(\\frac{M}{M_\\odot}\\right) \\text{erg/s}',
    description: '向外辐射光压与向内恒星自引力处于流体静力学平衡时的理论上限光度。当吸积光度超过爱丁顿极限时光压将吹散外层吸积物质。',
    conditions: ['稳态球对称纯气体吸积', '汤姆逊电子散射自由截面占主导 (\\kappa_{\\text{es}} \\approx 0.4 \\text{ cm}^2/\\text{g})'],
    parameters: [
      { name: 'M', symbol: 'M', range: '[0.1, 10^{10}]', unit: 'M_\\odot', desc: '天体质量 (包含中子星与超大质量黑洞)' },
      { name: 'kappa_es', symbol: '\\kappa_{\\text{es}}', range: '0.40', unit: 'cm^2/g', desc: '电子散射不透明度' },
    ],
    properties: ['Luminosity', 'Mass', 'Accretion Rate', 'Eddington Ratio'],
    tags: ['爱丁顿极限', '辐射压', '吸积流', '黑洞质量', '临界界限'],
    sources: 'Eddington (1916); Rybicki & Lightman (1979) Radiative Processes in Astrophysics',
    user_preference: 'preferred',
    preferred: true,
    is_user: false,
  },
  {
    id: 'cardelli_ccm89_extinction',
    title: 'CCM89 紫外-光学-近红外消光曲线模型 (Cardelli-Clayton-Mathis)',
    category: 'measurement_and_extinction',
    formula: '\\frac{A(\\lambda)}{A(V)} = a(x) + \\frac{b(x)}{R_V}, \\quad x = \\lambda^{-1} \\; [\\mu\\text{m}^{-1}]',
    description: '参数化星际尘埃消光律，通过全波段总消光与色余比值 RV = AV / E(B-V) 统一描述从光学到紫外、红外波段的连续色散消光行为。',
    conditions: ['弥散与密集星际介质 (0.3 \\le \\lambda^{-1} \\le 10 \\; \\mu\\text{m}^{-1})'],
    parameters: [
      { name: 'R_V', symbol: 'R_V', range: '[2.1, 5.5]', unit: '无量纲', desc: '总消光比 (银盘弥散介质典型标准值 3.1)' },
    ],
    properties: ['Extinction', 'Color Excess', 'Magnitude', 'Apparent Magnitude', 'Absolute Magnitude'],
    tags: ['星际消光', '色余', '红化修正', 'CCM89', '光度测量'],
    sources: 'Cardelli, Clayton, & Mathis (1989), ApJ, 345, 245; Fitzpatrick (1999)',
    user_preference: 'neutral',
    preferred: false,
    is_user: false,
  },
  {
    id: 'lane_emden_equation',
    title: '莱恩-埃姆登自引力多方球状态方程 (Lane-Emden Equation)',
    category: 'equations_of_state_and_models',
    formula: '\\frac{1}{\\xi^2} \\frac{d}{d\\xi} \\left( \\xi^2 \\frac{d\\theta}{d\\xi} \\right) + \\theta^n = 0',
    description: '基于自引力流体静力学平衡与多方状态方程 P = K \\rho^{1+1/n} 推导出的无量纲恒星径向结构方程，是恒星内部结构与主序前恒星演化的基石模型。',
    conditions: ['静态球对称自引力平衡', '正压多方流体'],
    parameters: [
      { name: 'n', symbol: 'n', range: '[0, 5]', unit: '无量纲', desc: '多方指数 (n=1.5 简并电子气/完全对流; n=3 相对论简并/标准辐射模型)' },
    ],
    properties: ['Density', 'Central Pressure', 'Radius', 'Central Density'],
    tags: ['多方球', '恒星结构', '流体静力平衡', '状态方程', '理论模型'],
    sources: 'Lane (1870); Emden (1907); Chandrasekhar (1939) Stellar Structure',
    user_preference: 'neutral',
    preferred: false,
    is_user: false,
  },
  {
    id: 'gaia_astrometric_parallax',
    title: '盖亚空间天体测量几何视差测距法 (Gaia Geometric Parallax)',
    category: 'observational_methodology',
    formula: 'd \\; [\\text{pc}] = \\frac{1000}{\\varpi \\; [\\text{mas}]}, \\quad \\mu_\\alpha^* = \\dot{\\alpha}\\cos\\delta',
    description: '高精度空间天体测量绝对三角几何视差转换为物理天体距离的基准法则，结合贝叶斯拟合纠正视差负数或低信噪比天体的非对称空间先验分布。',
    conditions: ['高质量天体测量解: \\varpi / \\sigma_\\varpi > 5 且 RUWE < 1.4', '空间零点修正 (zero-point bias corrected)'],
    parameters: [
      { name: 'parallax', symbol: '\\varpi', range: '(0, 1000]', unit: 'mas', desc: '天体测量视差' },
      { name: 'RUWE', symbol: '\\text{RUWE}', range: '< 1.4', unit: '无量纲', desc: '重正化单位权重误差' },
    ],
    properties: ['Distance', 'Parallax', 'Proper Motion', 'Coordinates'],
    tags: ['空间天体测量', '视差测距', '盖亚星表', 'Gaia DR3', '观测方法'],
    sources: 'Gaia Collaboration, Brown et al. (2021) A&A 649, A1; Bailer-Jones et al. (2021) AJ 161, 147',
    user_preference: 'preferred',
    preferred: true,
    is_user: false,
  },
  {
    id: 'chandrasekhar_mass_limit',
    title: '钱德拉塞卡质量极限 (Chandrasekhar Mass Limit)',
    category: 'reference_limits',
    formula: 'M_{\\text{Ch}} \\approx \\frac{\\omega_3^0 \\sqrt{3\\pi}}{2} \\left( \\frac{\\hbar c}{G} \\right)^{3/2} \\frac{1}{(\\mu_e m_u)^2} \\approx 1.44 \\; M_\\odot',
    description: '极端相对论简并电子气抵抗自引力坍缩的最大白矮星质量极限。当碳氧白矮星吸积突破钱德拉塞卡极限时，将引发热核失控爆炸形成Ia型超新星。',
    conditions: ['极端相对论非理想费米气体', '平均分子量 \\mu_e \\approx 2.0 (碳氧简并核)'],
    parameters: [
      { name: 'M_Ch', symbol: 'M_{\\text{Ch}}', range: '\\approx 1.44', unit: 'M_\\odot', desc: '电子简并压极限质量' },
    ],
    properties: ['Mass', 'Radius', 'Density', 'Supernova Progenitor'],
    tags: ['致密天体', '白矮星', 'Ia型超新星', '费米简并压', '极限质量'],
    sources: 'Chandrasekhar (1931), ApJ, 74, 81; Shapiro & Teukolsky (1983)',
    user_preference: 'preferred',
    preferred: true,
    is_user: false,
  },
  {
    id: 'wien_displacement_law',
    title: '维恩位移定律 (Wien\'s Displacement Law)',
    category: 'physical_laws',
    formula: '\\lambda_{\\max} T_{\\text{eff}} = b \\approx 2.89777 \\times 10^{-3} \\; \\text{m}\\cdot\\text{K}',
    description: '黑体连续光谱辐射出度峰值波长与绝对热力学温度成反比。天文学中用于根据高精度分光光谱连续谱峰位直接估算天体光球温度。',
    conditions: ['纯黑体谱能量分布 (波长空间单峰)'],
    parameters: [
      { name: 'b', symbol: 'b', range: '2.89777 \\times 10^{-3}', unit: 'm K', desc: '维恩位移常数' },
      { name: 'T_eff', symbol: 'T_{\\text{eff}}', range: '[1000, 100000]', unit: 'K', desc: '辐射体温度' },
    ],
    properties: ['Effective Temperature', 'Peak Wavelength', 'Color Index', 'Temperature'],
    tags: ['黑体连续谱', '有效温度', '维恩定律', '光谱测温'],
    sources: 'Wien (1893); Rybicki & Lightman (1979)',
    user_preference: 'neutral',
    preferred: false,
    is_user: false,
  },
  {
    id: 'simbad_ned_concept_catalog',
    title: 'SIMBAD / NED 跨尺度概念与天体分类星表体系',
    category: 'concepts_and_catalogs',
    formula: '\\text{Obj} \\in \\mathcal{C}_{\\text{class}} \\iff \\text{SpecType} \\cup \\text{Morphology} \\cup \\text{Identifiers}',
    description: '汇聚银河系内外恒星、致密天体、星系及活动星系核（AGN）的多色交叉比对和层级分类本体结构。',
    conditions: ['国际天文学联合会 (IAU) 命名规范推荐'],
    parameters: [
      { name: 'N_objects', symbol: 'N_{\\text{obj}}', range: '> 1.3 \\times 10^7', unit: '个', desc: '已编目交叉标识天体总量' },
    ],
    properties: ['Spectral Type', 'Object Class', 'Coordinates', 'Designation'],
    tags: ['天体分类', '星表交叉比对', '概念体系', 'SIMBAD', 'NED'],
    sources: 'Wenger et al. (2000), A&AS 143, 9; Helou et al. (1991)',
    user_preference: 'neutral',
    preferred: false,
    is_user: false,
  },
  {
    id: 'user_be_star_disk_emission',
    title: 'Be星星周粘滞解吸积盘 Halpha 辐射模型 (用户派生)',
    category: 'user_private',
    formula: '\\Sigma(r) = \\Sigma_0 \\left(\\frac{r}{R_*}\\right)^{-n}, \\quad W_{\\text{H}\\alpha} \\propto \\int_{R_*}^{R_{\\text{out}}} \\rho(r)^2 r \\, dr',
    description: '针对高速自转早期型 Be 星去吸积盘建立的经验粘滞盘辐射模型，用于从 Halpha 准双峰发射线轮廓反演盘质量倾角。',
    conditions: ['超临界近开普勒自转 (v/v_crit > 0.8)', '等温气体盘假设'],
    parameters: [
      { name: 'n', symbol: 'n', range: '[2.0, 3.5]', unit: '无量纲', desc: '表面密度径向幂律指数' },
      { name: 'Sigma_0', symbol: '\\Sigma_0', range: '[0.1, 10.0]', unit: 'g/cm^2', desc: '盘根部表面密度' },
    ],
    properties: ['Halpha Equivalent Width', 'Rotational Velocity', 'Disk Mass', 'Radial Velocity'],
    tags: ['Be星', '星周盘', 'Halpha发射线', '用户派生模型', '粘滞吸积'],
    sources: 'Rivinius et al. (2013) A&ARv; Carciofi & Bjorkman (2006) ApJ; 用户科研笔记',
    user_preference: 'preferred',
    preferred: true,
    is_user: true,
  },
]

export const INITIAL_KNOWLEDGE_GRAPH = {
  nodes: [
    { id: 'stefan_boltzmann_law', label: '斯特藩-玻尔兹曼定律', category: 'physical_laws', formula: 'L = 4\\pi R^2 \\sigma T^4', preferred: true, properties: ['Luminosity', 'Effective Temperature', 'Radius'] },
    { id: 'wien_displacement_law', label: '维恩位移定律', category: 'physical_laws', formula: '\\lambda_{\\max} T = b', preferred: false, properties: ['Effective Temperature'] },
    { id: 'lane_emden_equation', label: '莱恩-埃姆登方程', category: 'equations_of_state_and_models', formula: '\\nabla^2 \\theta + \\theta^n = 0', preferred: false, properties: ['Density', 'Radius'] },
    { id: 'cardelli_ccm89_extinction', label: 'CCM89 消光模型', category: 'measurement_and_extinction', formula: 'A(\\lambda)/A(V) = a + b/R_V', preferred: false, properties: ['Extinction', 'Magnitude'] },
    { id: 'gaia_astrometric_parallax', label: '盖亚空间几何视差法', category: 'observational_methodology', formula: 'd = 1000/\\varpi', preferred: true, properties: ['Distance', 'Parallax'] },
    { id: 'eddington_luminosity_limit', label: '爱丁顿光度极限', category: 'reference_limits', formula: 'L_{\\text{Edd}} = 4\\pi G M c / \\kappa', preferred: true, properties: ['Luminosity', 'Mass'] },
    { id: 'chandrasekhar_mass_limit', label: '钱德拉塞卡极限', category: 'reference_limits', formula: 'M_{\\text{Ch}} \\approx 1.44 M_\\odot', preferred: true, properties: ['Mass', 'Density'] },
    { id: 'simbad_ned_concept_catalog', label: 'SIMBAD/NED 星表体系', category: 'concepts_and_catalogs', formula: '\\text{Obj} \\in \\mathcal{C}', preferred: false, properties: ['Spectral Type', 'Coordinates'] },
    { id: 'user_be_star_disk_emission', label: 'Be星星周盘模型 (派生)', category: 'user_private', formula: '\\Sigma(r) = \\Sigma_0 (r/R)^{-n}', preferred: true, is_user: true, properties: ['Rotational Velocity', 'Disk Mass'] },
    // Property connector nodes
    { id: 'prop_luminosity', label: '光度 (Luminosity)', category: 'concepts_and_catalogs', is_property: true, preferred: false, properties: ['Luminosity'] },
    { id: 'prop_teff', label: '有效温度 (Teff)', category: 'concepts_and_catalogs', is_property: true, preferred: false, properties: ['Effective Temperature'] },
    { id: 'prop_mass', label: '天体质量 (Mass)', category: 'concepts_and_catalogs', is_property: true, preferred: false, properties: ['Mass'] },
    { id: 'prop_distance', label: '天体距离 (Distance)', category: 'concepts_and_catalogs', is_property: true, preferred: false, properties: ['Distance'] },
    { id: 'prop_extinction', label: '星际消光 (Extinction)', category: 'concepts_and_catalogs', is_property: true, preferred: false, properties: ['Extinction'] },
  ],
  edges: [
    { source: 'stefan_boltzmann_law', target: 'prop_luminosity', label: '导出光度' },
    { source: 'stefan_boltzmann_law', target: 'prop_teff', label: '约束温度' },
    { source: 'wien_displacement_law', target: 'prop_teff', label: '测算温度' },
    { source: 'eddington_luminosity_limit', target: 'prop_luminosity', label: '理论上限' },
    { source: 'eddington_luminosity_limit', target: 'prop_mass', label: '吸积体质量' },
    { source: 'chandrasekhar_mass_limit', target: 'prop_mass', label: '简并质量极限' },
    { source: 'lane_emden_equation', target: 'chandrasekhar_mass_limit', label: '状态方程推演' },
    { source: 'gaia_astrometric_parallax', target: 'prop_distance', label: '绝对几何距离' },
    { source: 'cardelli_ccm89_extinction', target: 'prop_extinction', label: '色余校正' },
    { source: 'cardelli_ccm89_extinction', target: 'prop_distance', label: '距离模数消光修正' },
    { source: 'user_be_star_disk_emission', target: 'prop_teff', label: '盘根部受照射' },
    { source: 'simbad_ned_concept_catalog', target: 'prop_distance', label: '视差汇编' },
  ],
}
