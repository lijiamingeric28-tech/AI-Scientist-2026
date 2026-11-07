import {
  categoryNames,
  clock,
  duration,
  stageNames,
  stateNames,
} from "./executionDisplay";
import { Icon } from "@/components/icons";

export function EventList({ items, focus, onEvent, onJob, onLinks }) {
  return (
    <ol className="execution-events">
      {items.map((event) => (
        <li
          key={event.seq}
          id={`execution-event-${event.seq}`}
          tabIndex={-1}
          className={focus === event.seq ? "is-focused" : ""}
        >
          <button
            className="execution-event-time"
            onClick={() => onEvent(event)}
            title="定位事件发生时间"
          >
            <span>{clock(event.at)}</span>
            <small>#{event.seq}</small>
          </button>
          <div>
            <strong>{event.label}</strong>
            {event.object_label && <span> · {event.object_label}</span>}
            <p>
              {stageNames[event.stage_id] || "阶段未记录"}
              {event.stage_basis === "visit_time" ? " · 访问执行区间" : ""}
              {event.status
                ? ` · ${stateNames[event.status] || event.status}`
                : ""}
            </p>
            {event.diagnostic && <p>{event.diagnostic.message}</p>}
            {event.review_result && (
              <p>
                {Object.values(event.review_result)
                  .map(
                    (value) =>
                      ({
                        applied: "核验结论已采纳",
                        passed: "交叉复检通过",
                        different_conditions: "按不同测量条件保留",
                        confirmed_conflict: "已确认多方数据存在分歧",
                        no_conflict: "未发现物理矛盾",
                        not_required: "无需人工复核",
                        completed: "调度完成",
                        succeeded: "调度完成",
                        pending: "排队等待",
                        kept: "已采纳保留",
                      })[value] || value,
                  )
                  .join(" · ")}
              </p>
            )}
            <div className="execution-inline-actions">
              {event.job_id && (
                <button onClick={() => onJob(event.job_id)}>
                  <Icon.Table style={{ width: 12, height: 12 }} />
                  查看作业
                </button>
              )}
              <ObjectLinks links={event.links} onLinks={onLinks} />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function ObjectLinks({ links = {}, onLinks }) {
  const labels = {
    measurement_id: "查看测量",
    source_id: "查看来源",
    work_id: "查看文献",
    review_id: "查看核验",
  };
  return Object.entries(links)
    .filter(([key]) => labels[key])
    .map(([key, value]) => (
      <button key={key} title={value} onClick={() => onLinks(key, value)}>
        {labels[key]}
      </button>
    ));
}

export function IssueList({ items, onEvent, onJob, onLinks, onTime }) {
  return (
    <div className="execution-issues">
      {items.map((issue) => {
        const isRecovered =
          issue.recovery === "recovered" || issue.recovery === "resolved";
        const isPartial = issue.recovery === "partial";

        return (
          <article
            className={`execution-issue-card recovery-${issue.recovery}`}
            key={issue.issue_id}
          >
            <div className="issue-card-header">
              <div className="issue-badges-row">
                {isRecovered ? (
                  <span className="issue-recovery-badge health-recovered">
                    <Icon.Check style={{ width: 11, height: 11 }} />
                    自动恢复闭环
                  </span>
                ) : isPartial ? (
                  <span className="issue-recovery-badge health-partial">
                    <Icon.Refresh style={{ width: 11, height: 11 }} />
                    容错降级完成
                  </span>
                ) : (
                  <span className="issue-recovery-badge health-unresolved">
                    <Icon.AlertCircle style={{ width: 11, height: 11 }} />
                    待人工介入
                  </span>
                )}
                <span className="issue-category-badge">
                  {issue.name || categoryNames[issue.category] || "学术数据服务"}
                </span>
                {issue.occurrences > 1 && (
                  <span className="issue-category-badge">
                    累计记入 {issue.occurrences} 次波动
                  </span>
                )}
              </div>
              <div className="issue-card-meta">
                <span>{stageNames[issue.stage_id] || "管线执行"}</span>
                <span>·</span>
                <span>{clock(issue.at, true)}</span>
              </div>
            </div>

            <h4 className="issue-card-title">{issue.message}</h4>

            {issue.impact && (
              <div className="issue-academic-box">
                <span className="issue-academic-box-label">容错与影响评估</span>
                <p style={{ margin: 0 }}>{issue.impact}</p>
              </div>
            )}

            <div className="execution-inline-actions">
              <button
                onClick={() =>
                  issue.seq != null
                    ? onEvent({ seq: issue.seq, at: issue.at })
                    : onTime({ at: issue.at })
                }
              >
                <Icon.Activity style={{ width: 12, height: 12 }} />
                定位发生时刻
              </button>
              {issue.job_id && (
                <button onClick={() => onJob(issue.job_id)}>
                  <Icon.Table style={{ width: 12, height: 12 }} />
                  查看关联作业
                </button>
              )}
              <ObjectLinks links={issue.links} onLinks={onLinks} />
            </div>

            {issue.service_attempts && (
              <ol className="execution-service-recovery" style={{ marginTop: 12 }}>
                {issue.service_attempts.map((attempt, i) => (
                  <li key={attempt.attempt_id}>
                    <strong>访问尝试 {i + 1}</strong>
                    <span>
                      {clock(attempt.start)} → {clock(attempt.end)}
                    </span>
                    <span>
                      {attempt.status === "completed"
                        ? "取得响应"
                        : attempt.status === "failed"
                          ? "节点连接超时 (已触发退避)"
                          : "此时点无结束回执"}
                    </span>
                    {attempt.status_code != null && (
                      <span className="job-hash-badge">HTTP {attempt.status_code}</span>
                    )}
                  </li>
                ))}
              </ol>
            )}

            {issue.actions?.length > 0 && (
              <EventList
                items={issue.actions}
                onEvent={onEvent}
                onJob={onJob}
                onLinks={onLinks}
              />
            )}

            {issue.code && (
              <details className="execution-diagnostic" style={{ marginTop: 12 }}>
                <summary>技术诊断与异常码</summary>
                <p style={{ margin: "6px 0" }}>内部诊断标识符：{issue.code}</p>
                <button
                  className="execution-text-action"
                  onClick={() =>
                    navigator.clipboard?.writeText(
                      `${clock(issue.at, true)} ${issue.message} ${issue.code}`,
                    )
                  }
                >
                  <Icon.Copy style={{ width: 12, height: 12 }} />
                  复制诊断报告
                </button>
              </details>
            )}
          </article>
        );
      })}
    </div>
  );
}

export function JobTable({ items, onJob }) {
  return (
    <div className="academic-job-table-vessel">
      <table className="academic-job-table">
        <thead>
          <tr>
            <th>管线作业</th>
            <th>所属阶段</th>
            <th>起止时间</th>
            <th>实际运行</th>
            <th>调度状态</th>
            <th>重试 / 等待</th>
            <th>前置依赖</th>
          </tr>
        </thead>
        <tbody>
          {items.map((job) => {
            const displayName =
              job.name === "业务作业"
                ? `${stageNames[job.stage_id] || "管线"}计算调度`
                : job.name;
            const isSuccess =
              job.status_label === "成功" ||
              job.status_label === "调度完成" ||
              job.status === "succeeded" ||
              job.status === "completed";
            const isRunning =
              job.status === "running" || job.status_label === "运行中";
            const isFailed =
              job.status === "failed" ||
              job.status === "error" ||
              job.status_label === "失败";

            return (
              <tr key={job.job_id}>
                <td>
                  <div>
                    <button
                      className="academic-job-btn"
                      onClick={() => onJob(job.job_id)}
                      title="点击展开作业全链路详情"
                    >
                      {displayName}
                    </button>
                  </div>
                  <span className="job-hash-badge" title={job.job_id}>
                    #{job.job_id.slice(0, 8)}
                  </span>
                </td>
                <td>
                  <span className="job-stage-pill">
                    {stageNames[job.stage_id] || "阶段"}
                  </span>
                </td>
                <td>
                  <div className="job-time-col">
                    <span>{clock(job.start)}</span>
                    <span className="time-sep">→</span>
                    <span>{clock(job.end)}</span>
                  </div>
                </td>
                <td>
                  <strong className="job-duration-val">
                    {duration(job.seconds)}
                  </strong>
                </td>
                <td>
                  {isSuccess ? (
                    <span className="job-status-pill status-succeeded">
                      <Icon.Check style={{ width: 10, height: 10 }} />
                      调度完成
                    </span>
                  ) : isRunning ? (
                    <span className="job-status-pill status-running">
                      <Icon.Refresh style={{ width: 10, height: 10 }} />
                      正在执行
                    </span>
                  ) : isFailed ? (
                    <span className="job-status-pill status-failed">
                      <Icon.AlertCircle style={{ width: 10, height: 10 }} />
                      执行波动
                    </span>
                  ) : (
                    <span className="job-status-pill status-waiting">
                      <Icon.Clock style={{ width: 10, height: 10 }} />
                      {job.status_label || stateNames[job.status] || "排队中"}
                    </span>
                  )}
                </td>
                <td style={{ color: "var(--ex-muted)" }}>
                  {job.retry_count > 0 ? (
                    <span style={{ color: "#8c6016", fontWeight: 550 }}>
                      {job.retry_count} 重试
                    </span>
                  ) : (
                    "0 重试"
                  )}{" "}
                  ·{" "}
                  {job.wait_count > 0 ? (
                    <span>{job.wait_count} 等待</span>
                  ) : (
                    "直接调度"
                  )}
                </td>
                <td>
                  <span style={{ color: "#314b3c" }}>
                    {job.dependency_count > 0
                      ? `${job.dependency_count} 项依赖`
                      : "首节点"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function JobDetail({ job, onJob, onEvent, onLinks }) {
  const isSuccess =
    job.status_label === "成功" ||
    job.status_label === "调度完成" ||
    job.status === "succeeded" ||
    job.status === "completed";

  return (
    <section className="execution-job-detail">
      <div className="execution-section-heading">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h3>{job.name}</h3>
          {isSuccess ? (
            <span className="job-status-pill status-succeeded">
              <Icon.Check style={{ width: 10, height: 10 }} />
              调度完成
            </span>
          ) : (
            <span className="job-status-pill status-waiting">
              {job.status_label || stateNames[job.status] || "就绪"}
            </span>
          )}
        </div>
        <span className="job-hash-badge">完整 ID: {job.job_id}</span>
      </div>

      <dl className="execution-fields">
        <div>
          <dt>所属阶段</dt>
          <dd>{stageNames[job.stage_id]}</dd>
        </div>
        <div>
          <dt>起止时间</dt>
          <dd>
            {clock(job.start, true)} → {clock(job.end, true)}
          </dd>
        </div>
        <div>
          <dt>实际运行净耗时</dt>
          <dd>{duration(job.seconds)}</dd>
        </div>
        <div>
          <dt>执行区段 / 重试 / 调度等待</dt>
          <dd>
            {job.run_count} 区段 · {job.retry_count} 次重试 · {job.wait_count} 次等待
          </dd>
        </div>
      </dl>

      <div className="execution-inline-actions">
        <ObjectLinks links={job.links} onLinks={onLinks} />
      </div>

      <h4>实际运行区段流</h4>
      <ol className="execution-runs">
        {job.runs.map((run, i) => (
          <li key={run.seq}>
            <strong>区段 #{i + 1}</strong>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {clock(run.start)} → {clock(run.end)}
            </span>
            <strong style={{ color: "#24583b" }}>{duration(run.seconds)}</strong>
            <span className="job-stage-pill">{stateNames[run.status] || run.status}</span>
            <button
              className="execution-text-action"
              onClick={() => onEvent({ seq: run.seq, at: run.start })}
            >
              <Icon.Activity style={{ width: 11, height: 11 }} />
              定位对应事件 #{run.seq}
            </button>
          </li>
        ))}
      </ol>
      {!job.runs.length && <p>没有记录实际开始运行。</p>}

      <h4>拓扑依赖关系</h4>
      <div
        className="execution-dependencies"
        aria-label="所选作业的一层上下游依赖"
      >
        <div>
          <h5>上游前置输入</h5>
          {!job.dependencies.length && <p style={{ fontSize: 13, color: "var(--ex-muted)" }}>首节点（无前置依赖）</p>}
          {job.dependencies.map((parent) => (
            <div key={parent.job_id} style={{ marginBottom: 8 }}>
              <button
                className="academic-job-btn"
                onClick={() => onJob(parent.job_id)}
              >
                {parent.name}
              </button>
              <span className="job-status-pill status-succeeded" style={{ marginLeft: 6 }}>
                {stateNames[parent.status] || "完成"}
              </span>
            </div>
          ))}
        </div>
        <div className="execution-dependency-center">
          {job.dependencies.length > 0 && (
            <svg viewBox="0 0 30 20" aria-hidden="true">
              <path d="M2 10h24m-6-6 6 6-6 6" />
            </svg>
          )}
          <strong>{job.name}</strong>
          {job.dependents.length > 0 && (
            <svg viewBox="0 0 30 20" aria-hidden="true">
              <path d="M2 10h24m-6-6 6 6-6 6" />
            </svg>
          )}
        </div>
        <div>
          <h5>下游消费作业</h5>
          {!job.dependents.length && <p style={{ fontSize: 13, color: "var(--ex-muted)" }}>终点任务（无下游依赖）</p>}
          {job.dependents.map((child) => (
            <div key={child.job_id} style={{ marginBottom: 8 }}>
              <button
                className="academic-job-btn"
                onClick={() => onJob(child.job_id)}
              >
                {child.name}
              </button>
              <span className="job-status-pill status-succeeded" style={{ marginLeft: 6 }}>
                {stateNames[child.status] || "完成"}
              </span>
            </div>
          ))}
        </div>
      </div>

      <details className="execution-diagnostic" style={{ marginTop: 16 }}>
        <summary>学术模型调用与诊断（{job.model_attempts.length} 次记录）</summary>
        {!job.model_attempts.length && <p>此作业未保存独立模型调用日志。</p>}
        {job.model_attempts.map((attempt, i) => (
          <article key={attempt.attempt_id} style={{ padding: "8px 0", borderBottom: "1px solid #eef3ef" }}>
            <strong style={{ color: "#24583b" }}>
              调用 #{i + 1} · {attempt.model || "默认天体物理推理模型"}
            </strong>
            <p style={{ margin: "4px 0" }}>
              {clock(attempt.start)} → {clock(attempt.end)} ·{" "}
              {attempt.status === "settled"
                ? "调用已结算"
                : attempt.status === "pending"
                  ? "尚无结束回执"
                  : attempt.status}
            </p>
            {attempt.error && <p style={{ color: "#b3362a" }}>{attempt.error.message}</p>}
            {attempt.provider_status != null && (
              <p>响应状态码：{attempt.provider_status}</p>
            )}
            {attempt.rate_wait_seconds != null && (
              <p>已记录限流平抑等待：{duration(attempt.rate_wait_seconds)}</p>
            )}
          </article>
        ))}
      </details>

      <details open style={{ marginTop: 16 }}>
        <summary>关联执行事件（{job.events.length}）</summary>
        <EventList
          items={job.events}
          onEvent={onEvent}
          onJob={onJob}
          onLinks={onLinks}
        />
      </details>
    </section>
  );
}
