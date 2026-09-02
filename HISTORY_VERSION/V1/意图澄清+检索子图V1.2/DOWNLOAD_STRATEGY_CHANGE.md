# 下载策略修改说明

**修改日期**: 2026-07-14  
**修改内容**: 从选择TOP25改为下载所有过滤后的论文

---

## 修改摘要

### 修改前
- **策略**: 选择评分最高的TOP 25篇论文
- **配置**: `OUTPUT_TOP_N = 25`
- **影响**: 即使有更多高质量论文，也只下载25篇

### 修改后
- **策略**: 下载所有通过过滤条件的论文
- **配置**: `OUTPUT_TOP_N = None`
- **影响**: 所有符合质量标准的论文都会被下载

---

## 修改的文件

### 1. configs/constants.py
```python
# 修改前
OUTPUT_TOP_N = 25

# 修改后
OUTPUT_TOP_N = None  # None表示下载所有过滤后的论文（之前是25）
```

**位置**: 第88行

---

### 2. tools/filter_rank/rank_and_select_top.py
```python
# 修改后的逻辑
def rank_and_select_top(papers, top_n=OUTPUT_TOP_N):
    # 按score降序排序
    sorted_papers = sorted(papers, key=lambda p: p.score if p.score else 0, reverse=True)
    
    # 如果top_n为None，返回所有论文
    if top_n is None:
        selected = sorted_papers
        logger.info(f"Selecting all {len(selected)} papers (OUTPUT_TOP_N=None)")
    else:
        selected = sorted_papers[:top_n]
        logger.debug(f"Selected top {len(selected)} papers from {len(papers)} total")
    
    return selected
```

**变更**: 添加了对`None`值的处理逻辑

---

### 3. pipeline/retrieval/agents/filter_rank.py
```python
# 修改前
TOP_N = 25
ranked = rank_and_select_top(filtered, top_n=TOP_N)
print(f"  [+] 选择Top {TOP_N}篇论文")

# 修改后
from configs.constants import OUTPUT_TOP_N

ranked = rank_and_select_top(filtered, top_n=OUTPUT_TOP_N)

if OUTPUT_TOP_N is None:
    print(f"  [+] 选择所有 {len(ranked)} 篇论文（OUTPUT_TOP_N=None，下载全部）")
else:
    print(f"  [+] 选择Top {OUTPUT_TOP_N}篇论文")
```

**变更**: 
1. 添加导入`OUTPUT_TOP_N`配置
2. 移除硬编码的`TOP_N = 25`
3. 添加动态输出信息

---

## 工作流程变化

### 修改前的流程
```
搜索论文 (A+B) 
  ↓
引用扩展 (C) 
  ↓
合并去重 (E-1)
  ↓
过滤 (E-2) → 假设得到50篇
  ↓
评分 (E-3)
  ↓
选择TOP25 (E-4) → 只选25篇 ❌
  ↓
下载25篇论文 (D)
```

### 修改后的流程
```
搜索论文 (A+B)
  ↓
引用扩展 (C)
  ↓
合并去重 (E-1)
  ↓
过滤 (E-2) → 假设得到50篇
  ↓
评分 (E-3)
  ↓
选择全部 (E-4) → 选50篇 ✅
  ↓
下载50篇论文 (D)
```

---

## 影响分析

### 优势
1. ✅ **更全面**: 不会因为数量限制错过高质量论文
2. ✅ **更灵活**: 根据实际搜索结果动态调整
3. ✅ **更合理**: 已经过滤的论文都符合质量标准

### 注意事项
1. ⚠️ **下载时间**: 论文数量增加，下载时间会相应增加
2. ⚠️ **存储空间**: 需要更多磁盘空间存储论文
3. ⚠️ **API限制**: 可能触发OpenAlex/Unpaywall的速率限制

### 典型场景对比

| 场景 | 过滤后论文数 | 修改前下载 | 修改后下载 |
|------|-------------|-----------|-----------|
| 窄领域搜索 | 15篇 | 15篇 | 15篇 |
| 常规搜索 | 50篇 | 25篇 ❌ | 50篇 ✅ |
| 宽泛搜索 | 100篇 | 25篇 ❌ | 100篇 ✅ |

---

## 过滤标准（未修改）

论文仍然需要通过以下过滤条件：

### 1. 引用数过滤
```python
FILTER_MIN_CITATION_COUNT = 3  # 至少3次引用
```

### 2. 年份过滤
```python
FILTER_YEAR_RELAXATION = 2  # 允许前后2年的论文
```

### 3. 开放获取优先
```python
FILTER_OA_HIGH_CITATION_THRESHOLD = 50  # 高引论文（>50）即使非OA也保留
```

### 4. 去重
- 按论文ID去重
- 按DOI去重（如有）

---

## 评分标准（未修改）

所有论文按以下权重评分：

```python
RANK_CITATION_WEIGHT = 0.4    # 引用数权重 40%
RANK_RECENCY_WEIGHT = 0.3     # 时效性权重 30%
RANK_RELEVANCE_WEIGHT = 0.3   # 相关性权重 30%
```

论文按评分降序排列，但现在**不再限制数量**。

---

## 如何恢复原来的TOP25限制

如果需要恢复TOP25限制，修改配置文件：

```python
# 文件: configs/constants.py

# 从
OUTPUT_TOP_N = None

# 改为
OUTPUT_TOP_N = 25
```

**无需修改其他代码**，系统会自动适配。

---

## 预期效果

### 修改前（TOP25限制）
```
[Agent B] 搜索到 30 篇论文
[Agent C] 引用扩展 20 篇论文
[Agent E] 合并去重后 45 篇论文
[Agent E] 过滤后 40 篇论文
[Agent E] 选择Top 25篇论文 ❌
[Agent D] 下载 25 篇论文
```

### 修改后（下载全部）
```
[Agent B] 搜索到 30 篇论文
[Agent C] 引用扩展 20 篇论文
[Agent E] 合并去重后 45 篇论文
[Agent E] 过滤后 40 篇论文
[Agent E] 选择所有 40 篇论文（OUTPUT_TOP_N=None，下载全部）✅
[Agent D] 下载 40 篇论文
```

---

## 性能考虑

### 下载时间估算

假设单篇论文平均下载时间为2秒：

| 论文数 | 修改前时间 | 修改后时间 | 增加 |
|-------|----------|----------|------|
| 15篇 | 30秒 | 30秒 | 0秒 |
| 50篇 | 50秒 | 100秒 | +50秒 |
| 100篇 | 50秒 | 200秒 | +150秒 |

### 存储空间估算

假设单篇论文平均大小为1MB：

| 论文数 | 修改前空间 | 修改后空间 | 增加 |
|-------|----------|----------|------|
| 15篇 | 15MB | 15MB | 0MB |
| 50篇 | 25MB | 50MB | +25MB |
| 100篇 | 25MB | 100MB | +75MB |

---

## 验证方法

### 运行测试
```bash
cd "E:/整合/意图澄清+检索子图V1.1"

# 运行主流程
python pipeline/main_graph.py
```

### 检查输出
查看日志中的以下信息：

```
[步骤 5/5] 排序并选择论文
  [+] 选择所有 40 篇论文（OUTPUT_TOP_N=None，下载全部）

  [STAT] 评分排名前5:
     [1] ...
     [2] ...
     ...
```

如果看到"下载全部"字样，说明修改生效。

---

## 回滚方案

如果需要回滚到TOP25限制：

```bash
cd "E:/整合/意图澄清+检索子图V1.1"

# 编辑配置文件
nano configs/constants.py

# 修改第88行
OUTPUT_TOP_N = 25  # 恢复TOP25限制
```

保存后无需修改其他代码。

---

## 总结

✅ **修改完成**
- 配置文件已更新
- 逻辑代码已适配
- 输出信息已优化

✅ **效果**
- 下载所有过滤后的论文
- 不再受TOP25限制
- 保持评分排序

✅ **灵活性**
- 可通过配置文件轻松调整
- 支持任意数量限制或无限制
- 无需修改代码

---

**修改状态**: ✅ 完成  
**测试状态**: ⏳ 待运行验证  
**建议**: 先用小规模查询测试，确认无问题后再进行大规模检索
