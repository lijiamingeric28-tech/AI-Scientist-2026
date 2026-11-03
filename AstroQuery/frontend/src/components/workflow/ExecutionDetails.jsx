import {
  categoryNames,
  clock,
  duration,
  stageNames,
  stateNames,
} from "./executionDisplay";

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
          >
            <span>{clock(event.at)}</span>
            <small>#{event.seq}</small>
          </button>
          <div>
            <strong>{event.label}</strong>
            {event.object_label && <span> · {event.object_label}</span>}
            <p>
              {stageNames[event.stage_id] || "阶段未记录"}
              {event.stage_basis === "visit_time" ? " · 此访问期间" : ""}
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
                        applied: "判断已应用",
                        passed: "复检通过",
                        different_conditions: "按不同测量条件保留",
                        confirmed_conflict: "确认存在矛盾",
                        no_conflict: "未确认矛盾",
                        not_required: "无需复检",
                        completed: "已完成",
                        succeeded: "成功",
                        pending: "等待处理",
                        kept: "保留",
                      })[value] || value,
                  )
                  .join(" · ")}
              </p>
            )}
            <div className="execution-inline-actions">
              {event.job_id && (
                <button onClick={() => onJob(event.job_id)}>查看作业</button>
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
    work_id: "查看论文",
    review_id: "查看审核",
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
      {items.map((issue) => (
        <details
          className={`execution-problem recovery-${issue.recovery}`}
          key={issue.issue_id}
        >
          <summary>
            <span className="execution-state-label">
              {stateNames[issue.recovery] || "恢复情况未记录"}
            </span>
            <strong>{issue.message}</strong>
            <span>{issue.name || categoryNames[issue.category]}</span>
          </summary>
          <p>
            {stageNames[issue.stage_id]} · {clock(issue.at, true)}
            {issue.occurrences ? ` · ${issue.occurrences} 次异常事件` : ""}
          </p>
          {issue.impact && <p>{issue.impact}</p>}
          <div className="execution-inline-actions">
            <button
              onClick={() =>
                issue.seq != null
                  ? onEvent({ seq: issue.seq, at: issue.at })
                  : onTime({ at: issue.at })
              }
            >
              定位发生时刻
            </button>
            {issue.job_id && (
              <button onClick={() => onJob(issue.job_id)}>查看关联作业</button>
            )}
            <ObjectLinks links={issue.links} onLinks={onLinks} />
          </div>
          {issue.service_attempts && (
            <ol className="execution-service-recovery">
              {issue.service_attempts.map((attempt, i) => (
                <li key={attempt.attempt_id}>
                  <strong>访问 {i + 1}</strong>
                  <span>
                    {clock(attempt.start)} → {clock(attempt.end)}
                  </span>
                  <span>
                    {attempt.status === "completed"
                      ? "取得响应"
                      : attempt.status === "failed"
                        ? "访问失败"
                        : "此时点无结束回执"}
                  </span>
                  {attempt.status_code != null && (
                    <span>HTTP {attempt.status_code}</span>
                  )}
                </li>
              ))}
            </ol>
          )}
          <EventList
            items={issue.actions}
            onEvent={onEvent}
            onJob={onJob}
            onLinks={onLinks}
          />
          {issue.code && (
            <details className="execution-diagnostic">
              <summary>技术诊断</summary>
              <p>错误类别 {issue.code}</p>
              <button
                onClick={() =>
                  navigator.clipboard?.writeText(
                    `${clock(issue.at, true)} ${issue.message} ${issue.code}`,
                  )
                }
              >
                复制公开诊断
              </button>
            </details>
          )}
        </details>
      ))}
    </div>
  );
}

export function JobTable({ items, onJob }) {
  return (
    <div className="execution-table-scroll">
      <table className="execution-table">
        <thead>
          <tr>
            <th>作业</th>
            <th>阶段</th>
            <th>起止时间</th>
            <th>实际运行</th>
            <th>最终状态</th>
            <th>重试 / 等待</th>
            <th>依赖</th>
          </tr>
        </thead>
        <tbody>
          {items.map((job) => (
            <tr key={job.job_id}>
              <td>
                <button onClick={() => onJob(job.job_id)}>{job.name}</button>
                <small>{job.job_id.slice(0, 12)}</small>
              </td>
              <td>{stageNames[job.stage_id]}</td>
              <td>
                {clock(job.start)}
                <small>至 {clock(job.end)}</small>
              </td>
              <td>{duration(job.seconds)}</td>
              <td>{job.status_label}</td>
              <td>
                {job.retry_count} / {job.wait_count}
              </td>
              <td>{job.dependency_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobDetail({ job, onJob, onEvent, onLinks }) {
  return (
    <section className="execution-job-detail">
      <div className="execution-section-heading">
        <h3>{job.name}</h3>
        <span>{job.status_label}</span>
      </div>
      <dl className="execution-fields">
        <div>
          <dt>所属阶段</dt>
          <dd>{stageNames[job.stage_id]}</dd>
        </div>
        <div>
          <dt>开始 / 结束</dt>
          <dd>
            {clock(job.start, true)} / {clock(job.end, true)}
          </dd>
        </div>
        <div>
          <dt>实际运行</dt>
          <dd>{duration(job.seconds)}</dd>
        </div>
        <div>
          <dt>运行区段 / 重试 / 资源等待</dt>
          <dd>
            {job.run_count} / {job.retry_count} / {job.wait_count}
          </dd>
        </div>
      </dl>
      <div className="execution-inline-actions">
        <ObjectLinks links={job.links} onLinks={onLinks} />
      </div>
      <h4>实际运行区段</h4>
      <ol className="execution-runs">
        {job.runs.map((run, i) => (
          <li key={run.seq}>
            <strong>第 {i + 1} 段</strong>
            <span>
              {clock(run.start)} → {clock(run.end)}
            </span>
            <span>{duration(run.seconds)}</span>
            <span>{stateNames[run.status] || run.status}</span>
            <button onClick={() => onEvent({ seq: run.seq, at: run.start })}>
              定位事件 #{run.seq}
            </button>
          </li>
        ))}
      </ol>
      {!job.runs.length && <p>没有记录实际开始运行。</p>}
      <h4>依赖关系</h4>
      <div
        className="execution-dependencies"
        aria-label="所选作业的一层上下游依赖"
      >
        <div>
          <h5>上游前置</h5>
          {!job.dependencies.length && <p>未保存前置依赖</p>}
          {job.dependencies.map((parent) => (
            <div key={parent.job_id}>
              <button onClick={() => onJob(parent.job_id)}>
                {parent.name}
                <small>{stateNames[parent.status]}</small>
              </button>
              <details>
                <summary>依赖解析</summary>
                <p>
                  {parent.resolution === "closed_without_result"
                    ? "已记录无结果释放回执"
                    : parent.resolution === "required"
                      ? "前置作业成功后运行"
                      : "解析状态未记录"}
                </p>
              </details>
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
          <h5>下游作业</h5>
          {!job.dependents.length && <p>未保存下游依赖</p>}
          {job.dependents.map((child) => (
            <button key={child.job_id} onClick={() => onJob(child.job_id)}>
              {child.name}
              <small>{stateNames[child.status]}</small>
            </button>
          ))}
        </div>
      </div>
      <details className="execution-diagnostic">
        <summary>模型尝试与服务诊断（{job.model_attempts.length}）</summary>
        {!job.model_attempts.length && <p>此作业未保存可展示的模型调用。</p>}
        {job.model_attempts.map((attempt, i) => (
          <article key={attempt.attempt_id}>
            <strong>
              模型调用 {i + 1} · {attempt.model || "型号未记录"}
            </strong>
            <p>
              {clock(attempt.start)} → {clock(attempt.end)} ·{" "}
              {attempt.status === "settled"
                ? "已结算"
                : attempt.status === "pending"
                  ? "当时尚无结束回执"
                  : attempt.status}
            </p>
            {attempt.error && <p>{attempt.error.message}</p>}
            {attempt.provider_status != null && (
              <p>响应状态 {attempt.provider_status}</p>
            )}
            {attempt.rate_wait_seconds != null && (
              <p>已记录限流等待 {duration(attempt.rate_wait_seconds)}</p>
            )}
          </article>
        ))}
        <p>网络访问的任务级记录可在“异常与事件”的服务诊断中查看。</p>
      </details>
      <details open>
        <summary>关联事件（{job.events.length}）</summary>
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
