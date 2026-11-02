/* Mock 流水线数据 —— 阶段定义 + 卡 1 完成态输出
 *
 * 结构对齐后端：
 * - 阶段状态: waiting | running | completed | error | skipped | cancelled
 * - 澄清 payload 对齐 subgraph1 interrupt 真实结构（type/question/target_entity/requested_properties）
 * - 完成态输出对齐 MainGraphState 字段（target_entity / simbad_info / property_spec）
 */

export const STAGE_DEFS = [
  { id: 'understand', name: '任务理解' },
  { id: 'retrieval', name: '数据检索' },
  { id: 'extraction', name: '数据提取' },
  { id: 'quality_check', name: '质量检查' },
  { id: 'clean', name: '数据清洗' },
  { id: 'deliver', name: '数据交付' },
  { id: 'done', name: '任务完成' },
]

/* 卡 1「任务理解」展开：垂直时间线子步骤（用户手绘定案） */
export const UNDERSTAND_SUBSTEPS = [
  { id: 'confirm', label: '查询确认' },
  { id: 'simbad', label: 'simbad查询' },
  { id: 'research', label: '研究方向确定' },
]

/* 卡 1 完成态产出（对齐 target_entity / simbad_info / property_spec）
 * 注意：卡 1 阶段还没有数据值——标准性质展示的是 property_spec 的
 * "白名单定义"（性质名 + 标准单位），数据值在检索/提取后才产生。
 * markdown 为渲染主体（设计 D4）。 */
export const understandOutput = {
  targetEntity: 'M31',
  simbad: {
    mainId: 'M 31',
    otype: 'G（星系）',
    ra: '00:42:44.33',
    dec: '+41:16:07.5',
  },
  properties: [
    { propertyId: 'distance', name: '距离', unit: 'kpc' },
    { propertyId: 'metallicity', name: '金属丰度', unit: '[Fe/H]' },
    { propertyId: 'mass', name: '总质量', unit: 'M☉' },
  ],
  markdown: `**目标天体**：M31

**SIMBAD 身份**：\`M 31\` · G（星系）· RA \`00:42:44.33\` · Dec \`+41:16:07.5\`

**标准性质**（含标准单位）：
- 距离 \`distance\` → 标准单位 kpc
- 金属丰度 \`metallicity\` → 标准单位 [Fe/H]
- 总质量 \`mass\` → 标准单位 M☉`,
}

/* 卡 2「数据检索」三路分组初始结构（对齐后端 retrieval 子图三路） */
export function makeRetrievalGroups() {
  return [
    {
      id: 'database',
      name: '数据库',
      steps: [
        { id: 'match', label: '数据匹配', status: 'waiting', detail: null },
        { id: 'extract', label: '数据提取', status: 'waiting', detail: null, progress: null },
        { id: 'summary', label: '总结', status: 'waiting', detail: null },
      ],
    },
    {
      id: 'paper',
      name: '论文',
      steps: [
        { id: 'build', label: '构建查询串', status: 'waiting', detail: null },
        { id: 'search', label: '检索与去重', status: 'waiting', detail: null },
        { id: 'download', label: '下载', status: 'waiting', detail: null, progress: null },
      ],
    },
    {
      id: 'supplementary',
      name: '补充材料',
      steps: [
        { id: 'find', label: '查找补充材料', status: 'waiting', detail: null, progress: null, substatus: null },
        { id: 'summary', label: '总结', status: 'waiting', detail: null },
      ],
    },
  ]
}

/* 卡 2 mock 数据（M31 场景，字段对齐后端 state）：
 * - catalog_progress {completed, total, current_catalog}（表名来自 catalog_config.name）
 * - pdf_download_progress {completed, total, current_paper}（bibcode）
 * - ads_query_groups / ads_query_strings / ads_total_found
 */
export const RETRIEVAL_MOCK = {
  // 12 次查询：5 类星表（Gaia DR3 ×3 / 2MASS ×2 / AllWISE ×2 / SDSS DR9 ×3 / Pan-STARRS1 ×2）
  catalogs: [
    'Gaia DR3', 'Gaia DR3', 'Gaia DR3',
    '2MASS', '2MASS',
    'AllWISE', 'AllWISE',
    'SDSS DR9', 'SDSS DR9', 'SDSS DR9',
    'Pan-STARRS1', 'Pan-STARRS1',
  ],
  matchDetail: '匹配到 5 类星表，共 12 次查询',
  dbSummary: '成功 4 个表 · 失败 1 个 · 提取 86 条数据',
  // 论文：按性质族构建查询串
  queryGroups: ['距离族', '金属丰度族'],
  searchDetail: '查询串 1「距离族」12 篇 · 查询串 2「金属丰度族」8 篇 → 合并去重 15 篇',
  // 15 篇论文 bibcode（下载 12 成功 / 3 失败）
  bibcodes: [
    '2016Natur.531..202S', '2012MNRAS.427.1463Z', '2018A&A...616A...1G',
    '2014ApJ...780..128I', '2001AJ....121.2557D', '2019ApJS..224...31M',
    '2013ApJ...763...12G', '2010ApJ...709..585D', '2017A&A...605A...3M',
    '2015MNRAS.449..118L', '2011ApJ...731..113C', '2005ApJ...622..244S',
    '2020ApJ...889...37C', '2018MNRAS.473.4958D', '2009ApJ...690..512S',
  ],
  downloadDone: '已下载 12 篇 · 失败 3 篇',
  // 补充材料验证表（论文内子状态）
  suppTables: ['J/MNRAS/427/1463', 'J/A+A/616/A1', 'J/ApJS/224/31', 'J/AJ/157/190'],
  suppSummary: '找到 4 张表 · 提取 28 条数据',
}

/* 卡 3「数据提取」四步线性展开（对齐后端节点：
 * pdf_batch_converter→vlm_batch_extractor→bbox_batch_annotator→figure_extractor→result_builder） */
export function makeExtractionSubsteps() {
  return [
    { id: 'paper', label: '论文提取', status: 'waiting', detail: null, progress: null },
    { id: 'bbox', label: '字段验证与定位', status: 'waiting', detail: null, progress: null, failures: null },
    { id: 'figure', label: '图片提取', status: 'waiting', detail: null, progress: null },
    { id: 'summary', label: '总结', status: 'waiting', detail: null },
  ]
}

/* 卡 3 mock 数据（12 篇已下载论文，对齐后端字段：
 * extraction_progress {completed,total,current_paper} /
 * bbox_annotation_progress {completed,total,current_key=bibcode_idx} /
 * extraction_failed / bbox_annotation_failed [{key,bibcode,reason}] */
export const EXTRACTION_MOCK = {
  papers: RETRIEVAL_MOCK.bibcodes.slice(0, 12),
  step1Detail: '12 篇论文提取完成，共 24 条数据',
  bboxTotal: 24,
  bboxSuccess: 22,
  bboxFailed: 2,
  bboxFailures: [
    { key: '2016Natur.531..202S_5', reason: '字段在 PDF 第 3 页未找到对应文本位置' },
    { key: '2012MNRAS.427.1463Z_11', reason: 'bbox 超出页面边界' },
  ],
  step3Detail: '提取 5 张图片',
  step4Detail: '论文：12 个 source · 24 条 record',
  duration: '12.4s',
  summary: '提取 24 条记录 · 5 张图证',
  completeMessage: '总共提取了 20 个数据源，提取到 138 条数据，下面开始质检',
}

/* 卡 4-7 mock 数据（对齐 quality_pipeline：
 * agent 行 = workflow_history {agent, stage, status, duration, reason}
 * 修改轨迹 = data_trace {field, before, after, tool, reason, confidence}
 * 流转轮次 = workflow_state.loop_round；路由 = dispatch per_source_routes
 * 演示路径：A→B→C→B→D（规范化发现冲突 → 冲突消解 → 复检通过 → 交付） */
export function makeInitialStages() {
  return STAGE_DEFS.map((def) => ({
    ...def,
    status: 'waiting',
    duration: null,
    summary: '',
    expanded: false,
    output: null,
    substeps: def.id === 'understand'
      ? UNDERSTAND_SUBSTEPS.map((s) => ({ ...s, status: 'waiting' }))
      : def.id === 'extraction'
        ? makeExtractionSubsteps()
        : null,
    groups: def.id === 'retrieval' ? makeRetrievalGroups() : null,
    // M-22：初始 agents 统一 null——真实任务渲染完全依赖后端 agent 事件动态追加
    agents: null,
    flow: null,
    clarifications: [],
  }))
}

/* 澄清类型 → 快捷按钮（后端 interrupt 无候选列表，快捷按钮按 type 推导：
 * ask_properties 接受"全部"；final_confirm 接受 y/m/n）
 */
export const CLARIFICATION_QUICK_BUTTONS = {
  ask_properties: [{ label: '全部', value: '全部' }],
  final_confirm: [
    { label: '确认 (y)', value: 'y' },
    { label: '修改 (m)', value: 'm' },
    { label: '取消 (n)', value: 'n' },
  ],
}
