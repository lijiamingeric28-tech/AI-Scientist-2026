/* 重复收录索引（2026-09-06，纯前端派生；后端/接口零改动）
 * 数据源：GET /quality → quality_report.report_state.conflict.verification.duplicate_groups[]
 *（缺失/空时回退 resolution_report.duplicate_groups；两处内容经样例库实测一致）。
 * 重复组 = 同 entity+field+value 的多条记录。V3.0 原则「全量保留标注」：组内记录从不删除，
 * 只标注差异/重复，供用户复核。
 *
 * 显示语义（用户决策）：每组选 1 条代表记录，其余成员在值单元格标「疑似重复」；
 * 代表选取规则（确定性、可解释）：
 *   ① extraction_method === 'database_query'（数据库主目录优先）
 *   ② extraction_confidence 最高（并列取前）
 *   ③ record_id 字典序最小
 *
 * buildDupIndex 是表格（ResultTabs 徽标）与详情弹窗（RecordDetail 章节）的单一数据源：
 * 两者共用同一份组/代表/文案，避免口径漂移。
 */

export const DUP_REASON_TEXT = {
  db_source: '数据库查询来源优先',
  top_confidence: '提取置信度最高',
  record_id: '记录 ID 最小',
}

export const DUP_RULE_TEXT =
  '代表记录选取规则：数据库查询来源优先 → 提取置信度最高 → 记录 ID 最小；仅非代表成员标「疑似重复」。'

export const DUP_PRINCIPLE_TEXT =
  '重复处理遵循「全量保留标注」：组内所有重复记录都保留在最终结果中，不做删除，仅将非代表成员标为疑似重复，供复核后按需剔除。'

const DB_METHOD = 'database_query'

function groupKey(g) {
  return `${g.entity_type ?? ''}|${g.entity_name ?? ''}|${g.field_name ?? ''}|${String(g.field_value ?? '')}`
}

/* 从现存成员中按规则选代表；返回 { recordId, sourceId, extractionMethod, reason } | null */
function pickRepresentative(liveMembers) {
  // ① 数据库查询来源优先
  for (const m of liveMembers) {
    if (m.extractionMethod === DB_METHOD) {
      return { recordId: m.recordId, sourceId: m.sourceId, extractionMethod: m.extractionMethod, reason: 'db_source' }
    }
  }
  // ② 提取置信度最高（仅数字参与；并列取前）
  let best = null
  let bestConf = -Infinity
  for (const m of liveMembers) {
    const c = typeof m.extractionConfidence === 'number' ? m.extractionConfidence : -Infinity
    if (c > bestConf) { bestConf = c; best = m }
  }
  if (best) {
    return { recordId: best.recordId, sourceId: best.sourceId, extractionMethod: best.extractionMethod, reason: 'top_confidence' }
  }
  // ③ 记录 ID 最小（全无置信度时兜底）
  let min = liveMembers[0]
  for (const m of liveMembers) {
    if (m.recordId < min.recordId) min = m
  }
  return { recordId: min.recordId, sourceId: min.sourceId, extractionMethod: min.extractionMethod, reason: 'record_id' }
}

/**
 * @param {Array|null} records       GET /records 的行数组（需含 record_id/source_id/extraction_method/…）
 * @param {object|null} qualityReport GET /quality 返回的 quality_report
 * @returns {{ groups: object[], byRecordId: Object<string, {group, isRepresentative}> }}
 *   groups[]    —— 有效重复组（现存成员 ≥2 条），组内含 members/代表等信息
 *   byRecordId  —— record_id → { group, isRepresentative }；只收录现存成员行
 *   无质量报告 / 无 conflict / 无重复组时返回空索引 { groups: [], byRecordId: {} }。
 */
export function buildDupIndex(records, qualityReport) {
  const empty = { groups: [], byRecordId: {} }
  if (!Array.isArray(records)) return empty
  const conflict = qualityReport?.report_state?.conflict || null
  if (!conflict) return empty

  let rawGroups = conflict.verification?.duplicate_groups
  if (!Array.isArray(rawGroups) || rawGroups.length === 0) {
    rawGroups = conflict.resolution_report?.duplicate_groups
  }
  if (!Array.isArray(rawGroups) || rawGroups.length === 0) return empty

  // 现存行索引（用户删除过的行不再参与 join，但组的原始规模仍保留用于展示）
  const live = new Map()
  for (const r of records) {
    if (r && typeof r.record_id === 'string' && r.record_id) live.set(r.record_id, r)
  }

  const seen = new Set()
  const groups = []
  for (const g of rawGroups) {
    // 防御性归一：成员 id 列表必须 ≥2 个非空字符串；同键组只取第一个
    if (!g || !Array.isArray(g.record_ids) || g.record_ids.length < 2) continue
    const key = groupKey(g)
    if (!key || seen.has(key)) continue
    seen.add(key)

    const recordIds = []
    const members = []
    for (const id of g.record_ids) {
      if (typeof id !== 'string' || !id) continue
      recordIds.push(id)
      const rec = live.get(id) || null
      members.push({
        recordId: id,
        sourceId: rec?.source_id ?? null,
        extractionMethod: rec?.extraction_method ?? null,
        extractionConfidence: typeof rec?.extraction_confidence === 'number' ? rec.extraction_confidence : null,
        isLive: !!rec,
        isRepresentative: false,
      })
    }
    const liveMembers = members.filter((m) => m.isLive)
    // 组已散（现存成员不足 2 条）→ 整组溶解，不留孤立的「疑似重复」
    if (liveMembers.length < 2) continue

    const rep = pickRepresentative(liveMembers)
    for (const m of members) {
      if (m.recordId === rep.recordId) m.isRepresentative = true
    }

    const rawSourceIds = Array.isArray(g.source_ids) ? g.source_ids : []
    groups.push({
      key,
      entityType: g.entity_type ?? '',
      entityName: g.entity_name ?? '',
      fieldName: g.field_name ?? '',
      fieldValue: String(g.field_value ?? ''),
      sourceCount: typeof g.source_count === 'number' ? g.source_count : rawSourceIds.length,
      sourceIds: rawSourceIds,
      recordIds,                        // 组原始记录 id 全量（含已删除行，供「共 N 条」口径）
      members,                          // 原序全量成员（含 isLive/isRepresentative 标记）
      liveCount: liveMembers.length,
      rep,
    })
  }
  groups.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))

  const byRecordId = {}
  for (const group of groups) {
    for (const m of group.members) {
      if (!m.isLive) continue
      if (byRecordId[m.recordId]) continue // 同一行同时出现在两个组（后端不应产生）：取先者
      byRecordId[m.recordId] = { group, isRepresentative: m.isRepresentative }
    }
  }
  return { groups, byRecordId }
}
