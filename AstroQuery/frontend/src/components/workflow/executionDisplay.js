export const stageNames = {
  understand: "任务理解",
  retrieval: "数据检索",
  extraction: "数据提取",
  quality_check: "质量检查",
  clean: "数据清洗",
  comparison: "数据对照",
  deliver: "数据交付",
  insight: "数据洞察",
};
export const stateNames = {
  completed: "已完成",
  running: "运行中",
  clarifying: "待确认",
  queued: "排队中",
  waiting_review: "等待复核",
  waiting_input: "等待确认",
  paused: "已暂停",
  pausing: "暂停中",
  cancelled: "已取消",
  cancelling: "取消中",
  failed: "执行失败",
  error: "执行失败",
  interrupted: "已中断",
  budget_exhausted: "已结束",
  definition_invalidated: "定义已失效",
  succeeded: "调度完成",
  ready: "就绪待运行",
  waiting_resource: "资源调度中",
  not_run: "未运行",
  waiting_dependency: "等待前置依赖",
  awaiting_review: "等待人工复核",
  unknown: "未记录",
  ended_unknown: "结束状态未记录",
  ended: "已结束",
  pending: "未开始",
  recovered: "自动恢复闭环",
  partial: "容错降级完成",
  unresolved: "待人工介入",
  resolved: "已自动处理",
};
export const categoryNames = {
  service: "外部学术服务",
  processing: "文献解析与清洗",
  model: "学术大模型调用",
  science: "天体物理核验",
  review: "人机协作复检",
  stage: "核心执行阶段",
  job: "管线任务",
  material: "材料与批次",
  delivery: "交付与导出",
  insight: "天体物理洞察",
  other: "其他事件",
};
export function duration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "未记录";
  const n = Math.round(seconds);
  return n >= 3600
    ? `${Math.floor(n / 3600)}小时${Math.floor((n % 3600) / 60)}分${n % 60}秒`
    : `${Math.floor(n / 60)}分${n % 60}秒`;
}
export function clock(at, full = false) {
  if (!at || !Number.isFinite(Date.parse(at))) return "未记录";
  return new Date(at).toLocaleString("zh-CN", {
    ...(full ? { month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
export const millis = (at) => (at ? Date.parse(at) : NaN);
export function visibleSpan(start, end, range) {
  const a = millis(start),
    b = millis(end),
    [lo, hi] = range;
  if (![a, b, lo, hi].every(Number.isFinite) || b < lo || a > hi || hi <= lo)
    return null;
  return {
    left: `${Math.max(0, ((a - lo) / (hi - lo)) * 100)}%`,
    width: `${Math.max(0.4, ((Math.min(b, hi) - Math.max(a, lo)) / (hi - lo)) * 100)}%`,
  };
}
