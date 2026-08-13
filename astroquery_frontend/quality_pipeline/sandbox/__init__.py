"""sandbox — 沙箱 SSOT 共享设施 (P0)

收纳 Layer 3 (LLM 动态生成工具) 的沙箱常量/工厂/校验函数, 供
normalization_agent (执行端) 与 planning_agent (dry-run 端) 共用,
杜绝两侧实现漂移 (docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(c))。
"""
