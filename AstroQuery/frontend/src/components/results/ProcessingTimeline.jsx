import { limitedValueText } from '@/lib/valueDisplay'
import { stateText } from '@/lib/researchDisplay'
import { artifactUrl } from '@/services/api'

export default function ProcessingTimeline({
  entries = [],
  records = [],
  onOpenRecord,
  compact = false,
}) {
  if (!entries.length) return <p className="hint">历史版本未记录这部分处理信息。</p>
  return (
    <ol className="research-timeline" aria-label="处理时间线">
      {entries.map((entry) => {
        const before = entry.before
        const original = before?.raw ?? before?.raw_value
        return (
          <li key={entry.id} data-activity-kind={entry.kind}>
            <div className="research-timeline-heading">
              <strong>{entry.operation}</strong>
              <span className="research-status">{stateText(entry.status)}</span>
              {entry.simulation && <span>当时的模拟审核</span>}
            </div>
            {entry.at && (
              <time dateTime={entry.at}>
                {new Date(entry.at).toLocaleString('zh-CN', { hour12: false })}
              </time>
            )}
            {original != null && (
              <div className="value-change">
                <span>
                  <small>原报</small>
                  {original} {before.unit}
                </span>
                {entry.after?.value && (
                  <span>
                    <small>当前表示</small>
                    {limitedValueText(entry.after.value)} {entry.after.coordinate_units?.target}
                  </span>
                )}
              </div>
            )}
            {entry.kind === 'reextraction' && (
              <p>
                {entry.candidate_count != null
                  ? `${entry.candidate_count} 个后继候选`
                  : '后继数量未记录'}{' '}
                · {entry.measurement_ids.length} 条进入本修订
              </p>
            )}
            {entry.reason && <p className="research-explanation">{entry.reason}</p>}
            {entry.origin_locator?.artifact_id && entry.origin_locator?.task_id && (
              <a
                className="text-link"
                href={
                  artifactUrl(entry.origin_locator.task_id, entry.origin_locator.artifact_id) +
                  (entry.origin_locator.page ? '#page=' + entry.origin_locator.page : '')
                }
                target="_blank"
                rel="noreferrer"
              >
                {entry.origin_locator.page
                  ? '核验原文 · PDF 物理第 ' + entry.origin_locator.page + ' 页'
                  : '打开核验原件'}
              </a>
            )}
            {entry.outcome && <p>{stateText(entry.outcome)}</p>}
            {entry.postcheck && <p>{stateText(entry.postcheck)}</p>}
            {entry.question && (
              <details>
                <summary>原问题与选项</summary>
                <p>{entry.question.question || entry.question.title}</p>
                {(entry.question.choices || []).map((choice, i) => (
                  <div key={i}>
                    <strong>{choice.label}</strong>
                    <p>{choice.impact}</p>
                  </div>
                ))}
              </details>
            )}
            {(entry.validation ||
              entry.field_diff?.length ||
              entry.checks?.length > 0 ||
              entry.conclusions?.length > 0) && (
              <details>
                <summary>处理依据与验证回执</summary>
                {entry.validation && <p>验证结果 · {stateText(entry.validation)}</p>}
                {entry.conclusions?.map((s, i) => (
                  <p key={i}>{stateText(s)}</p>
                ))}
                {entry.checks?.map((check, i) => (
                  <p key={i}>
                    {check.target === 'main_value' ? '主值' : '相应分量'} ·{' '}
                    {stateText(check.status)}
                  </p>
                ))}
                {entry.before_ref && <p>原版本 {entry.before_ref.version ?? '未记录'}</p>}
                {entry.after_ref && <p>处理版本 {entry.after_ref.version ?? '未记录'}</p>}
                {entry.field_diff?.length > 0 && (
                  <p>已保存 {entry.field_diff.length} 项结构变化及其验证依据</p>
                )}
              </details>
            )}
            {!compact && onOpenRecord && entry.measurement_ids?.length > 0 && (
              <div className="research-links">
                {entry.measurement_ids.map((id) => {
                  const record = records.find((r) => r.record_id === id)
                  return (
                    <button className="text-link" key={id} onClick={() => onOpenRecord(id)}>
                      {record ? `${record.field_value} ${record.field_unit || ''}` : '查看关联记录'}{' '}
                      · 原件
                    </button>
                  )
                })}
              </div>
            )}
            {entry.kind === 'delivery' && <p>交付修订 {entry.delivery_revision}</p>}
          </li>
        )
      })}
    </ol>
  )
}
