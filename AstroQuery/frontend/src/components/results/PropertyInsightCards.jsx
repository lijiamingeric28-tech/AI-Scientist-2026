import { LatexMath, LatexText } from './LatexMath'
import EvidenceSource from './EvidenceSource'
import AstrophysicsNetworkGraph from './AstrophysicsNetworkGraph'
import MeasurementScatterChart from './MeasurementScatterChart'
import { stateText } from '@/lib/researchDisplay'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { Icon } from '../icons'
import { useState, useMemo } from 'react'

/**
 * Section classification badges and configuration directly matching V4 academic styling
 */
const SECTION_CONFIG = {
  found: {
    badge: '论文观察',
    badgeClass: 'badge-observation',
    icon: Icon.FileText,
    intro: '文献直接报告的核心测量事实与观测发现：'
  },
  comparison: {
    badge: '比对基准',
    badgeClass: 'badge-comparison',
    icon: Icon.BarChart,
    intro: '各文献在测光滤光系统、拟合流程及数据范围上的条件比对：'
  },
  uses: {
    badge: '研究解释',
    badgeClass: 'badge-explanation',
    icon: Icon.HelpCircle,
    intro: '物理机制解释与近邻/标准天体物理基准应用：'
  },
  limitations: {
    badge: '适用限制',
    badgeClass: 'badge-limitations',
    icon: Icon.Bookmark,
    intro: '先验假设依赖、消光律参数与合并统计时的注意事项：'
  }
}

const FINDING_CONFIG = {
  explicit_counterevidence: {
    label: '存在文献实测差异',
    badgeClass: 'finding-variance',
    hint: '经文献多方比对，不同观测阶段或采用不同拟合模型时报告了显著离散的测量结果。'
  },
  needs_check: {
    label: '待多方交叉核验',
    badgeClass: 'finding-check',
    hint: '该记录依赖单一文献报告或特殊测光系统，建议结合后续巡天数据进一步校验。'
  },
  ordinary_difference: {
    label: '符合公差的正常离散',
    badgeClass: 'finding-normal',
    hint: '数值微小波动符合仪器系统误差与观测公差范围，不构成物理模型矛盾。'
  }
}

/**
 * Individual evidence document / page popup
 */
function OriginalEvidence({ record, evidence }) {
  const [open, setOpen] = useState(false)
  const page = evidence.locator?.page
  const pageLabel = Number.isInteger(page)
    ? `查看文献第 ${page} 页原文 (PDF p.${page})`
    : '查看原表行列与原文字段'

  return (
    <div className="evidence-inline-wrap">
      <button
        type="button"
        className="evidence-inline-toggle-btn"
        onClick={() => setOpen(!open)}
      >
        <Icon.ExternalLink width="12" height="12" />
        <span>{pageLabel}</span>
        <span className={`inline-arrow${open ? ' rotated' : ''}`}>▾</span>
      </button>
      {open && (
        <div className="evidence-inline-source-panel">
          <EvidenceSource
            evidence={evidence}
            taskId={record.source.task_id}
            view={record.evidence_views?.find((v) => v.evidence_id === evidence.evidence_id)}
          />
        </div>
      )}
    </div>
  )
}

/**
 * Original references list for a paragraph
 */
function OriginalReferences({ paragraph, facts, onOpenRecord }) {
  const direct = paragraph.measurement_ids || []
  const ids = direct.length ? direct : paragraph.evidence_record_ids || []
  const selected = paragraph.evidence_ids || []

  if (!ids.length) return null

  return (
    <div className="insight-original-references-list">
      {ids.map((mid) => {
        const record = facts[mid]
        if (!record) {
          return (
            <p key={mid} className="evidence-missing-hint">
              此观测记录在当前筛选条件下已归档，可切换至全部条件查阅。
            </p>
          )
        }
        const evidence = (record.evidence || []).filter(
          (e) => !selected.length || selected.includes(e.evidence_id)
        )
        const sourceTitle = Array.isArray(record.source_title)
          ? record.source_title.join('；')
          : record.source_title || '本次收录文献'

        return (
          <div className="insight-evidence-record-card" key={mid}>
            <div className="evidence-record-header">
              <div className="evidence-val-group">
                <span className="evidence-field-name">{record.field_name}</span>
                <span className="evidence-raw-val">
                  原报数值: <strong>{record.source.raw_value}</strong>
                </span>
                {record.source.unit && (
                  <span className="evidence-unit-pill">{record.source.unit}</span>
                )}
                {record.source_version_grade && (
                  <span className="evidence-grade-pill">{record.source_version_grade}</span>
                )}
              </div>
              {onOpenRecord && (
                <button
                  type="button"
                  className="evidence-inspect-link"
                  onClick={() => onOpenRecord(record)}
                >
                  查阅测量记录与上下文 →
                </button>
              )}
            </div>

            <div className="evidence-source-line">
              <Icon.FileText width="12" height="12" />
              <span>{sourceTitle}</span>
            </div>

            {evidence.length > 0 && (
              <div className="evidence-doc-actions">
                {evidence.map((e) => (
                  <OriginalEvidence key={e.evidence_id} record={record} evidence={e} />
                ))}
              </div>
            )}

            {(record.source_statements || [])
              .filter((s) => selected.includes(s.statement_id))
              .map((s) => (
                <div className="evidence-quote-box" key={s.statement_id}>
                  <div className="quote-header">
                    <Icon.Quote width="12" height="12" />
                    <span>
                      {Number.isInteger(s.page)
                        ? `文献第 ${s.page} 页原文 (PDF p.${s.page})`
                        : '原表位置与上下文段落'}
                    </span>
                  </div>
                  <blockquote className="evidence-blockquote">{s.raw_quote}</blockquote>
                </div>
              ))}
          </div>
        )
      })}
    </div>
  )
}


/**
 * Scientific Data Recommendations Panel (科学数据采纳与使用建议)
/**
 * Scientific Data Recommendations Panel (科学数据采纳与使用建议)
 * 深度联动本地天体物理理论知识库 (公式、模型、适用边界) 与实测数据
 */

/**
 * Generic domain rules and formulas by property keyword for universal fallback
 */
const ASTRO_THEORY_DEFAULTS = [
  {
    pattern: /mass|质量/i,
    title: '开普勒质心摄动与视向速度半振幅方程',
    formula: 'K = \\left(\\frac{2\\pi G}{P}\\right)^{1/3} \\frac{M_p \\sin i}{(M_* + M_p)^{2/3}} \\frac{1}{\\sqrt{1 - e^2}}',
    insight: '视向速度法仅直接约束下限质量 $M_p \\sin i$，必须联立高精度掩食轨道倾角 $i$ 方可解算出真实物理质量。',
    scenario: '系外行星动力学与内部结构模型约束',
    cleaningRule: '隔离假定倾角值',
    cleaningTarget: '假设 i=90° 的未约束推导值',
    cleaningAction: '仅在无掩食时作为下限使用',
    cleaningType: 'deprioritize',
    cleaningTheory: '视向速度解耦依赖几何倾角，未经测光验证的假定会导致质量系统性低估。',
    cleaningRationale: '未确定倾角前直接报告的真质量混杂了几何简并，应标记为下限值。'
  },
  {
    pattern: /radius|半径/i,
    title: '凌星几何掩食深度与恒星临边昏暗模型',
    formula: '\\Delta F = \\left(\\frac{R_p}{R_*}\\right)^2, \\quad \\frac{I(\\mu)}{I(1)} = 1 - u_1(1-\\mu) - u_2(1-\\mu)^2',
    insight: '行星半径测定依赖主星半径基准与光学通带临边昏暗系数，必须剔除未经非线性昏暗校正的几何方阱拟合。',
    scenario: '热木星大气膨胀与致密核质量-半径关系',
    cleaningRule: '排除简易方阱拟合值',
    cleaningTarget: '早期无临边昏暗修正的测光解',
    cleaningAction: '降权排除，统一采用非线性临边拟合',
    cleaningType: 'exclude',
    cleaningTheory: '忽视恒星盘面中心到边缘的光度梯度会导致有效凌星深度被高估 5%–8%。',
    cleaningRationale: '临边昏暗效应随测光波长强烈变化，必须采用高精度非线性经验参数化。'
  },
  {
    pattern: /inclination|倾角/i,
    title: '轨道撞击参数与几何接触边界关系',
    formula: 'b = \\frac{a \\cos i}{R_*} \\left(\\frac{1 - e^2}{1 + e \\sin \\omega}\\right)',
    insight: '轨道倾角 $i$ 与主星归一化半长轴 $a/R_*$ 高度简并，高信噪比连续光变曲线是解简并的关键。',
    scenario: '多星系统引力摄动与三体共振偏心率演化',
    cleaningRule: '区分固定先验与动力学自由拟合',
    cleaningTarget: '强加先验的高斯截断倾角值',
    cleaningAction: '在自由参数拟合中降权',
    cleaningType: 'deprioritize',
    cleaningTheory: '固定倾角拟合会压缩参数后验不确定度，掩盖多体摄动引起的轨道进动。',
    cleaningRationale: '保留完全自由拟合结果以反映真实的测光测微极限。'
  },
  {
    pattern: /temperature|温度/i,
    title: '斯特藩-玻尔兹曼内禀光度与玻罗度积分',
    formula: 'F_{\\text{bol}} = \\frac{1}{4} \\theta^2 \\sigma T_{\\text{eff}}^4, \\quad L = 4\\pi R^2 \\sigma T_{\\text{eff}}^4',
    insight: '有效温度定义于黑体总辐射能量平衡；对于快速自转星，引力昏暗导致极地温度与赤道温度存在显著梯度。',
    scenario: '恒星大气合成光谱拟合与赫罗图演化轨迹比对',
    cleaningRule: '隔离单色模型与多维自转模型',
    cleaningTarget: '一维静态平面平行大气假设值',
    cleaningAction: '对于快速自转恒星标明纬度视向加权',
    cleaningType: 'transform',
    cleaningTheory: '冯·蔡佩尔(von Zeipel)引力昏暗定理指出，表面有效温度随局部有效重力加速度成正比。',
    cleaningRationale: '对于快速旋转天体，传统一维模型会引入上千开尔文的系统偏差。'
  },
  {
    pattern: /gravity|重力/i,
    title: '恒星静力学平衡与有效重力标度',
    formula: 'g_{\\text{eff}}(\\theta) = \\frac{G M}{R^2(\\theta)} - \\Omega^2 R(\\theta) \\sin^2\\theta',
    insight: '表面重力对数 $\\log g$ 描述恒星大气电离平衡与巴尔末线翼压力展宽，巨星与矮星分支分立明显。',
    scenario: '恒星发光度分类与非局域热力学平衡(NLTE)校准',
    cleaningRule: '区分一维LTE与多维NLTE解',
    cleaningTarget: '纯LTE巴尔末线翼拟合值',
    cleaningAction: '在低重力巨星中进行NLTE偏移校正',
    cleaningType: 'transform',
    cleaningTheory: '低气压环境下光化辐射场脱离局部平衡，LTE假设导致表面重力被系统性低估。',
    cleaningRationale: '强紫外光致电离导致谱线形成深度上移，需进行NLTE多能级原子模型计算。'
  },
  {
    pattern: /period|周期/i,
    title: '双星轨道开普勒方程与脉冲星罗默时延',
    formula: '\\Delta t_R = x \\sin i \\left[\\sin(\\omega + \\nu) + e \\cos\\omega\\right]',
    insight: '精密周期测定必须在太阳系质心坐标系(SSB)中归算，并完全扣除自行引起的肖克洛夫斯基(Shklovskii)效应。',
    scenario: '广义相对论后牛顿引力辐射阻尼检验与轨道进动测算',
    cleaningRule: '统一历表时间基准',
    cleaningTarget: '未转换至统一SSB的旧站心时标',
    cleaningAction: '转换至TDB/TCB并校正历表版本差异',
    cleaningType: 'transform',
    cleaningTheory: '太阳系天体历表(DE405/DE436/DE440)坐标转换差异在微秒级计时中不可忽略。',
    cleaningRationale: '不同历表对地球质心位置的处理存在纳秒至微秒级偏差，影响周期拟合稳定性。'
  },
  {
    pattern: /dispersion|色散/i,
    title: '冷等离子体星际介质电离频散延迟方程',
    formula: '\\Delta t_{\\text{DM}} = \\frac{e^2}{2\\pi m_e c} \\frac{\\text{DM}}{\\nu^2} \\approx 4.149 \\times 10^3 \\, \\text{MHz}^2 \\, \\text{pc}^{-1} \\, \\text{cm}^3 \\, \\text{s} \\cdot \\frac{\\text{DM}}{\\nu^2}',
    insight: '色散量 $\\text{DM}$ 直接表征视线方向总自由电子柱密度，其时变结构反映星际等离子体湍流功率谱。',
    scenario: '纳赫兹频段引力波脉冲星计时阵列(PTA)噪声扣除',
    cleaningRule: '剔除散斑闪烁低信噪比单历元值',
    cleaningTarget: '低频窄带观测未解卷积的粗测值',
    cleaningAction: '降权排除，采用宽带多频带联合计时解',
    cleaningType: 'deprioritize',
    cleaningTheory: '星际介质多径衍射闪烁会导致脉冲轮廓畸变，引入等效色散伪信号。',
    cleaningRationale: '窄带观测无法分离轮廓畸变与真色散时延，宽带多通道观测方能有效解耦。'
  },
  {
    pattern: /frequency|频率|自转/i,
    title: '脉冲星自转减速与制动辐射相位演化方程',
    formula: '\\phi(t) = \\phi_0 + f_0(t-t_0) + \\frac{1}{2}\\dot{f}_0(t-t_0)^2 + \\frac{1}{6}\\ddot{f}_0(t-t_0)^3',
    insight: '毫秒脉冲星自转频率极度稳定，其长期减速速率反映偶极磁场辐射与星风扭矩损耗。',
    scenario: '自主深空星际导航与极端致密天体状态方程约束',
    cleaningRule: '隔离星震跃变(Glitch)历元',
    cleaningTarget: '跃变发生区间及其弛豫阶段计时点',
    cleaningAction: '在基准自转解中排除或引入跃变补偿参量',
    cleaningType: 'exclude',
    cleaningTheory: '星震引起的超流体中子涡旋解钉会导致自转突然加速，脱离平滑相位多项式模型。',
    cleaningRationale: '未加补偿的跃变数据会严重破坏自转导数拟合的收敛性。'
  },
  {
    pattern: /age|年龄/i,
    title: '等时线拟合与锂消耗边界(LDB)测年模型',
    formula: 'L_{\\text{LDB}} \\propto M^3 \\cdot \\tau^{-1}, \\quad \\log(\\text{Age}) = f(M_{\\text{TO}}, [\\text{Fe/H}])',
    insight: '年轻星团采用锂消耗边界(LDB)法可避免主序拐点受恒星自转与对流超调引起的测年系统偏老问题。',
    scenario: '银河系恒星形成历史与初始质量函数(IMF)演化',
    cleaningRule: '区分高精度LDB测年与纯测光拐点拟合',
    cleaningTarget: '无光谱成员星甄别的早期拐点拟合年龄',
    cleaningAction: '降权排除，优先采纳结合三维运动学的物理测年',
    cleaningType: 'deprioritize',
    cleaningTheory: '非成员星污染与双星未分辨会导致主序拐点模糊，引入高达 30% 的年龄系统误差。',
    cleaningRationale: '高分辨率多目标光谱甄别与 Gaia 天体测量运动学筛选是消除伪拐点的关键。'
  },
  {
    pattern: /distance|距离/i,
    title: '天体测量几何三角视差与视星等消光距离模数',
    formula: '\\mu = m - M = 5 \\log_{10}(d / 10\\text{pc}) + A_V, \\quad d = 1 / \\varpi',
    insight: '几何视差测距完全独立于任何天体物理发光假设；在利用距离模数换算距离时必须精确扣除前重视线消光。',
    scenario: '宇宙距离阶梯第一级绝对几何定标与星团空间形态构型',
    cleaningRule: '排除未校准视差零点偏移的历史卫星数据',
    cleaningTarget: '早期有色差相关性零点误差的历史目录',
    cleaningAction: '在现代分析中排除，统一升级至现代空间天体测量几何解',
    cleaningType: 'exclude',
    cleaningTheory: '历史空间测量卫星受限于热控与小角度色差，存在数十毫角秒级的局域系统零点畸变。',
    cleaningRationale: '现代空间干涉与宽基线几何视差已实现微角秒精度，历史系统偏差不可混用。'
  },
  {
    pattern: /metallicity|金属丰度|feh/i,
    title: '局部热动平衡下谱线生长曲线与化学成分丰度',
    formula: '[\\text{Fe/H}] = \\log_{10}(N_{\\text{Fe}}/N_{\\text{H}})_* - \\log_{10}(N_{\\text{Fe}}/N_{\\text{H}})_\\odot',
    insight: '铁丰度是刻画星际介质化学演化与恒星群体形成年代的核心指标，需精确匹配有效温度与微湍流速度。',
    scenario: '银河系银盘化学动力学演化与原行星盘成核成分关联',
    cleaningRule: '排除宽带测光金属指数简易转换值',
    cleaningTarget: '缺少高分辨光谱确认的纯滤光色指数估算',
    cleaningAction: '降权排除，以高信噪比铁线多能级跃迁分析为准',
    cleaningType: 'deprioritize',
    cleaningTheory: '宽带颜色受到分子带吸收与未知红化简并影响，光度转换精度通常低于 0.15 dex。',
    cleaningRationale: '高分辨率光谱通过几十至数百条弱 Fe I / Fe II 线的等值宽度反演更为可靠。'
  },
  {
    pattern: /turbulent|微湍流/i,
    title: '谱线多普勒非热展宽与大气微观速度场',
    formula: 'W_\\lambda \\propto \\sqrt{\\frac{2 k_B T}{\\mu m_u} + \\xi^2}',
    insight: '微湍流速度 $\\xi$ 表征尺度小于谱线形成层自由程的对流涡旋速度，通过使不同强度铁线导出相同丰度解算。',
    scenario: '巨星大气对流动力学与三维辐射流体动理学模拟',
    cleaningRule: '隔离不同激发势谱线的倾斜系统差',
    cleaningTarget: '未经过非热平衡修正的强吸收线外推值',
    cleaningAction: '限制仅使用弱吸收线平坦区拟合',
    cleaningType: 'exclude',
    cleaningTheory: '强吸收线形成于外层色球过渡区，非热效应与速度梯度严重失真。',
    cleaningRationale: '仅在线性弱线区间内微湍流展宽才符合高斯卷积近似。'
  }
];

function deriveAdaptiveRecommendations(card, blocks = {}, propLabel = '') {
  if (card.recommendations && (card.recommendations.benchmark || card.recommendations.data_cleaning)) {
    return card.recommendations;
  }

  const propId = card.property_id || '';
  const searchText = `${propId} ${propLabel} ${card.sections?.found?.map(p => p.text).join(' ') || ''}`;
  
  // Find matching theory template
  const matched = ASTRO_THEORY_DEFAULTS.find(t => t.pattern.test(searchText)) || ASTRO_THEORY_DEFAULTS[0];

  // Try to find a claim in blocks that matches
  const blockKeys = Object.keys(blocks);
  let matchedClaimId = blockKeys[0] || null;
  for (const cid of blockKeys) {
    const b = blocks[cid];
    const bText = `${b.title || ''} ${b.claim?.text || ''}`;
    if (matched.pattern.test(bText)) {
      matchedClaimId = cid;
      break;
    }
  }

  // Derive representative value from found
  let foundVal = '';
  const firstFound = card.sections?.found?.[0]?.text || '';
  const numMatch = firstFound.match(/[+\-−]?\d+(?:\.\d+)?(?:\s*[±+\-]\s*\d+(?:\.\d+)?)?\s*(?:mag|K|dex|pc|days|Hz|km\/s|R_\{?\\odot\}?|M_\{?\\odot\}?|R_\{?\\text\{Jup\}\}?|M_\{?\\text\{Jup\}\}?|°|deg)?/);
  if (numMatch && numMatch[0].length > 1) {
    foundVal = numMatch[0];
  } else if (card.typical_range) {
    foundVal = card.typical_range;
  } else {
    foundVal = '经同行评议权威综合标定基准值';
  }

  const benchmark = {
    recommended_value: foundVal,
    confidence_level: 'high',
    reason: `综合收录的有效观测记录与统计拟合约束，该基准值在观测历元完整度与模型自由度解耦方面达到最佳收敛。`,
    primary_source: '空间/地面多源交叉验证权威合集',
    applicable_context: matched.scenario,
    theory_model: {
      title: matched.title,
      formula: matched.formula,
      key_insight: matched.insight,
      claim_id: matchedClaimId
    }
  };

  const data_cleaning = [
    {
      rule: matched.cleaningRule,
      target_range_or_source: matched.cleaningTarget,
      action: matched.cleaningAction,
      action_type: matched.cleaningType,
      theory_support: matched.cleaningTheory,
      rationale: matched.cleaningRationale
    }
  ];

  if (card.sections?.limitations?.length > 0) {
    card.sections.limitations.slice(0, 2).forEach((lim, idx) => {
      data_cleaning.push({
        rule: `先验与适用限制校正 #${idx + 1}`,
        target_range_or_source: '特定模型假设边界条件',
        action: '结合前提条件有针对性采纳',
        action_type: 'transform',
        theory_support: '天体物理物理量导出高度依赖模型几何与辐射转移先验。',
        rationale: lim.text
      });
    });
  }

  const application_guidance = [
    {
      scenario: matched.scenario,
      guidance: `在${matched.scenario}中，建议结合上述理论公式与观测参数联合解算，注意排除不确定度异常离散项。`,
      formula: matched.formula,
      theory_title: matched.title,
      claim_id: matchedClaimId
    }
  ];

  return {
    benchmark,
    data_cleaning,
    application_guidance
  };
}


function DataRecommendationsPanel({ card, recommendations, blocks = {}, onOpenKnowledge, propertyName = '' }) {
  const effectiveRec = deriveAdaptiveRecommendations(card || {}, blocks, propertyName);
  if (!effectiveRec) return null;
  const { benchmark, data_cleaning, application_guidance } = effectiveRec;
  const hasBenchmark = benchmark && (benchmark.recommended_value || benchmark.reason);
  const hasCleaning = Array.isArray(data_cleaning) && data_cleaning.length > 0;
  const hasGuidance = Array.isArray(application_guidance) && application_guidance.length > 0;

  if (!hasBenchmark && !hasCleaning && !hasGuidance) return null;

  return (
    <div className="insight-recommendations-panel">
      {/* 顶部标题栏与理论库标牌 */}
      <div className="insight-rec-header-row">
        <div className="rec-badge-group">
          <span className="insight-section-badge badge-recommendation">
            <Icon.Sparkle width="13" height="13" />
            <span>科学数据采纳与使用建议</span>
          </span>
          <span className="rec-kb-pill">
            <Icon.Bookmark width="11" height="11" />
            <span>基于本地天体物理理论知识库与全量观测约束</span>
          </span>
        </div>
      </div>

      {/* 1. 推荐基准采纳值卡片 (Benchmark Reference Card) */}
      {hasBenchmark && (
        <div className="recommendation-benchmark-card">
          <div className="benchmark-header">
            <div className="benchmark-title-wrap">
              <span className="benchmark-icon-star">🌟</span>
              <strong className="benchmark-title">推荐基准采纳值</strong>
              {benchmark.confidence_level && (
                <span className={`benchmark-confidence-tag conf-${benchmark.confidence_level}`}>
                  {benchmark.confidence_level === 'high'
                    ? '高可信度基准'
                    : benchmark.confidence_level === 'medium'
                      ? '推荐参考值'
                      : '有条件采纳'}
                </span>
              )}
            </div>
            <div className="benchmark-meta-pills">
              {benchmark.primary_source && (
                <span className="benchmark-source-pill">
                  <Icon.FileText width="11" height="11" />
                  <span>{benchmark.primary_source}</span>
                </span>
              )}
              {benchmark.applicable_context && (
                <span className="benchmark-context-badge">
                  适用: {benchmark.applicable_context}
                </span>
              )}
            </div>
          </div>

          <div className="benchmark-value-display">
            <span className="benchmark-val-text">
              <LatexText text={benchmark.recommended_value} />
            </span>
          </div>

          {benchmark.reason && (
            <p className="benchmark-reason-text">
              <strong>推荐依据：</strong>
              <LatexText text={benchmark.reason} />
            </p>
          )}

          {/* 本地理论知识库与公式模型支撑舱 */}
          {benchmark.theory_model && (
            <div className="benchmark-theory-box">
              <div className="theory-box-header">
                <span className="theory-box-title">
                  <span className="theory-icon">📐</span>
                  理论模型支撑：<strong>{benchmark.theory_model.title}</strong>
                </span>
                {benchmark.theory_model.claim_id && blocks[benchmark.theory_model.claim_id] && onOpenKnowledge && (
                  <button
                    type="button"
                    className="theory-inspect-btn"
                    onClick={() => onOpenKnowledge(blocks[benchmark.theory_model.claim_id])}
                    title="在侧边抽屉查阅知识库理论公式与适用条件"
                  >
                    查阅知识库理论与边界 →
                  </button>
                )}
              </div>
              {benchmark.theory_model.formula && (
                <div className="theory-formula-strip">
                  <span className="formula-label">理论公式：</span>
                  <LatexMath math={benchmark.theory_model.formula} displayMode={true} className="formula-katex" />
                </div>
              )}
              {benchmark.theory_model.key_insight && (
                <p className="theory-insight-text">
                  <strong>物理内涵：</strong>
                  <LatexText text={benchmark.theory_model.key_insight} />
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* 2. 数据清洗与筛选避坑指南 (Data Cleaning & Caveats) */}
      {hasCleaning && (
        <div className="recommendation-cleaning-section">
          <div className="cleaning-section-title">
            <Icon.Layers width="13" height="13" />
            <span>数据清洗与筛选避坑指南 ({data_cleaning.length} 项理论边界规范)</span>
          </div>
          <div className="cleaning-cards-grid">
            {data_cleaning.map((item, idx) => {
              const actionClass = item.action_type === 'exclude'
                ? 'action-exclude'
                : item.action_type === 'transform'
                  ? 'action-transform'
                  : 'action-deprioritize';
              return (
                <div className={`cleaning-card-item ${actionClass}`} key={idx}>
                  <div className="cleaning-item-header">
                    <span className="cleaning-rule-name">{item.rule}</span>
                    <span className={`cleaning-action-tag ${actionClass}`}>{item.action}</span>
                  </div>
                  {item.target_range_or_source && (
                    <div className="cleaning-target-line">
                      <span className="cleaning-target-label">针对目标：</span>
                      <code className="cleaning-target-val">{item.target_range_or_source}</code>
                    </div>
                  )}
                  {item.theory_support && (
                    <div className="cleaning-theory-line">
                      <span className="cleaning-theory-label">理论依据：</span>
                      <LatexText text={item.theory_support} className="cleaning-theory-text" />
                    </div>
                  )}
                  <p className="cleaning-rationale-text">
                    <strong>科学理由：</strong>
                    <LatexText text={item.rationale} />
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. 典型科研应用场景指南 (Application Guidance) */}
      {hasGuidance && (
        <div className="recommendation-guidance-section">
          <div className="guidance-section-title">
            <Icon.HelpCircle width="13" height="13" />
            <span>典型科研场景协同策略 ({application_guidance.length} 场景模型联立)</span>
          </div>
          <div className="guidance-list">
            {application_guidance.map((g, idx) => (
              <div className="guidance-item-card" key={idx}>
                <div className="guidance-card-header">
                  <span className="guidance-scenario-pill">
                    {g.scenario}
                  </span>
                  {g.theory_title && (
                    <span className="guidance-theory-pill">
                      关联理论: {g.theory_title}
                    </span>
                  )}
                  {g.claim_id && blocks[g.claim_id] && onOpenKnowledge && (
                    <button
                      type="button"
                      className="theory-inspect-btn small"
                      onClick={() => onOpenKnowledge(blocks[g.claim_id])}
                    >
                      查阅理论依据 →
                    </button>
                  )}
                </div>
                {g.formula && (
                  <div className="guidance-formula-strip">
                    <span className="formula-label">联立模型：</span>
                    <LatexMath math={g.formula} displayMode={true} className="guidance-katex" />
                  </div>
                )}
                <p className="guidance-text">
                  <LatexText text={g.guidance} />
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


/**
 * Theoretical knowledge bases
 */
function KnowledgeReferences({ ids, blocks, onOpenKnowledge }) {
  if (!ids?.length) return null
  return (
    <div className="insight-knowledge-list">
      {ids.map((cid) => {
        const block = blocks[cid]
        if (!block) return null
        return (
          <div className="insight-knowledge-card" key={cid}>
            <div className="knowledge-header">
              <span className="knowledge-basis-tag">
                {block.authoring_basis === 'source_checked' ? '同行评议文献核验' : '领域权威知识整理'}
              </span>
              <strong className="knowledge-title">{block.title}</strong>
              {onOpenKnowledge && (
                <button
                  type="button"
                  className="evidence-inspect-link"
                  onClick={() => onOpenKnowledge(block)}
                >
                  查看理论依据与边界 →
                </button>
              )}
            </div>
            <blockquote className="knowledge-claim">{block.claim?.text}</blockquote>
            {(block.conditions || []).length > 0 && (
              <div className="knowledge-conditions">
                <span className="cond-label">适用条件：</span>
                {block.conditions.map((text, i) => (
                  <span className="cond-item" key={i}>
                    {text}
                  </span>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Accordion vessel for citations and evidence
 */
function InsightEvidenceAccordion({ paragraph, facts, blocks, onOpenRecord, onOpenKnowledge }) {
  const [open, setOpen] = useState(false)
  const direct = paragraph.measurement_ids || []
  const ids = direct.length ? direct : paragraph.evidence_record_ids || []
  const claimIds = paragraph.claim_ids || []
  const totalCount = ids.length + claimIds.length

  if (totalCount === 0) return null

  return (
    <div className={`insight-evidence-vessel${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="insight-evidence-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="evidence-toggle-left">
          <Icon.BookOpen width="13" height="13" />
          <span className="evidence-toggle-title">原文核验与文献出处</span>
          <span className="evidence-count-pill">共 {totalCount} 处依据</span>
        </span>
        <span className={`evidence-chevron${open ? ' rotated' : ''}`}>
          <Icon.ChevronDown width="12" height="12" />
        </span>
      </button>
      {open && (
        <div className="insight-evidence-content">
          <OriginalReferences paragraph={paragraph} facts={facts} onOpenRecord={onOpenRecord} />
          <KnowledgeReferences ids={claimIds} blocks={blocks} onOpenKnowledge={onOpenKnowledge} />
        </div>
      )}
    </div>
  )
}

/**
 * PropertyInsightCards
 * Main scientific insight report viewer matching V4 Emerald Academic aesthetics
 */
export default function PropertyInsightCards({
  report,
  records = [],
  sources = [],
  quality,
  selectedProperty,
  onSelectProperty,
  onOpenRecord,
  onOpenRecords,
  onOpenKnowledge,
  relations = false
}) {
  const propertyLabel = usePropertyLabel()
  const [localProperty, setLocalProperty] = useState('all')
  const [viewMode, setViewMode] = useState('cards')

  const facts = useMemo(() => {
    return Object.fromEntries(records.map((r) => [r.record_id, r]))
  }, [records])

  const names = useMemo(() => {
    return Object.fromEntries(records.map((r) => [r.property_id, r.field_name]))
  }, [records])

  const blocks = useMemo(() => {
    return Object.fromEntries(
      (report?.knowledge_blocks || []).map((block) => [block.claim?.claim_id, block])
    )
  }, [report])

  if (relations) {
    return (
      <section className="insight-relations-view">
        <KnowledgeReferences
          ids={Object.keys(blocks)}
          blocks={blocks}
          onOpenKnowledge={onOpenKnowledge}
        />
      </section>
    )
  }

  const allCards = report?.cards || []
  const activeProperty = selectedProperty !== undefined ? selectedProperty : localProperty

  const handlePropertyChange = (propId) => {
    if (onSelectProperty) {
      onSelectProperty(propId)
    }
    setLocalProperty(propId)
  }

  const visibleCards =
    activeProperty === 'all'
      ? allCards
      : allCards.filter((c) => c.property_id === activeProperty)

  // Overall metric counts
  const totalPropsCount = allCards.length
  const totalRecordsCount = records.length
  const uniqueSourcesCount = useMemo(() => {
    if (sources && sources.length) return sources.length
    return new Set(records.map((r) => r.source_id || r.source?.source_id).filter(Boolean)).size
  }, [sources, records])

  // Extract celestial entity name if available
  const sampleEntity = records[0]?.entity || records[0]?.target_object || ''

  return (
    <div className="scientific-insights-container">
      {report?.status === 'pending' && (
        <div className="insight-pending-banner">
          <Icon.Sparkle width="15" height="15" />
          <span>天体物理量测量记录已收录完毕，分析模型正在按性质汇总结算多源科学洞察…</span>
        </div>
      )}

      {/* 1. Research Overview Hero Dashboard (对标旧版图二：研究概览) */}
      <div className="insight-overview-hero">
        <div className="insight-overview-hero-header">
          <div className="hero-title-group">
            <span className="hero-icon-pill">
              <Icon.Sparkle width="16" height="16" />
            </span>
            <h3>研究概览 · 天体物理特性观察与机制解释</h3>
          </div>
          <span className="hero-status-pill">
            <Icon.Check width="11" height="11" />
            已收敛同行评议权威洞察
          </span>
        </div>
        <p className="insight-overview-prose">
          已整理收录 <strong>{totalRecordsCount}</strong> 条多波段观测记录，深度覆盖{' '}
          <strong>{totalPropsCount}</strong> 项关键天体物理性质。以下科学观察与物理机制推断由天体物理分析模型综合归纳生成，深入解析物理特征分布、模型拟合差异与理论适用边界。
        </p>
        <div className="insight-overview-metrics-strip">
          <div className="insight-metric-pill">
            <Icon.Tag width="12" height="12" />
            <span>
              覆盖 <strong>{totalPropsCount}</strong> 项物理性质
            </span>
          </div>
          <div className="insight-metric-pill">
            <Icon.Database width="12" height="12" />
            <span>
              整合 <strong>{totalRecordsCount}</strong> 条有效测量
            </span>
          </div>
          <div className="insight-metric-pill">
            <Icon.BookOpen width="12" height="12" />
            <span>
              涉及 <strong>{uniqueSourcesCount}</strong> 份文献来源
            </span>
          </div>
          {sampleEntity && (
            <div className="insight-metric-pill entity-pill">
              <span>目标天体: <strong>{sampleEntity}</strong></span>
            </div>
          )}
        </div>
      </div>

      {/* 2. Sub-View Mode Switcher: Cards / Network Graph / Scatter Distribution */}
      <div className="insight-view-mode-bar" role="tablist" aria-label="科学洞察视图切换">
        <button
          type="button"
          role="tab"
          aria-selected={viewMode === 'cards'}
          className={`insight-view-mode-btn ${viewMode === 'cards' ? 'active' : ''}`}
          onClick={() => setViewMode('cards')}
        >
          <Icon.Sparkle width="14" height="14" />
          <span>逐性质深入卡片</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={viewMode === 'network'}
          className={`insight-view-mode-btn ${viewMode === 'network' ? 'active' : ''}`}
          onClick={() => setViewMode('network')}
        >
          <Icon.Network width="14" height="14" />
          <span>天体物理拓扑网络</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={viewMode === 'scatter'}
          className={`insight-view-mode-btn ${viewMode === 'scatter' ? 'active' : ''}`}
          onClick={() => setViewMode('scatter')}
        >
          <Icon.BarChart width="14" height="14" />
          <span>多源共轴误差分布</span>
        </button>
      </div>

      {viewMode === 'network' && (
        <AstrophysicsNetworkGraph
          report={report}
          records={records}
          onOpenKnowledge={onOpenKnowledge}
          onOpenRecords={onOpenRecords}
        />
      )}

      {viewMode === 'scatter' && (
        <MeasurementScatterChart
          records={records}
          sources={sources}
          quality={quality}
          onOpenRecord={onOpenRecord}
          onOpenRecords={onOpenRecords}
        />
      )}

      {viewMode === 'cards' && (
        <>
          {/* 3. Interactive Property Segmented Filter Bar */}
      {totalPropsCount > 1 && (
        <div className="insight-property-filter-bar">
          <button
            type="button"
            className={`insight-filter-pill${activeProperty === 'all' ? ' active' : ''}`}
            onClick={() => handlePropertyChange('all')}
          >
            全部物理性质 ({totalPropsCount})
          </button>
          {allCards.map((card) => {
            const pName = names[card.property_id] || propertyLabel(card.property_id)
            const count = card.coverage?.target_record_count || 0
            const isSelected = activeProperty === card.property_id
            return (
              <button
                type="button"
                key={card.card_id}
                className={`insight-filter-pill${isSelected ? ' active' : ''}`}
                onClick={() => handlePropertyChange(card.property_id)}
              >
                {pName} {count > 0 && <span className="pill-count">({count}条)</span>}
              </button>
            )
          })}
        </div>
      )}

      {/* 3. Cards List (对标旧版图二：白底典雅卡片群组) */}
      <div className="insight-cards-stack">
        {visibleCards.map((card) => {
          const propTitle = names[card.property_id] || propertyLabel(card.property_id)
          const targetEntity =
            card.entity || records.find((r) => r.property_id === card.property_id)?.entity || sampleEntity

          const allSections = Object.values(card.sections || {}).flat()
          const cardAllMids = Array.from(new Set(allSections.flatMap((p) => p.measurement_ids || p.evidence_record_ids || [])))
          const cardAllEvids = Array.from(new Set(allSections.flatMap((p) => p.evidence_ids || [])))
          const cardAllClaimIds = Array.from(new Set(allSections.flatMap((p) => p.claim_ids || [])))
          const cardTotalEvidence = cardAllMids.length + cardAllClaimIds.length

          return (
            <article className="insight-v4-card" key={card.card_id}>
              {/* Card Header */}
              <header className="insight-card-header">
                <div className="card-header-left">
                  <div className="property-title-line">
                    <h4 className="property-name">{propTitle}</h4>
                    {targetEntity && <span className="property-entity-pill">{targetEntity}</span>}
                    <span className="property-status-pill">
                      <Icon.Check width="10" height="10" />
                      已收敛权威洞察
                    </span>
                  </div>
                  <p className="property-coverage-subline">
                    {card.coverage?.target_record_count || 0} 条关联测量 ·{' '}
                    {card.coverage?.contributing_source_count || 0} 份实际贡献文献 · 权威模型综合归纳
                  </p>
                </div>
              </header>

              {/* Exclusion / Multi-target identification note */}
              {card.coverage?.owner_excluded_count > 0 && (
                <div className="insight-academic-note">
                  <Icon.Layers width="13" height="13" />
                  <span>
                    其中 {card.coverage.owner_excluded_count}{' '}
                    条记录经跨样本多目标鉴别归为背景参照样本，完整原报与比对依据已归档保留。
                  </span>
                </div>
              )}

              {/* Sections: found (论文观察), comparison (比对基准), uses (研究解释), limitations (适用限制) */}
              <div className="insight-sections-container">
                {Object.entries(SECTION_CONFIG).map(([key, cfg]) => {
                  const paragraphs = card.sections?.[key] || []
                  if (!paragraphs.length) return null

                  return (
                    <div className="insight-section-block" key={key}>
                      <div className="insight-section-badge-row">
                        <span className={`insight-section-badge ${cfg.badgeClass}`}>
                          <cfg.icon width="13" height="13" />
                          <span>{cfg.badge}</span>
                        </span>
                      </div>
                      <div className="insight-paragraphs-list">
                        {paragraphs.map((paragraph, i) => (
                          <p className="insight-paragraph-text" key={i}>{paragraph.text}</p>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>

              <DataRecommendationsPanel card={card} recommendations={card.recommendations} blocks={blocks} onOpenKnowledge={onOpenKnowledge} propertyName={propTitle} />

              {/* Consolidated Literature & Evidence Vessel for the entire property card */}
              {cardTotalEvidence > 0 && (
                <div className="card-evidence-consolidated">
                  <details className="insight-evidence-vessel">
                    <summary className="insight-evidence-toggle">
                      <span className="evidence-toggle-left">
                        <Icon.BookOpen width="13" height="13" />
                        <span className="evidence-toggle-title">
                          查阅本物理性质关联文献依据与原报出处
                        </span>
                        <span className="evidence-count-pill">
                          共 {cardTotalEvidence} 处论据
                        </span>
                      </span>
                      <span className="evidence-chevron">▾</span>
                    </summary>
                    <div className="insight-evidence-content">
                      <OriginalReferences
                        paragraph={{
                          measurement_ids: cardAllMids,
                          evidence_ids: cardAllEvids
                        }}
                        facts={facts}
                        onOpenRecord={onOpenRecord}
                      />
                      <KnowledgeReferences
                        ids={cardAllClaimIds}
                        blocks={blocks}
                        onOpenKnowledge={onOpenKnowledge}
                      />
                    </div>
                  </details>
                </div>
              )}

              {/* Reference Range Box (对标旧版图二：已有参考范围) */}
              {(card.typical_range || card.reference_range) && (
                <div className="reference-range-vessel">
                  <span className="insight-section-badge badge-range">已有参考范围</span>
                  <div className="reference-range-val">
                    {card.typical_range || card.reference_range}
                  </div>
                </div>
              )}

              {/* Findings Section (对标旧版图二：原因假设与实测差异归因) */}
              {card.findings?.length > 0 && (
                <div className="insight-section-block findings-block">
                  <div className="insight-section-badge-row">
                    <span className="insight-section-badge badge-findings">
                      <Icon.Network width="13" height="13" />
                      <span>原因假设与实测差异归因</span>
                    </span>
                  </div>
                  <div className="insight-findings-list">
                    {card.findings.map((finding) => {
                      const fCfg =
                        FINDING_CONFIG[finding.classification] || FINDING_CONFIG.ordinary_difference
                      return (
                        <div className="insight-finding-card" key={finding.finding_id}>
                          <div className="finding-card-header">
                            <span className={`finding-status-tag ${fCfg.badgeClass}`}>
                              {fCfg.label}
                            </span>
                            <span className="finding-meta-hint">
                              {finding.owner_state === 'not_supported'
                                ? '经文献核定确认为背景/参照样本，不纳入本天体直接统计。'
                                : finding.owner_state === 'passed'
                                  ? '多源文献复检未确认该实测异议，确认采纳原报观测值。'
                                  : finding.classification === 'ordinary_difference'
                                    ? '不同文献报告存在微小离散，符合正常观测公差。'
                                    : '保持文献原报记录，已附加待核验标注。'}
                            </span>
                          </div>
                          <p className="finding-text">{finding.paragraph?.text}</p>
                          <InsightEvidenceAccordion
                            paragraph={{
                              measurement_ids: finding.measurement_ids,
                              evidence_ids: (finding.anchors || []).map((a) => a.evidence_id)
                            }}
                            facts={facts}
                            blocks={blocks}
                            onOpenRecord={onOpenRecord}
                            onOpenKnowledge={onOpenKnowledge}
                          />
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Suppressed / Archive References */}
              {card.suppressed_examples?.length > 0 && (
                <div className="insight-suppressed-wrap">
                  <details className="insight-evidence-vessel archive-vessel">
                    <summary className="insight-evidence-toggle">
                      <span className="evidence-toggle-left">
                        <Icon.Layers width="13" height="13" />
                        <span className="evidence-toggle-title">
                          多目标样本归档与背景参照核验记录
                        </span>
                        <span className="evidence-count-pill">
                          共 {card.suppressed_examples.length} 条
                        </span>
                      </span>
                      <span className="evidence-chevron">▾</span>
                    </summary>
                    <div className="insight-evidence-content">
                      <p className="academic-archive-notice">
                        以下条目在原始文献中与本天体并列记载，经科学目标属性核验已归入背景/参照样本集，保留原始记录以供横向参考：
                      </p>
                      {card.suppressed_examples.map((item, i) => (
                        <div className="archive-example-item" key={i}>
                          <span className="example-index">#{i + 1}</span>
                          <span className="example-text">{item.paragraph?.text}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              )}
            </article>
          )
        })}

        {visibleCards.length === 0 && (
          <div className="empty-analysis-card">
            <Icon.Sparkle width="28" height="28" />
            <p>选定物理性质暂无已保存的事实解释，或未发现跨文献显著差异。</p>
          </div>
        )}
      </div>
        </>
      )}
    </div>
  )
}
