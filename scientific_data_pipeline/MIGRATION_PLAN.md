# 迁移计划 (Migration Plan)

## 当前状态：骨架已创建 ✅

项目结构已完成，所有必需文件已创建。

## 迁移顺序

### 阶段1：配置和共享组件（最安全）

- [ ] `config/` - 配置文件
- [ ] `shared/models/` - 数据模型
- [ ] `shared/utils/` - 工具函数

### 阶段2：子图迁移（逐个进行）

#### 子图1：意图澄清（最简单）
- [ ] 复制 `pipeline/intent/` 到 `subgraphs/intent_clarification/`
- [ ] 修复 import 路径
- [ ] 测试运行

#### 子图2：检索
- [ ] 复制 `pipeline/retrieval/` 到 `subgraphs/retrieval/`
- [ ] 修复 import 路径
- [ ] 测试运行

#### 子图3：提取
- [ ] 复制 `pipeline/extraction/` 到 `subgraphs/extraction/`
- [ ] 修复 import 路径
- [ ] 测试运行

#### 子图4：质检（最复杂）
- [ ] 复制 `Data_Assessment_agentV1/` 到 `subgraphs/quality/assessment/`
- [ ] 复制 `Data_Normalization_agentV1/` 到 `subgraphs/quality/normalization/`
- [ ] 复制 `Data_Conflict_agentV1/` 到 `subgraphs/quality/conflict/`
- [ ] 复制 `Data_Export_agentV1/` 到 `subgraphs/quality/export/`
- [ ] 复制 `Data_HumanReview_agentV1/` 到 `subgraphs/quality/human_review/`
- [ ] 整合主图 `graph.py`
- [ ] 修复所有 import
- [ ] 测试运行

### 阶段3：主图整合
- [ ] 实现 `main_graph/wrappers.py` 中的包装函数
- [ ] 完成 `main_graph/graph.py`
- [ ] 端到端测试

## 迁移原则

1. **一次只迁移一个子图**
2. **每次迁移后立即测试**
3. **不删除旧代码**
4. **使用 Git commit 保护进度**
5. **遇到问题立即回滚**

## 下一步

运行验证脚本：
```bash
python scripts/validate_structure.py
```
