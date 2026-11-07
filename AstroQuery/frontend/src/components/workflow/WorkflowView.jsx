import { useEffect, useMemo, useRef, useState } from "react";
import { useSlidingPanes } from "@/hooks/useSlidingPanes";
import { Icon } from "@/components/icons";
import { getExecution, executionReportUrl } from "@/services/api";
import { useRememberedState, useScrollMemory } from "@/hooks/useViewMemory";
import ExecutionTimeline from "./ExecutionTimeline";
import { EventList, IssueList, JobTable, JobDetail } from "./ExecutionDetails";
import {
  categoryNames,
  clock,
  duration,
  millis,
  stageNames,
  stateNames,
} from "./executionDisplay";
import "./execution.css";

function useExecution(taskId, query, active, version) {
  const key = JSON.stringify([taskId, query]),
    [result, setResult] = useState({ key: null, data: null, error: null });
  useEffect(() => {
    if (!taskId || !active) return;
    const controller = new AbortController();
    getExecution(taskId, query, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, data, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setResult({ key, data: null, error: error.message });
      });
    return () => controller.abort();
  }, [key, active, version]);
  return result.key === key ? result : { data: null, error: null };
}

function Pager({ data, onPage }) {
  if (!data || data.total <= data.limit) return null;
  return (
    <nav className="execution-pagination" aria-label="执行明细分页">
      <button
        disabled={data.offset === 0}
        onClick={() => onPage(Math.max(0, data.offset - data.limit))}
      >
        上一页
      </button>
      <span>
        {data.offset + 1}–
        {Math.min(data.total, data.offset + data.items.length)} / {data.total}{" "}
        项
      </span>
      <button
        disabled={data.offset + data.limit >= data.total}
        onClick={() => onPage(data.offset + data.limit)}
      >
        下一页
      </button>
    </nav>
  );
}

export default function WorkflowView(props) {
  if (!props.task)
    return <div className="empty-state">选择查询后查看执行明细。</div>;
  return (
    <ExecutionWorkspace
      key={`${props.task.task_id}:${Boolean(props.pipeline.playback)}`}
      {...props}
    />
  );
}

function ExecutionWorkspace({
  memory = {},
  active = true,
  task,
  pipeline,
  onShowStageInChat,
  onGoChat,
  onFocusInChat,
  onOpenData,
  request,
}) {
  const [tab, setTab] = useRememberedState(memory, "executionTab", "overview");
  const [range, setRange] = useRememberedState(memory, "executionRange", null);
  const [following, setFollowing] = useRememberedState(
    memory,
    "executionFollowing",
    true,
  );
  const [pinned, setPinned] = useRememberedState(
    memory,
    "executionPinned",
    null,
  );
  const [stage, setStage] = useRememberedState(memory, "executionStage", "");
  const [search, setSearch] = useRememberedState(memory, "executionSearch", "");
  const [eventCategory, setEventCategory] = useRememberedState(
    memory,
    "executionEventCategory",
    "",
  );
  const [issueCategory, setIssueCategory] = useRememberedState(
    memory,
    "executionIssueCategory",
    "",
  );
  const [jobStatus, setJobStatus] = useRememberedState(
    memory,
    "executionJobStatus",
    "",
  );
  const [sort, setSort] = useRememberedState(memory, "executionSort", "time");
  const [eventOffset, setEventOffset] = useRememberedState(
    memory,
    "executionEventOffset",
    0,
  );
  const [issueOffset, setIssueOffset] = useRememberedState(
    memory,
    "executionIssueOffset",
    0,
  );
  const [jobOffset, setJobOffset] = useRememberedState(
    memory,
    "executionJobOffset",
    0,
  );
  const [selectedVisit, setSelectedVisit] = useRememberedState(
    memory,
    "executionVisit",
    null,
  );

  const contentRef = useRef(null);
  const navRef = useRef(null);
  const tabRefs = useRef({});
  const tabOrder = useMemo(() => ["overview", "events", "jobs"], []);
  const panes = useSlidingPanes(contentRef, tab, tabOrder, { active });
  const [sliderStyle, setSliderStyle] = useState({ left: 0, width: 0, opacity: 0 });

  useEffect(() => {
    const updateSlider = () => {
      const activeEl = tabRefs.current[tab];
      const navEl = navRef.current;
      if (activeEl && navEl) {
        setSliderStyle({
          left: activeEl.offsetLeft,
          width: activeEl.offsetWidth,
          opacity: 1,
        });
      }
    };
    updateSlider();
    const rafId = requestAnimationFrame(updateSlider);
    let observer;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(updateSlider);
      if (navRef.current) observer.observe(navRef.current);
      Object.values(tabRefs.current).forEach((btn) => {
        if (btn) observer.observe(btn);
      });
    }
    return () => {
      cancelAnimationFrame(rafId);
      if (observer) observer.disconnect();
    };
  }, [tab]);
  const [selectedJob, setSelectedJob] = useRememberedState(
    memory,
    "executionJob",
    null,
  );
  const [jobStack, setJobStack] = useState([]),
    [expanded, setExpanded] = useState(null);
  const [focusSeq, setFocusSeq] = useState(null),
    [version, setVersion] = useState(0);
  const [ranking, setRanking] = useState("duration"),
    [stageFilter, setStageFilter] = useState("all");
  const [serviceOffset, setServiceOffset] = useState(0);
  const [download, setDownload] = useState(""),
    [downloadError, setDownloadError] = useState("");
  const [navigationNotice, setNavigationNotice] = useState("");
  const eventRef = useRef(null),
    detailRef = useRef(null),
    requestSeen = useRef(null);
  const listReturn = useRef(null);
  const cursor = pipeline.readOnly
    ? pipeline.presentation?.cursor
    : !following && pinned != null
      ? pinned
      : pipeline.presentation?.cursor;
  const canRead = active && (!pipeline.readOnly || cursor != null);
  const base = { at_seq: cursor ?? undefined };
  const overview = useExecution(
    task.task_id,
    { ...base, section: "overview" },
    canRead,
    version,
  );
  const facts = overview.data;
  const query = {
    ...base,
    stage_id: stage || undefined,
    search: search || undefined,
    start: range ? new Date(range[0]).toISOString() : undefined,
    end: range ? new Date(range[1]).toISOString() : undefined,
    limit: 30,
  };
  const events = useExecution(
    task.task_id,
    {
      ...query,
      section: "events",
      category: eventCategory || undefined,
      offset: eventOffset,
      focus_seq: focusSeq ?? undefined,
    },
    canRead && (tab === "events" || panes.hasVisited("events")),
    version,
  );
  const issues = useExecution(
    task.task_id,
    {
      ...query,
      section: "issues",
      category: issueCategory || undefined,
      offset: issueOffset,
    },
    canRead && (tab === "events" || panes.hasVisited("events")),
    version,
  );
  const jobs = useExecution(
    task.task_id,
    {
      ...query,
      section: "jobs",
      status: jobStatus || undefined,
      sort,
      offset: jobOffset,
    },
    canRead && (tab === "jobs" || panes.hasVisited("jobs")),
    version,
  );
  const detail = useExecution(
    task.task_id,
    { ...base, section: "job", job_id: selectedJob },
    canRead && (tab === "jobs" || panes.hasVisited("jobs")) && !!selectedJob,
    version,
  );
  const lanes = useExecution(
    task.task_id,
    { ...base, section: "jobs", stage_id: expanded, limit: 20 },
    canRead && (tab === "overview" || panes.hasVisited("overview")) && !!expanded,
    version,
  );
  const services = useExecution(
    task.task_id,
    { ...base, section: "services", offset: serviceOffset, limit: 30 },
    canRead && (tab === "events" || panes.hasVisited("events")),
    version,
  );
  const scroll = useScrollMemory(memory, Boolean(facts), active);
  const manual = () => {
    if (following && facts) {
      setPinned(facts.cursor);
      setFollowing(false);
    }
  };
  const changeRange = (next) => {
    manual();
    setRange(next);
    setEventOffset(0);
    setIssueOffset(0);
    setJobOffset(0);
    setFocusSeq(null);
  };
  const selectVisit = (visit) => {
    manual();
    setSelectedVisit(visit.visit_id);
  };
  const openEvent = (event) => {
    manual();
    setTab("events");
    setStage("");
    setSearch("");
    setEventCategory("");
    setFocusSeq(event.seq);
    setRange(null);
  };
  const locateTime = (event) => {
    manual();
    setTab("overview");
    const t = millis(event.at),
      begin = millis(facts?.created_at),
      end = millis(facts?.terminal_at || facts?.as_of);
    if (Number.isFinite(t) && Number.isFinite(begin) && end > begin)
      setRange([Math.max(begin, t - 60000), Math.min(end, t + 60000)]);
  };
  const openJob = (jid) => {
    manual();
    if (!selectedJob)
      listReturn.current = {
        scroll: scroll.ref.current?.scrollTop,
        focus: document.activeElement,
      };
    setTab("jobs");
    if (selectedJob && selectedJob !== jid)
      setJobStack((stack) => [...stack, selectedJob]);
    setSelectedJob(jid);
  };
  const closeJob = () => {
    setSelectedJob(jobStack.at(-1) || null);
    setJobStack((stack) => stack.slice(0, -1));
    if (!jobStack.length)
      requestAnimationFrame(() => {
        if (scroll.ref.current)
          scroll.ref.current.scrollTop = listReturn.current?.scroll || 0;
        listReturn.current?.focus?.focus({ preventScroll: true });
      });
  };
  const openLink = (key, value) => {
    if (key === "review_id") {
      onShowStageInChat("quality_check", value);
      return;
    }
    if (!facts?.delivery_ref) {
      setNavigationNotice("此时点尚未发布交付，可先查看关联作业。");
      return;
    }
    const extra = { deliveryRef: facts?.delivery_ref };
    if (key === "measurement_id")
      onOpenData("records", { ...extra, recordId: value });
    else onOpenData("evidence", { ...extra, materialId: value });
  };
  const filter = (setter, value) => {
    manual();
    setter(value);
    setEventOffset(0);
    setIssueOffset(0);
    setJobOffset(0);
    setFocusSeq(null);
  };
  useEffect(() => {
    if (!request || !facts || requestSeen.current === request.seq) return;
    requestSeen.current = request.seq;
    setTab("overview");
    setSelectedVisit(
      facts.visits.find((v) => v.stage_id === request.id)?.visit_id || null,
    );
    setFollowing(false);
    setPinned(facts.cursor);
  }, [request, facts]);
  useEffect(() => {
    if (!focusSeq || !events.data || tab !== "events") return;
    const row = eventRef.current?.querySelector(`#execution-event-${focusSeq}`);
    row?.scrollIntoView({ block: "center" });
    row?.focus({ preventScroll: true });
  }, [focusSeq, events.data, tab]);
  useEffect(() => {
    if (detail.data && selectedJob)
      detailRef.current?.scrollIntoView({ block: "nearest" });
  }, [detail.data, selectedJob]);
  const exportReport = async (format) => {
    setDownload(format);
    setDownloadError("");
    try {
      const response = await fetch(
        executionReportUrl(task.task_id, facts.cursor, format),
      );
      if (!response.ok) throw new Error("运行报告生成失败，请重试。");
      const url = URL.createObjectURL(await response.blob()),
        anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `执行报告-${task.task_id.slice(0, 8)}-${facts.cursor}.${format}`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) {
      setDownloadError(error.message);
    } finally {
      setDownload("");
    }
  };
  const error =
    overview.error ||
    events.error ||
    issues.error ||
    jobs.error ||
    lanes.error ||
    downloadError;
  const summary = facts?.summary,
    visit = facts?.visits.find((v) => v.visit_id === selectedVisit);
  let ranked =
    facts?.stages.filter(
      (s) =>
        (!stage || s.id === stage) &&
        (stageFilter === "all" ||
          (stageFilter === "visited" && s.visits.length) ||
          (stageFilter === "revisited" &&
            s.visits.some((v) => v.local_repair))),
    ) || [];
  if (ranking === "duration")
    ranked = [...ranked].sort((a, b) => (b.seconds || 0) - (a.seconds || 0));
  const maximum = Math.max(1, ...ranked.map((s) => s.seconds || 0));
  return (
    <div
      className="data-workbench execution-workbench"
      data-component="workflow-view"
      ref={scroll.ref}
      onScroll={scroll.onScroll}
    >
      <header className="execution-heading">
        <div className="execution-heading-left">
          <h2>执行明细</h2>
          <p>
            {facts ? (
              <>
                <span className="execution-status-pill">
                  <span className="execution-status-dot" />
                  {stateNames[facts.lifecycle] || "运行中"}
                </span>
                <span>截至事件 #{facts.cursor}</span>
              </>
            ) : (
              "正在读取执行记录…"
            )}
          </p>
        </div>
        <div className="execution-header-actions">
          {!following && (
            <button
              className="execution-text-action"
              onClick={() => {
                setFollowing(true);
                setPinned(null);
              }}
              title="跟随最新产生的管线事件"
            >
              跟随最新
            </button>
          )}
          {(onFocusInChat || onGoChat || onShowStageInChat) && (
            <button
              className="execution-text-action"
              onClick={() => {
                if (onFocusInChat) onFocusInChat(facts?.terminal_at || facts?.as_of);
                else if (onGoChat) onGoChat();
                else if (onShowStageInChat) onShowStageInChat(stage || "understand");
              }}
              title="在对话面板中查阅"
            >
              <Icon.MessageSquare style={{ width: 12, height: 12 }} />
              在对话查看
            </button>
          )}
          <details className="execution-export">
            <summary className="execution-export-btn">
              <Icon.Download style={{ width: 13, height: 13 }} />
              导出运行报告
              <Icon.ChevronDown style={{ width: 11, height: 11 }} />
            </summary>
            <div className="execution-export-menu">
              <button
                disabled={!facts || !!download}
                onClick={() => exportReport("pdf")}
              >
                <Icon.FileText style={{ width: 13, height: 13 }} />
                {download === "pdf" ? "正在生成 PDF…" : "下载学术 PDF 报告"}
              </button>
              <button
                disabled={!facts || !!download}
                onClick={() => exportReport("json")}
              >
                <Icon.Database style={{ width: 13, height: 13 }} />
                {download === "json" ? "正在生成 JSON…" : "下载完整执行 JSON"}
              </button>
            </div>
          </details>
        </div>
      </header>
      {error && (
        <div className="resource-error" role="alert">
          {error}
          <button
            onClick={() => {
              setVersion((n) => n + 1);
              setDownloadError("");
            }}
          >
            重试读取
          </button>
        </div>
      )}
      {navigationNotice && (
        <p className="execution-history-note" role="status">
          {navigationNotice}{" "}
          <button onClick={() => setNavigationNotice("")}>收起</button>
        </p>
      )}
      <div className="execution-subnav-vessel">
        <nav
          ref={navRef}
          className="execution-segmented-track data-tabs"
          role="tablist"
          aria-label="执行明细视图导航"
        >
          {/* 滑动高亮滑块 */}
          <div
            className="execution-nav-slider-pill"
            style={{
              transform: `translateX(${sliderStyle.left}px)`,
              width: sliderStyle.width ? `${sliderStyle.width}px` : 0,
              opacity: sliderStyle.opacity,
            }}
            aria-hidden="true"
          />
          {[
            { id: "overview", label: "执行全景", icon: Icon.Activity },
            { id: "events", label: "异常与事件", icon: Icon.Refresh },
            { id: "jobs", label: "作业明细", icon: Icon.Table },
          ].map(({ id, label, icon: TabIcon }) => {
            const isActive = tab === id;
            return (
              <button
                key={id}
                ref={(el) => {
                  tabRefs.current[id] = el;
                }}
                role="tab"
                aria-selected={isActive}
                className={`execution-tab-pill-btn tab-btn${isActive ? " active" : ""}`}
                onClick={() => setTab(id)}
              >
                <TabIcon className="execution-tab-icon" />
                <span className="execution-tab-label">{label}</span>
              </button>
            );
          })}
        </nav>
      </div>
      {!facts ? (
        <div className="execution-loading" role="status">
          正在读取此时点的阶段、作业与时间记录…
        </div>
      ) : (
        <>
          <div className="execution-hero-dashboard">
            <div className="execution-hero-left">
              <span className="execution-hero-label">
                <Icon.Clock style={{ width: 13, height: 13, color: "var(--ex-green)" }} />
                管线总执行耗时
              </span>
              <strong className="execution-hero-wall-time">
                {duration(facts.wall_seconds)}
              </strong>
              <div className="execution-hero-wait-pill">
                <span>其中科研交互等待 {duration(facts.human_wait_seconds)}</span>
              </div>
            </div>

            <div className="execution-hero-right">
              <dl className="execution-hero-metrics-grid">
                <div className="execution-hero-metric-tile">
                  <dt>核心阶段覆盖</dt>
                  <dd>
                    {summary.visited_stages}
                    <small> / 8</small>
                  </dd>
                </div>
                <div className="execution-hero-metric-tile">
                  <dt>管线调度任务</dt>
                  <dd>
                    {summary.jobs}
                    <small> 个</small>
                  </dd>
                </div>
                <div className="execution-hero-metric-tile">
                  <dt>自动容错处理</dt>
                  <dd>
                    {summary.exception_events}
                    <small> 起</small>
                  </dd>
                </div>
                <div className="execution-hero-metric-tile">
                  <dt>自适应重试</dt>
                  <dd>
                    {summary.retries}
                    <small> 次</small>
                  </dd>
                </div>
              </dl>

              <div className="execution-hero-stage-filter">
                <Icon.Filter style={{ width: 13, height: 13, color: "var(--ex-green)" }} />
                <span>阶段筛选:</span>
                <select
                  aria-label="全局阶段筛选"
                  value={stage}
                  onChange={(e) => filter(setStage, e.target.value)}
                >
                  <option value="">全部阶段</option>
                  {facts.stages.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                {(stage || range || search) && (
                  <button
                    className="execution-reset-filter-btn"
                    onClick={() => {
                      setStage("");
                      changeRange(null);
                      setSearch("");
                    }}
                  >
                    重置
                  </button>
                )}
              </div>
            </div>
          </div>
          {!facts.history_complete && (
            <p className="execution-history-note">
              历史过程记录不完整，已保存的事件和作业仍可查阅。
            </p>
          )}
          <div
            ref={contentRef}
            className="execution-panes-viewport slide-panes"
            data-sliding={panes.moving || undefined}
          >
            {/* Tab 1: 执行全景 */}
            <div className="execution-pane" {...panes.paneProps("overview")}>
              {panes.hasVisited("overview") && (
                <>
                  <ExecutionTimeline
                data={
                  stage
                    ? {
                        ...facts,
                        stages: facts.stages.filter((s) => s.id === stage),
                      }
                    : facts
                }
                range={range}
                onRange={changeRange}
                selected={selectedVisit}
                onVisit={selectVisit}
                onEvent={openEvent}
                onJob={openJob}
                expanded={expanded}
                onExpand={(id) => {
                  manual();
                  setExpanded(expanded === id ? null : id);
                }}
                jobs={lanes.data?.items || []}
              />
              {visit && (
                <section className="execution-visit-detail">
                  <div className="execution-section-heading">
                    <h3>
                      {stageNames[visit.stage_id]} ·{" "}
                      {visit.seq ? `#${visit.seq} 访问` : "任务创建"}
                    </h3>
                    <button onClick={() => setSelectedVisit(null)}>
                      收起访问详情
                    </button>
                  </div>
                  <p>
                    {clock(visit.start, true)} → {clock(visit.end, true)} ·{" "}
                    {duration(visit.seconds)} · {stateNames[visit.state]}
                  </p>
                  <p>
                    本次启动 {visit.job_total} 项作业
                    {Object.entries(visit.job_states)
                      .map(
                        ([state, count]) =>
                          ` · ${stateNames[state] || state} ${count}`,
                      )
                      .join("")}
                  </p>
                  <p>
                    {visit.previous_visit_id &&
                      `前一次访问 ${stageNames[visit.previous_visit_id.split(":")[0]]}`}
                    {visit.local_repair ? " → 本次复检回访" : ""}
                  </p>
                  <div className="execution-inline-actions">
                    {visit.seq > 0 && (
                      <button
                        onClick={() =>
                          openEvent({ seq: visit.seq, at: visit.start })
                        }
                      >
                        查看本次进入事件
                      </button>
                    )}
                    <button
                      onClick={() => {
                        filter(setStage, visit.stage_id);
                        setTab("jobs");
                      }}
                    >
                      查看本阶段作业
                    </button>
                    <button onClick={() => onShowStageInChat(visit.stage_id)}>
                      在对话查看
                    </button>
                    {visit.next_visit_id && (
                      <button
                        onClick={() => setSelectedVisit(visit.next_visit_id)}
                      >
                        查看下一次阶段访问
                      </button>
                    )}
                  </div>
                  {visit.key_events.length > 0 && (
                    <EventList
                      items={visit.key_events}
                      onEvent={openEvent}
                      onJob={openJob}
                      onLinks={openLink}
                    />
                  )}
                </section>
              )}
              <section className="execution-time-analysis">
                <div className="execution-section-heading">
                  <h3>时间主要花在哪里</h3>
                  <select
                    aria-label="阶段耗时排序"
                    value={ranking}
                    onChange={(e) => setRanking(e.target.value)}
                  >
                    <option value="duration">按耗时排序</option>
                    <option value="flow">按流程顺序</option>
                  </select>
                </div>
                <div className="execution-time-strip">
                  <div className="execution-time-base">
                    总耗时 {duration(facts.wall_seconds)}
                  </div>
                  {facts.waits.map((wait) => {
                    const style = visibleWait(wait, facts);
                    return (
                      style && (
                        <span
                          key={wait.seq}
                          style={style}
                          title={`其中人工等待 ${duration(wait.seconds)}`}
                        />
                      )
                    );
                  })}
                </div>
                <p className="execution-caption">
                  人工等待包含在总耗时内；各作业的运行时间可以重叠。
                </p>
                <label className="execution-rank-filter">
                  显示{" "}
                  <select
                    value={stageFilter}
                    onChange={(e) => setStageFilter(e.target.value)}
                  >
                    <option value="all">全部阶段</option>
                    <option value="visited">已有访问</option>
                    <option value="revisited">发生复检回访</option>
                  </select>
                </label>
                <div className="execution-rank">
                  {ranked.map((s) => (
                    <details key={s.id}>
                      <summary>
                        <span>{s.name}</span>
                        <div className="execution-rank-track">
                          <i
                            style={{
                              width: `${((s.seconds || 0) / maximum) * 100}%`,
                            }}
                          />
                        </div>
                        <strong>{duration(s.seconds)}</strong>
                        <small>{s.visits.length} 次</small>
                      </summary>
                      {s.visits.length > 0 && (
                        <p className="execution-caption">
                          单次最长{" "}
                          {duration(
                            Math.max(
                              ...s.visits
                                .map((v) => v.seconds)
                                .filter(Number.isFinite),
                            ),
                          )}{" "}
                          · 最短{" "}
                          {duration(
                            Math.min(
                              ...s.visits
                                .map((v) => v.seconds)
                                .filter(Number.isFinite),
                            ),
                          )}
                        </p>
                      )}
                      <div>
                        {s.visits.map((v) => (
                          <button
                            key={v.visit_id}
                            onClick={() => {
                              selectVisit(v);
                              changeRange([
                                millis(v.start),
                                millis(v.end || facts.as_of),
                              ]);
                            }}
                          >
                            {clock(v.start)} → {clock(v.end)} ·{" "}
                            {duration(v.seconds)}
                            {v.local_repair ? " · 复检回访" : ""}
                          </button>
                        ))}
                        {!s.visits.length && <p>未记录阶段访问</p>}
                      </div>
                    </details>
                  ))}
                </div>
                <div className="execution-parallel-summary">
                  <span>
                    峰值同时运行{" "}
                    <strong>{summary.peak_running_jobs ?? "未记录"}</strong> 项
                  </span>
                  <span>
                    资源等待 <strong>{summary.resource_waits}</strong> 次
                  </span>
                  <button
                    onClick={() => {
                      setTab("jobs");
                      setSort("duration");
                    }}
                  >
                    查看最长运行作业
                  </button>
                  <button
                    onClick={() => {
                      setTab("jobs");
                      setSort("retries");
                    }}
                  >
                    查看重试较多作业
                  </button>
                </div>
              </section>
                </>
              )}
            </div>

            {/* Tab 2: 异常与事件 */}
            <div className="execution-pane" {...panes.paneProps("events")}>
              {panes.hasVisited("events") && (
                <>
                  <section className="execution-problem-center">
                <div className="execution-section-heading">
                  <h3>异常与恢复</h3>
                  <span>
                    {summary.issues} 项作业问题 · {summary.service_issues}{" "}
                    项服务问题 · {summary.scientific_reviews} 项科研判断
                  </span>
                </div>
                <div className="execution-health-capsules">
                  <button
                    type="button"
                    className="execution-health-pill health-recovered"
                    onClick={() => filter(setIssueCategory, "recovered")}
                  >
                    <Icon.Check style={{ width: 12, height: 12 }} />
                    自动恢复闭环
                    <strong>{summary.issue_states?.recovered || 0}</strong>
                  </button>
                  <button
                    type="button"
                    className="execution-health-pill health-partial"
                    onClick={() => filter(setIssueCategory, "partial")}
                  >
                    <Icon.Refresh style={{ width: 12, height: 12 }} />
                    容错降级完成
                    <strong>{summary.issue_states?.partial || 0}</strong>
                  </button>
                  <button
                    type="button"
                    className="execution-health-pill health-unresolved"
                    onClick={() => filter(setIssueCategory, "unresolved")}
                  >
                    <Icon.AlertCircle style={{ width: 12, height: 12 }} />
                    待人工介入
                    <strong>{summary.issue_states?.unresolved || 0}</strong>
                  </button>
                </div>
                <p className="execution-narrative-note">
                  管线全流程已自动处理 {summary.exception_events} 起调度波动与 {summary.http_failures} 次数据源重试，各阶段保持自洽闭环。
                </p>
                <label>
                  问题分类{" "}
                  <select
                    aria-label="问题分类"
                    value={issueCategory}
                    onChange={(e) => filter(setIssueCategory, e.target.value)}
                  >
                    <option value="">全部问题与科研判断</option>
                    {["service", "processing", "model", "science"].map(
                      (key) => (
                        <option key={key} value={key}>
                          {categoryNames[key]}
                        </option>
                      ),
                    )}
                    {["recovered", "partial", "unresolved"].map((key) => (
                      <option key={key} value={key}>
                        {stateNames[key]}
                      </option>
                    ))}
                  </select>
                </label>
                {issues.data ? (
                  <>
                    <IssueList
                      items={issues.data.items}
                      onEvent={openEvent}
                      onTime={locateTime}
                      onJob={openJob}
                      onLinks={openLink}
                    />
                    {!issues.data.total && <p>此范围没有匹配的问题记录。</p>}
                    <Pager
                      data={issues.data}
                      onPage={(value) => {
                        manual();
                        setIssueOffset(value);
                      }}
                    />
                  </>
                ) : (
                  <p role="status">正在读取问题记录…</p>
                )}
              </section>
              <section ref={eventRef}>
                <div className="execution-section-heading">
                  <h3>执行事件流</h3>
                  <span>{events.data?.total ?? "…"} 条</span>
                </div>
                <div className="execution-list-toolbar">
                  <label>
                    类别{" "}
                    <select
                      aria-label="事件类别"
                      value={eventCategory}
                      onChange={(e) => filter(setEventCategory, e.target.value)}
                    >
                      <option value="">全部事件</option>
                      <option value="exception">仅异常事件</option>
                      {Object.entries(categoryNames)
                        .filter(
                          ([k]) =>
                            !["service", "processing", "science"].includes(k),
                        )
                        .map(([key, name]) => (
                          <option key={key} value={key}>
                            {name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <input
                    aria-label="搜索事件或作业对象"
                    placeholder="搜索动作、作业或关联对象"
                    value={search}
                    onChange={(e) => filter(setSearch, e.target.value)}
                  />
                </div>
                {events.data ? (
                  <>
                    <EventList
                      items={events.data.items}
                      focus={focusSeq}
                      onEvent={locateTime}
                      onJob={openJob}
                      onLinks={openLink}
                    />
                    {!events.data.total && <p>此范围没有匹配的事件。</p>}
                    <Pager
                      data={events.data}
                      onPage={(value) => {
                        manual();
                        setFocusSeq(null);
                        setEventOffset(value);
                      }}
                    />
                  </>
                ) : (
                  <p role="status">正在读取执行事件…</p>
                )}
              </section>
              <details className="execution-diagnostic">
                <summary>
                  任务级服务访问诊断 · {summary.http_attempts} 次访问
                </summary>
                <p>此处按任务归集；历史没有记录具体作业关联。</p>
                {services.data && (
                  <>
                    <div className="execution-table-scroll">
                      <table className="execution-table">
                        <thead>
                          <tr>
                            <th>服务</th>
                            <th>起止</th>
                            <th>结果</th>
                            <th>响应</th>
                          </tr>
                        </thead>
                        <tbody>
                          {services.data.items.map((s) => (
                            <tr key={s.attempt_id}>
                              <td>{s.service}</td>
                              <td>
                                {clock(s.start)}–{clock(s.end)}
                              </td>
                              <td>
                                {s.status === "completed"
                                  ? "已取得响应"
                                  : s.status === "failed"
                                    ? "访问失败"
                                    : "此时点无结束回执"}
                              </td>
                              <td>{s.status_code ?? "未记录"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Pager data={services.data} onPage={setServiceOffset} />
                  </>
                )}
              </details>
                </>
              )}
            </div>

            {/* Tab 3: 作业明细 */}
            <div className="execution-pane" {...panes.paneProps("jobs")}>
              {panes.hasVisited("jobs") && (
                <>
                  <div className="execution-list-toolbar">
                <label>
                  状态{" "}
                  <select
                    aria-label="作业状态"
                    value={jobStatus}
                    onChange={(e) => filter(setJobStatus, e.target.value)}
                  >
                    <option value="">全部状态</option>
                    {[
                      "succeeded",
                      "failed",
                      "running",
                      "waiting_resource",
                      "ready",
                      "not_run",
                      "cancelled",
                      "ended_unknown",
                    ].map((key) => (
                      <option key={key} value={key}>
                        {stateNames[key]}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  排序{" "}
                  <select
                    aria-label="作业排序"
                    value={sort}
                    onChange={(e) => filter(setSort, e.target.value)}
                  >
                    <option value="time">开始时间</option>
                    <option value="duration">运行耗时</option>
                    <option value="retries">重试次数</option>
                  </select>
                </label>
                <input
                  aria-label="搜索作业"
                  placeholder="搜索作业名称、类型或对象"
                  value={search}
                  onChange={(e) => filter(setSearch, e.target.value)}
                />
              </div>
              <p className="execution-caption">
                {jobs.data?.total ?? "…"} 项作业 · 耗时按实际运行区段计算
              </p>
              {jobs.data ? (
                <>
                  <JobTable items={jobs.data.items} onJob={openJob} />
                  {!jobs.data.total && <p>此范围没有匹配的作业。</p>}
                  <Pager
                    data={jobs.data}
                    onPage={(value) => {
                      manual();
                      setJobOffset(value);
                    }}
                  />
                </>
              ) : (
                <p role="status">正在读取作业…</p>
              )}
              {selectedJob && (
                <div className="execution-detail-section" ref={detailRef}>
                  <div className="execution-inline-actions">
                    <button className="execution-axis-pill-btn" onClick={closeJob}>
                      <Icon.ArrowLeft style={{ width: 13, height: 13 }} />
                      {jobStack.length ? "返回上一个作业" : "收起作业全链路详情"}
                    </button>
                  </div>
                  {detail.error ? (
                    <p role="alert">{detail.error}</p>
                  ) : detail.data ? (
                    <JobDetail
                      job={detail.data.job}
                      onJob={openJob}
                      onEvent={openEvent}
                      onLinks={openLink}
                    />
                  ) : (
                    <p role="status">正在读取作业详情…</p>
                  )}
                </div>
              )}
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function visibleWait(wait, facts) {
  const start = millis(facts.created_at),
    end = millis(facts.terminal_at || facts.as_of);
  if (!Number.isFinite(end) || end <= start) return null;
  return {
    left: `${((millis(wait.start) - start) / (end - start)) * 100}%`,
    width: `${((millis(wait.end || facts.as_of) - millis(wait.start)) / (end - start)) * 100}%`,
  };
}
