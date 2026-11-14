import { limitedValueText } from '@/lib/valueDisplay'
import { stateText } from '@/lib/researchDisplay'
import { artifactUrl } from '@/services/api'
import { Icon } from '@/components/icons'

// 辅助解析长英文字段推理说明，提取关键物理要素
function parseRationaleTags(text) {
  if (!text || typeof text !== 'string') return []
  const tags = []
  if (/SN\s*2014J/i.test(text)) tags.push({ label: '物理客体', val: 'SN 2014J' })
  if (/extinction\s*\(Av\)|host extinction/i.test(text)) tags.push({ label: '观测物理量', val: 'Av 视线消光' })
  if (/Phillips/i.test(text)) tags.push({ label: '消光律换算', val: 'Phillips (2013) 关系' })
  if (/Goobar/i.test(text)) tags.push({ label: '估算来源', val: 'Goobar (2014)' })
  if (/not_restricted/i.test(text)) tags.push({ label: '估计量方法', val: '通用估计量准入' })
  return tags
}

export default function ProcessingTimeline({
  entries = [],
  records = [],
  onOpenRecord,
  compact = false,
}) {
  if (!entries.length) {
    return <div className="trace-empty-box">该筛选条件下无相关处理记录或历史已完成全量归档。</div>
  }

  return (
    <ol className="research-timeline" aria-label="科学处理溯源时间线">
      {entries.map((entry) => {
        const before = entry.before
        const original = before?.raw ?? before?.raw_value
        const rationaleTags = parseRationaleTags(entry.reason)
        const isNoChange = entry.status === 'no_change' || entry.status === 'not_run'
        const isNotApplicable = entry.status === 'not_applicable'

        return (
          <li key={entry.id} data-activity-kind={entry.kind} className="timeline-node-card">
            {/* 时间线节点头部 */}
            <div className="research-timeline-heading">
              <span className="timeline-op-badge">{entry.operation || '证据核实'}</span>
              <span className={`timeline-status-badge ${isNotApplicable ? 'status-na' : isNoChange ? 'status-nochange' : 'status-ok'}`}>
                {isNotApplicable
                  ? '免二次核验 (权威基准)'
                  : isNoChange
                    ? '确认采纳原报'
                    : stateText(entry.status)}
              </span>
              {entry.simulation && <span className="timeline-sim-tag">模拟推演审核</span>}
              {entry.at && (
                <time className="timeline-time-text" dateTime={entry.at}>
                  {new Date(entry.at).toLocaleString('zh-CN', { hour12: false })}
                </time>
              )}
            </div>

            {/* 数值转换对比舱 */}
            {original != null && (
              <div className="value-change-vessel">
                <div className="value-col original">
                  <div className="value-label">原报数值</div>
                  <div className="value-number">{original} {before.unit || ''}</div>
                </div>

                <div className="value-arrow-col">
                  <span className="value-flow-pill">
                    {entry.after?.value ? '规范化处理' : '确认采纳原报'}
                  </span>
                </div>

                <div className="value-col target">
                  <div className="value-label">交付物理量</div>
                  <div className="value-number highlight">
                    {entry.after?.value
                      ? `${limitedValueText(entry.after.value)} ${entry.after.coordinate_units?.target || before.unit || ''}`
                      : `${original} ${before.unit || ''}`}
                  </div>
                </div>
              </div>
            )}

            {entry.kind === 'reextraction' && (
              <p className="reextract-note">
                {entry.candidate_count != null
                  ? `${entry.candidate_count} 个后继观测候选`
                  : '后继数量已核对'}{' '}
                · {entry.measurement_ids.length} 条进入本修订交付
              </p>
            )}

            {/* 结构化科学推理与依据卡片 */}
            {entry.reason && (
              <div className="trace-rationale-vessel">
                {rationaleTags.length > 0 && (
                  <div className="trace-rationale-tags">
                    {rationaleTags.map((t, idx) => (
                      <span className="trace-tag-chip" key={idx}>
                        <strong>{t.label}:</strong> {t.val}
                      </span>
                    ))}
                  </div>
                )}
                <div className="trace-rationale-text">
                  {entry.reason}
                </div>
              </div>
            )}

            {/* 原文定位依据链接 */}
            {entry.origin_locator?.artifact_id && entry.origin_locator?.task_id && (
              <div className="trace-origin-link-wrap">
                <a
                  className="trace-origin-link"
                  href={
                    artifactUrl(entry.origin_locator.task_id, entry.origin_locator.artifact_id) +
                    (entry.origin_locator.page ? '#page=' + entry.origin_locator.page : '')
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  <Icon.FileText style={{ width: 13, height: 13, color: 'var(--accent)' }} />
                  <span>
                    {entry.origin_locator.page
                      ? '核验原文依据 · 文献第 ' + entry.origin_locator.page + ' 页 (PDF p.' + entry.origin_locator.page + ')'
                      : '打开核验原件文献'}
                  </span>
                  <Icon.ExternalLink style={{ width: 12, height: 12 }} />
                </a>
              </div>
            )}

            {/* 关联测量记录查看 */}
            {!compact && onOpenRecord && entry.measurement_ids?.length > 0 && (
              <div className="trace-record-links-row">
                <span className="trace-record-lead">关联物理记录:</span>
                {entry.measurement_ids.map((id) => {
                  const record = records.find((r) => r.record_id === id)
                  return (
                    <button
                      type="button"
                      className="trace-record-pill active-press"
                      key={id}
                      onClick={() => onOpenRecord(id)}
                    >
                      <span>{record ? `${record.field_value} ${record.field_unit || ''}` : '关联记录'}</span>
                      <Icon.ArrowRight style={{ width: 11, height: 11 }} />
                    </button>
                  )
                })}
              </div>
            )}

            {entry.kind === 'delivery' && (
              <div className="trace-delivery-tag">
                交付修订版本 {entry.delivery_revision}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
