import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  clock,
  duration,
  millis,
  visibleSpan,
  stateNames,
} from "./executionDisplay";
import { Icon } from "@/components/icons";

export default function ExecutionTimeline({
  data,
  range,
  onRange,
  selected,
  onVisit,
  onEvent,
  onJob,
  expanded,
  onExpand,
  jobs = [],
}) {
  const [width, setWidth] = useState(1);
  const drag = useRef(null);

  const full = useMemo(() => [
    millis(data.created_at),
    millis(data.terminal_at || data.as_of),
  ], [data.created_at, data.terminal_at, data.as_of]);

  const actual = range || full;
  const span = Math.max(1, actual[1] - actual[0]);
  const totalWallSeconds = Math.max(1, (full[1] - full[0]) / 1000);
  const maxStageSeconds = Math.max(1, ...data.stages.map((s) => s.seconds || 0));

  const ticks = Array.from({ length: 6 }, (_, i) => actual[0] + (span * i) / 5);

  const zoom = (factor) => {
    const mid = (actual[0] + actual[1]) / 2;
    const half = (span * factor) / 2;
    onRange([Math.max(full[0], mid - half), Math.min(full[1], mid + half)]);
  };

  const pan = (direction) => {
    const shift = span * 0.35 * direction;
    const a = Math.min(full[1] - span, Math.max(full[0], actual[0] + shift));
    onRange([a, a + span]);
  };

  const focusStage = (stage) => {
    if (!stage.visits?.length) return;
    const first = millis(stage.visits[0].start);
    const last = millis(stage.visits[stage.visits.length - 1].end || data.as_of);
    const pad = Math.max(60000, (last - first) * 0.25);
    onRange([Math.max(full[0], first - pad), Math.min(full[1], last + pad)]);
  };

  const focusTopDuration = () => {
    const topStage = [...data.stages].sort((a, b) => (b.seconds || 0) - (a.seconds || 0))[0];
    if (topStage) focusStage(topStage);
  };

  const focusRevisits = () => {
    const revisits = data.stages.flatMap((s) => s.visits || []).filter((v) => v.local_repair);
    if (!revisits.length) return;
    const first = Math.min(...revisits.map((v) => millis(v.start)));
    const last = Math.max(...revisits.map((v) => millis(v.end || data.as_of)));
    const pad = Math.max(60000, (last - first) * 0.3);
    onRange([Math.max(full[0], first - pad), Math.min(full[1], last + pad)]);
  };

  return (
    <section className="execution-chart" aria-label="八阶段执行时间线">
      <div className="execution-section-heading">
        <div className="execution-heading-main">
          <h3>执行全景时序看板</h3>
          <span className="execution-heading-badge">管线时序与调度追踪</span>
        </div>
        <span className="execution-heading-meta">
          基准时钟：本地时间 · 耗时 <strong>{duration(totalWallSeconds)}</strong>
        </span>
      </div>

      {/* 宏观阶段连续流水走势条 (Macro Pipeline Ribbon) —— 充实视觉，消除大块空白感 */}
      <div className="pipeline-flow-ribbon-card">
        <div className="pipeline-flow-ribbon-header">
          <div className="pipeline-flow-ribbon-title">
            <span className="pipeline-flow-pulse-dot" />
            <span>全阶段流水推进走势</span>
            <small>点击任意阶段块可自动对齐缩放至该时段</small>
          </div>
          <div className="pipeline-flow-ribbon-stats">
            <span>总耗时 <strong>{duration(totalWallSeconds)}</strong></span>
            <span>·</span>
            <span>共 <strong>{data.stages.length}</strong> 个阶段</span>
          </div>
        </div>
        <div className="pipeline-flow-track">
          {data.stages.map((stage, idx) => {
            const pct = Math.max(7, ((stage.seconds || 0) / totalWallSeconds) * 100);
            const isTop = stage.seconds === maxStageSeconds;
            const hasRevisit = stage.visits?.some((v) => v.local_repair);
            return (
              <button
                key={stage.id}
                type="button"
                className={`pipeline-flow-block ${isTop ? "is-top-duration" : ""} ${hasRevisit ? "has-revisit" : ""}`}
                style={{ flex: `${pct} 0 auto` }}
                onClick={() => focusStage(stage)}
                title={`${stage.name} · ${duration(stage.seconds)} (占比 ${(((stage.seconds || 0) / totalWallSeconds) * 100).toFixed(1)}%) 点击缩放到此时段`}
              >
                <span className="pipeline-flow-step-num">{String(idx + 1).padStart(2, "0")}</span>
                <span className="pipeline-flow-name">{stage.name}</span>
                <span className="pipeline-flow-dur">{duration(stage.seconds)}</span>
                {hasRevisit && <span className="pipeline-flow-revisit-badge">复检</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* 精密时序控制栏 */}
      <div className="execution-axis-tools">
        {/* 左侧：聚焦预设 */}
        <div className="execution-tool-group">
          <span className="execution-tool-label">视图预设:</span>
          <button
            type="button"
            className={`execution-axis-pill-btn ${!range ? "is-active" : ""}`}
            onClick={() => {
              onRange(null);
              setWidth(1);
            }}
            title="恢复全局完整时间范围"
          >
            <Icon.RotateCcw style={{ width: 12, height: 12 }} />
            全局完整 ({((totalWallSeconds) / 60).toFixed(1)}m)
          </button>
          <button
            type="button"
            className="execution-axis-pill-btn"
            onClick={focusTopDuration}
            title="聚焦耗时最长的核心计算阶段"
          >
            <Icon.Activity style={{ width: 12, height: 12 }} />
            聚焦核心耗时段
          </button>
          <button
            type="button"
            className="execution-axis-pill-btn"
            onClick={focusRevisits}
            title="快速定位发生局部复检回访的阶段"
          >
            <Icon.Refresh style={{ width: 12, height: 12 }} />
            定位复检回访
          </button>
        </div>

        {/* 中间：精细缩放与平移 */}
        <div className="execution-tool-group">
          <button
            type="button"
            className="execution-axis-pill-btn"
            aria-label="向前平移时间轴"
            onClick={() => pan(-1)}
            title="向前平移时间视窗"
          >
            <Icon.ChevronLeft style={{ width: 12, height: 12 }} />
            前移
          </button>
          <button
            type="button"
            className="execution-axis-pill-btn"
            onClick={() => zoom(0.5)}
            disabled={span < 1000}
            title="放大时间轴显示"
          >
            <Icon.Plus style={{ width: 12, height: 12 }} />
            放大
          </button>
          <button
            type="button"
            className="execution-axis-pill-btn"
            onClick={() => zoom(2)}
            title="缩小时间轴显示"
          >
            <Icon.Minus style={{ width: 12, height: 12 }} />
            缩小
          </button>
          <button
            type="button"
            className="execution-axis-pill-btn"
            aria-label="向后平移时间轴"
            onClick={() => pan(1)}
            title="向后平移时间视窗"
          >
            后移
            <Icon.ChevronRight style={{ width: 12, height: 12 }} />
          </button>
        </div>

        {/* 右侧：当前时段指示与密度切换 */}
        <div className="execution-tool-group">
          <span className="execution-scope-pill" title="当前显示的起止时间范围">
            <Icon.Clock style={{ width: 12, height: 12, color: "var(--seed-accent)" }} />
            <span>{clock(new Date(actual[0]).toISOString())}</span>
            <span>→</span>
            <span>{clock(new Date(actual[1]).toISOString())}</span>
            <small>({duration((actual[1] - actual[0]) / 1000)})</small>
          </span>
          <button
            type="button"
            className="execution-axis-pill-btn"
            onClick={() => setWidth((n) => (n === 1 ? 2 : 1))}
            title={width === 1 ? "展开为高密度横向长图" : "适应屏幕宽度"}
          >
            <Icon.Maximize style={{ width: 12, height: 12 }} />
            {width === 1 ? "高密全览" : "自适应宽"}
          </button>
        </div>
      </div>

      {!data.visits.length && (
        <p className="execution-empty">
          历史未记录阶段访问区间。下方仍可查阅已保存的事件。
        </p>
      )}

      {/* 时间线主体表格区域 */}
      <div
        className="execution-axis-scroll"
        tabIndex={0}
        aria-label="可横向滚动的执行时间轴"
        onPointerDown={(event) => {
          if (
            event.pointerType !== "mouse" ||
            event.button !== 0 ||
            event.target.closest("button,input,select,summary")
          )
            return;
          drag.current = {
            x: event.clientX,
            start: actual[0],
            span,
            scroll: event.currentTarget.scrollLeft,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          event.preventDefault();
        }}
        onPointerMove={(event) => {
          if (!drag.current) return;
          const delta = event.clientX - drag.current.x;
          if (
            event.currentTarget.scrollWidth > event.currentTarget.clientWidth
          ) {
            event.currentTarget.scrollLeft = drag.current.scroll - delta;
            return;
          }
          const next = Math.max(
            full[0],
            Math.min(
              full[1] - drag.current.span,
              drag.current.start -
                (delta / Math.max(1, event.currentTarget.clientWidth - 230)) *
                  drag.current.span,
            ),
          );
          onRange([next, next + drag.current.span]);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div
          className="execution-axis"
          style={{ minWidth: width === 1 ? 840 : 1480 }}
        >
          {/* 表头刻度 */}
          <div className="execution-ticks">
            <div className="execution-ticks-header-label">
              <span className="execution-ticks-title">阶段 / 流程指标</span>
              <span className="execution-ticks-count">共 8 阶段</span>
            </div>
            <div className="execution-ticks-track">
              {ticks.map((at, i) => {
                const elapsedMin = Math.max(0, (at - full[0]) / 60000).toFixed(1);
                return (
                  <div key={i} className="execution-tick-point" style={{ left: `${i * 20}%` }}>
                    <span className="tick-relative">+{elapsedMin}m</span>
                    <span className="tick-clock">{clock(new Date(at).toISOString())}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 各阶段泳道行 */}
          {data.stages.map((stage, stageIdx) => {
            const stageSeconds = stage.seconds || 0;
            const stageShare = totalWallSeconds > 0 ? ((stageSeconds / totalWallSeconds) * 100).toFixed(1) : 0;
            const stageBarWidth = Math.min(100, (stageSeconds / maxStageSeconds) * 100);
            const isExpanded = expanded === stage.id;
            const visitCount = stage.visits?.length || 0;
            const hasRevisit = stage.visits?.some((v) => v.local_repair);

            return (
              <div className={`execution-lane-group ${hasRevisit ? "has-revisit-lane" : ""}`} key={stage.id}>
                <div className="execution-lane">
                  <div className="execution-lane-label">
                    <button
                      type="button"
                      className="execution-stage-identity-card"
                      aria-expanded={isExpanded}
                      onClick={() => onExpand(stage.id)}
                      title={`点击${isExpanded ? '收起' : '展开'} ${stage.name} 的底层作业详情`}
                    >
                      <div className="stage-card-top-row">
                        <span className="stage-index-badge">{String(stageIdx + 1).padStart(2, "0")}</span>
                        <span className="execution-lane-name">{stage.name}</span>
                        <div className="stage-tags-group">
                          {hasRevisit && <span className="stage-revisit-tag">复检</span>}
                          <span className="stage-visit-count-tag">{visitCount} 次</span>
                        </div>
                      </div>
                      <div className="stage-card-mid-row">
                        <span className="stage-duration-num">{duration(stageSeconds)}</span>
                        <span className="stage-share-pill">占比 {stageShare}%</span>
                        {stage.job_total ? (
                          <span className="stage-jobs-count-text">{stage.job_total} 作业</span>
                        ) : null}
                      </div>
                      {/* 微型耗时占比条 */}
                      <div className="stage-mini-progress-track" title={`耗时占比 ${stageShare}%`}>
                        <div
                          className="stage-mini-progress-fill"
                          style={{ width: `${stageBarWidth}%` }}
                        />
                      </div>
                    </button>
                  </div>

                  <div className="execution-track">
                    {ticks.map((_, i) => (
                      <i
                        className="execution-gridline"
                        key={i}
                        style={{ left: `${i * 20}%` }}
                      />
                    ))}

                    {/* 甘特时序条 */}
                    {stage.visits.map((visit, i) => {
                      const style = visibleSpan(
                        visit.start,
                        visit.end || data.as_of,
                        actual,
                      );
                      if (!style) return null;
                      const widthPct = parseFloat(style.width) || 0;
                      const isRevisit = !!visit.local_repair;
                      const isSelected = selected === visit.visit_id;

                      const labelText = isRevisit
                        ? "复检回访"
                        : {
                            catalog: "星表获取",
                            literature: "文献解析",
                            acquisition: "数据获取",
                          }[visit.execution_stage] ||
                          (i === 0 ? "首次执行" : `第${i + 1}次访问`);

                      return (
                        <button
                          key={visit.visit_id}
                          type="button"
                          className={`execution-visit ${isRevisit ? "is-revisit" : ""} ${isSelected ? "is-selected" : ""}`}
                          style={style}
                          onClick={() => onVisit(visit)}
                          aria-label={`${stage.name}第${i + 1}次访问 ${duration(visit.seconds)}${isRevisit ? " 局部复检回访" : ""}`}
                          title={`${stage.name} #${visit.seq} ${clock(visit.start)} → ${clock(visit.end)} · 耗时 ${duration(visit.seconds)}${isRevisit ? " (局部复检回访)" : ""}`}
                        >
                          <span className="visit-inner-content">
                            {widthPct > 9 ? (
                              <>
                                <span className="visit-badge-kind">{labelText}</span>
                                <span className="visit-badge-sep">·</span>
                                <span className="visit-badge-dur">{duration(visit.seconds)}</span>
                              </>
                            ) : widthPct > 4.5 ? (
                              <span className="visit-badge-dur">{duration(visit.seconds)}</span>
                            ) : (
                              <span className="visit-dot-indicator" />
                            )}
                          </span>
                        </button>
                      );
                    })}

                    {/* 人工等待条带 */}
                    {data.waits
                      .filter((w) => w.stage_id === stage.id)
                      .map((w) => {
                        const style = visibleSpan(
                          w.start,
                          w.end || data.as_of,
                          actual,
                        );
                        return (
                          style && (
                            <span
                              key={w.seq}
                              className="execution-human-wait"
                              style={style}
                              title={`科研人工交互与等待 ${duration(w.seconds)}`}
                            >
                              <span className="wait-stripe-icon">⏱</span>
                              <span className="wait-stripe-text">人工等待 {duration(w.seconds)}</span>
                            </span>
                          )
                        );
                      })}

                    {/* 里程碑事件 Pin */}
                    <TimelineMarkers
                      events={data.markers.filter((e) => e.stage_id === stage.id)}
                      range={actual}
                      cursor={data.cursor}
                      onEvent={onEvent}
                    />
                  </div>
                </div>

                {/* 展开的作业子泳道 */}
                {isExpanded && (
                  <div className="execution-job-lanes">
                    <div className="execution-job-lanes-header">
                      <Icon.Layers style={{ width: 13, height: 13, color: "var(--seed-accent)" }} />
                      <span>本阶段共调度 <strong>{stage.job_total}</strong> 项底层作业 (当前视图展示 {jobs.length} 项)</span>
                    </div>
                    {jobs.map((job) => (
                      <div
                        className="execution-lane execution-job-lane"
                        key={job.job_id}
                      >
                        <button
                          type="button"
                          className="execution-lane-label execution-job-label"
                          onClick={() => onJob(job.job_id)}
                        >
                          <span className="job-lane-name">{job.name}</span>
                          <span className={`job-lane-status status-${job.status}`}>{job.status_label || stateNames[job.status] || job.status}</span>
                        </button>
                        <div className="execution-track">
                          {ticks.map((_, i) => (
                            <i
                              className="execution-gridline"
                              key={i}
                              style={{ left: `${i * 20}%` }}
                            />
                          ))}
                          {job.runs.map((run) => {
                            const style = visibleSpan(
                              run.start,
                              run.end || data.as_of,
                              actual,
                            );
                            return (
                              style && (
                                <button
                                  key={run.seq}
                                  type="button"
                                  className={`execution-job-run state-${run.status}`}
                                  style={style}
                                  onClick={() => onJob(job.job_id)}
                                  title={`${job.name} ${stateNames[run.status] || run.status} ${duration(run.seconds)}`}
                                  aria-label={`查看${job.name}作业 #${run.seq}`}
                                />
                              )
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* 终态卡片行 */}
          <div className="execution-terminal-row">
            <div className="terminal-row-left">
              <span className="terminal-flag-icon">✓</span>
              <span className="terminal-flag-label">管线全周期终态节点</span>
            </div>
            <div className="terminal-row-right">
              {data.terminal_seq ? (
                <button
                  type="button"
                  className="terminal-event-card-btn"
                  onClick={() =>
                    onEvent({ seq: data.terminal_seq, at: data.terminal_at })
                  }
                  title="点击查看终态完成事件详情"
                >
                  <span className="terminal-seq">#{data.terminal_seq}</span>
                  <span className="terminal-clock">{clock(data.terminal_at)}</span>
                  <span className="terminal-status-pill">{stateNames[data.lifecycle] || "调度已完成"}</span>
                  <span className="terminal-total-dur">总执行耗时 {duration(totalWallSeconds)}</span>
                </button>
              ) : (
                <span className="terminal-pending-text">
                  {data.lifecycle === "completed"
                    ? "终止时点已归档"
                    : "尚未记录终态事件"}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 现代图例栏 */}
      <div className="execution-legend">
        <span className="legend-item">
          <i className="legend-chip legend-visit" />
          <span>核心执行访问</span>
        </span>
        <span className="legend-item">
          <i className="legend-chip legend-revisit" />
          <span>局部复检回访</span>
        </span>
        <span className="legend-item">
          <i className="legend-chip legend-wait" />
          <span>科研人工等待</span>
        </span>
        <span className="legend-item">
          <i className="legend-chip legend-event" />
          <span>关键里程碑事件</span>
        </span>
        <span className="legend-item">
          <i className="legend-chip legend-issue" />
          <span>异常与重试事件</span>
        </span>
        <span className="legend-item">
          <i className="legend-chip legend-terminal" />
          <span>终态归档</span>
        </span>
      </div>
    </section>
  );
}

function TimelineMarkers({ events, range, cursor, onEvent }) {
  const [menu, setMenu] = useState(null);
  const picker = useRef(null);
  const trigger = useRef(null);

  useEffect(() => setMenu(null), [cursor, range[0], range[1]]);

  useEffect(() => {
    if (!menu) return;
    picker.current?.querySelector("button")?.focus();
    const close = (event) => {
      if (
        !picker.current?.contains(event.target) &&
        !trigger.current?.contains(event.target)
      )
        setMenu(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);

  const groups = new Map();
  const span = Math.max(1, range[1] - range[0]);

  for (const event of events) {
    const position = ((millis(event.at) - range[0]) / span) * 100;
    if (position < 0 || position > 100) continue;
    const key = Math.round(position);
    if (!groups.has(key)) groups.set(key, { position, events: [] });
    groups.get(key).events.push(event);
  }

  return (
    <>
      {[...groups].map(([key, group]) => {
        const hasIssue = group.events.some((e) => e.exception);
        const count = group.events.length;
        return (
          <button
            key={key}
            type="button"
            data-marker-seqs={group.events.map((e) => e.seq).join(",")}
            className={`execution-marker ${hasIssue ? "is-issue" : ""} ${count > 1 ? "is-cluster" : ""}`}
            style={{ left: `${group.position}%` }}
            title={group.events.map((e) => `#${e.seq} ${e.label}`).join(" / ")}
            aria-label={`定位事件 ${group.events.map((e) => e.seq).join("、")}`}
            onClick={(event) => {
              if (count === 1) {
                onEvent(group.events[0]);
                return;
              }
              trigger.current = event.currentTarget;
              const rect = event.currentTarget.getBoundingClientRect();
              setMenu({
                ...group,
                left: Math.max(12, Math.min(innerWidth - 290, rect.left)),
                top: Math.max(12, Math.min(innerHeight - 310, rect.bottom + 8)),
              });
            }}
          >
            <span className="marker-pin-head">
              {hasIssue ? (count > 1 ? `!${count}` : "!") : (count > 1 ? count : "•")}
            </span>
          </button>
        );
      })}

      {menu &&
        createPortal(
          <div
            className="execution-marker-picker"
            ref={picker}
            style={{ left: menu.left, top: menu.top }}
            role="dialog"
            aria-label="选择此处的执行事件"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setMenu(null);
                trigger.current?.focus();
              }
            }}
          >
            <p className="marker-picker-title">此处归集有 {menu.events.length} 条执行事件</p>
            <div className="marker-picker-list">
              {menu.events.map((event) => (
                <button
                  key={event.seq}
                  type="button"
                  className={`marker-picker-item ${event.exception ? "is-issue" : ""}`}
                  onClick={() => {
                    setMenu(null);
                    onEvent(event);
                  }}
                >
                  <span className="picker-item-seq">#{event.seq}</span>
                  <span className="picker-item-label">{event.label}</span>
                  <small className="picker-item-clock">{clock(event.at)}</small>
                </button>
              ))}
            </div>
            <button
              type="button"
              className="marker-picker-close-btn"
              onClick={() => {
                setMenu(null);
                trigger.current?.focus();
              }}
            >
              关闭
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
