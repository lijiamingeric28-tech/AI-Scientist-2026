import { useEffect, useRef, useState } from "react";
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
  const full = [
    millis(data.created_at),
    millis(data.terminal_at || data.as_of),
  ];
  const actual = range || full,
    span = Math.max(1, actual[1] - actual[0]);
  const ticks = Array.from({ length: 6 }, (_, i) => actual[0] + (span * i) / 5);
  const zoom = (factor) => {
    const mid = (actual[0] + actual[1]) / 2,
      half = (span * factor) / 2;
    onRange([Math.max(full[0], mid - half), Math.min(full[1], mid + half)]);
  };
  const pan = (direction) => {
    const shift = span * 0.35 * direction;
    const a = Math.min(full[1] - span, Math.max(full[0], actual[0] + shift));
    onRange([a, a + span]);
  };
  const rangeValue = (index) =>
    Math.max(0, (actual[index] - full[0]) / 60000).toFixed(1);
  const custom = (index, value) => {
    const next = [...actual];
    next[index] = full[0] + Number(value) * 60000;
    if (next[0] < next[1] && next[0] >= full[0] && next[1] <= full[1] + 1000)
      onRange(next);
  };
  return (
    <section className="execution-chart" aria-label="八阶段执行时间线">
      <div className="execution-section-heading">
        <h3>执行全景</h3>
        <span>本地时间</span>
      </div>
      <div className="execution-axis-tools">
        <div className="execution-tool-group">
          <button
            className="execution-axis-pill-btn"
            onClick={() => zoom(0.5)}
            disabled={span < 1000}
            title="放大时间轴显示"
          >
            <Icon.Search style={{ width: 12, height: 12 }} />
            放大
          </button>
          <button
            className="execution-axis-pill-btn"
            onClick={() => zoom(2)}
            title="缩小时间轴显示"
          >
            缩小
          </button>
          <button
            className="execution-axis-pill-btn"
            aria-label="向前平移时间轴"
            onClick={() => pan(-1)}
            title="向前平移时间视窗"
          >
            <Icon.ChevronLeft style={{ width: 12, height: 12 }} />
            前移
          </button>
          <button
            className="execution-axis-pill-btn"
            aria-label="向后平移时间轴"
            onClick={() => pan(1)}
            title="向后平移时间视窗"
          >
            后移
            <Icon.ChevronRight style={{ width: 12, height: 12 }} />
          </button>
          <button
            className="execution-axis-pill-btn"
            onClick={() => {
              onRange(null);
              setWidth(1);
            }}
            title="恢复全局完整时间范围"
          >
            <Icon.RotateCcw style={{ width: 12, height: 12 }} />
            全局范围
          </button>
        </div>
        <div className="execution-tool-group">
          <label className="execution-axis-input-box">
            起始
            <input
              type="number"
              step="0.1"
              min="0"
              value={rangeValue(0)}
              onChange={(e) => custom(0, e.target.value)}
            />
            m
          </label>
          <label className="execution-axis-input-box">
            结束
            <input
              type="number"
              step="0.1"
              min="0"
              value={rangeValue(1)}
              onChange={(e) => custom(1, e.target.value)}
            />
            m
          </label>
          <button
            className="execution-axis-pill-btn"
            onClick={() => setWidth((n) => (n === 1 ? 2 : 1))}
          >
            <Icon.Maximize style={{ width: 12, height: 12 }} />
            {width === 1 ? "展开高密度时间轴" : "自适应宽度"}
          </button>
        </div>
      </div>
      {!data.visits.length && (
        <p className="execution-empty">
          历史未记录阶段访问区间。下方仍可查阅已保存的事件。
        </p>
      )}
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
                (delta / Math.max(1, event.currentTarget.clientWidth - 152)) *
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
          style={{ minWidth: width === 1 ? 740 : 1400 }}
        >
          <div className="execution-ticks">
            <div>阶段 / 访问</div>
            <div>
              {ticks.map((at, i) => (
                <span key={i} style={{ left: `${i * 20}%` }}>
                  {clock(new Date(at).toISOString())}
                </span>
              ))}
            </div>
          </div>
          {data.stages.map((stage) => (
            <div className="execution-lane-group" key={stage.id}>
              <div className="execution-lane">
                <div className="execution-lane-label">
                  <button
                    aria-expanded={expanded === stage.id}
                    onClick={() => onExpand(stage.id)}
                  >
                    <span className="execution-lane-name">{stage.name}</span>
                    <span>
                      {stage.visits.length} 次 · {duration(stage.seconds)}
                    </span>
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
                  {stage.visits.map((visit, i) => {
                    const style = visibleSpan(
                      visit.start,
                      visit.end || data.as_of,
                      actual,
                    );
                    return (
                      style && (
                        <button
                          key={visit.visit_id}
                          className={`execution-visit ${visit.local_repair ? "is-revisit" : ""} ${selected === visit.visit_id ? "is-selected" : ""}`}
                          style={style}
                          onClick={() => onVisit(visit)}
                          aria-label={`${stage.name}第${i + 1}次访问 ${duration(visit.seconds)}${visit.local_repair ? " 局部复检回访" : ""}`}
                          title={`${stage.name} #${visit.seq} ${clock(visit.start)} → ${clock(visit.end)} · ${duration(visit.seconds)}`}
                        >
                          <span>
                            {visit.local_repair
                              ? "复检回访"
                              : {
                                  catalog: "星表",
                                  literature: "文献",
                                  acquisition: "获取",
                                }[visit.execution_stage] ||
                                (i === 0 ? "首次" : `第${i + 1}次`)}{" "}
                            · {duration(visit.seconds)}
                          </span>
                        </button>
                      )
                    );
                  })}
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
                            title={`人工等待 ${duration(w.seconds)}`}
                          >
                            人工等待
                          </span>
                        )
                      );
                    })}
                  <TimelineMarkers
                    events={data.markers.filter((e) => e.stage_id === stage.id)}
                    range={actual}
                    cursor={data.cursor}
                    onEvent={onEvent}
                  />
                </div>
              </div>
              {expanded === stage.id && (
                <div className="execution-job-lanes">
                  <p>
                    {stage.job_total} 项作业 · 当前显示 {jobs.length} 项 ·
                    可在作业明细中继续筛选
                  </p>
                  {jobs.map((job) => (
                    <div
                      className="execution-lane execution-job-lane"
                      key={job.job_id}
                    >
                      <button
                        className="execution-lane-label"
                        onClick={() => onJob(job.job_id)}
                      >
                        {job.name}
                        <span>{job.status_label}</span>
                      </button>
                      <div className="execution-track">
                        {job.runs.map((run) => {
                          const style = visibleSpan(
                            run.start,
                            run.end || data.as_of,
                            actual,
                          );
                          return (
                            style && (
                              <button
                                className={`execution-job-run state-${run.status}`}
                                style={style}
                                key={run.seq}
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
          ))}
          <div className="execution-terminal-row">
            <span>任务终态</span>
            {data.terminal_seq ? (
              <button
                onClick={() =>
                  onEvent({ seq: data.terminal_seq, at: data.terminal_at })
                }
              >
                #{data.terminal_seq} · {clock(data.terminal_at)} ·{" "}
                {stateNames[data.lifecycle] || "已结束"}
              </button>
            ) : (
              <span>
                {data.lifecycle === "completed"
                  ? "终止时点未记录"
                  : "尚未记录终态事件"}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="execution-legend">
        <span>
          <i className="legend-visit" />
          阶段访问
        </span>
        <span>
          <i className="legend-revisit" />
          复检回访
        </span>
        <span>
          <i className="legend-wait" />
          人工等待
        </span>
        <span>
          <i className="legend-event" />
          事件
        </span>
      </div>
    </section>
  );
}

function TimelineMarkers({ events, range, cursor, onEvent }) {
  const [menu, setMenu] = useState(null),
    picker = useRef(null),
    trigger = useRef(null);
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
  const groups = new Map(),
    span = Math.max(1, range[1] - range[0]);
  for (const event of events) {
    const position = ((millis(event.at) - range[0]) / span) * 100;
    if (position < 0 || position > 100) continue;
    const key = Math.round(position);
    if (!groups.has(key)) groups.set(key, { position, events: [] });
    groups.get(key).events.push(event);
  }
  return (
    <>
      {[...groups].map(([key, group]) => (
        <button
          key={key}
          data-marker-seqs={group.events.map((e) => e.seq).join(",")}
          className={`execution-marker ${group.events.some((e) => e.exception) ? "is-issue" : ""} ${group.events.length > 1 ? "is-cluster" : ""}`}
          style={{ left: `${group.position}%` }}
          title={group.events.map((e) => `#${e.seq} ${e.label}`).join(" / ")}
          aria-label={`定位事件 ${group.events.map((e) => e.seq).join("、")}`}
          onClick={(event) => {
            if (group.events.length === 1) {
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
          {group.events.length > 1 ? group.events.length : null}
        </button>
      ))}
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
            <p>此处有 {menu.events.length} 条事件</p>
            {menu.events.map((event) => (
              <button
                key={event.seq}
                onClick={() => {
                  setMenu(null);
                  onEvent(event);
                }}
              >
                #{event.seq} · {event.label}
                <small>{clock(event.at)}</small>
              </button>
            ))}
            <button
              onClick={() => {
                setMenu(null);
                trigger.current?.focus();
              }}
            >
              关闭事件选择
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
