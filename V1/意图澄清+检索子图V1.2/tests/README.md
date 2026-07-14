# 检索子图测试指南

**最后更新**: 2026-07-14

---

## 📋 测试概述

本测试套件用于验证检索子图系统的稳定性和正确性。

**测试范围**:
- ✅ Agent A: 查询扩展
- ✅ Agent B: 论文搜索
- ✅ Agent C: 引用扩展（已修复）
- ✅ Agent E: 过滤排序
- ✅ Agent D: 论文下载

**不包含**: 意图澄清子图（已单独测试通过）

---

## 🚀 快速开始

### 方法1: 快速单次测试（推荐）

用于快速验证系统是否正常工作：

```bash
cd "E:/整合/意图澄清+检索子图V1.1/tests"

# 使用默认查询
python quick_test.py

# 自定义查询
python quick_test.py --query "perovskite solar cells"

# 指定年份范围
python quick_test.py --query "quantum dots" --year-start 2022 --year-end 2024
```

**预期输出**:
```
检索子图快速测试
================================================================================
查询: graphene mechanical properties
年份: 2020-2024
...
[✓] 测试成功完成

耗时: 45.23秒

[统计]
  搜索结果: 35 篇
  引用扩展: 52 篇
  过滤后: 42 篇
```

---

### 方法2: 完整稳定性测试

运行完整的测试套件：

```bash
cd "E:/整合/意图澄清+检索子图V1.1/tests"

# P0级别测试（必须通过，约10分钟）
python test_retrieval_stability.py --suite p0

# P1级别测试（包含P0+P1，约20分钟）
python test_retrieval_stability.py --suite p1

# 完整测试（包含P0+P1+P2，约30分钟）
python test_retrieval_stability.py --suite all
```

**预期输出**:
```
检索子图系统稳定性测试
================================================================================
测试套件: P0
开始时间: 2026-07-14 10:30:00

[TEST 1.1] 标准材料科学查询
...
[结果] ✅ PASS

测试报告
================================================================================
总测试数: 2
通过: 2
失败: 0
通过率: 100.0%
```

---

## 📚 测试套件说明

### P0 测试套件（必须通过）

**包含测试**:
- Test 1.1: 标准材料科学查询
- Test 3.1: 引用扩展成功率

**适用场景**: 
- 修复bug后的验证
- 发布前的必要检查
- 快速验证系统是否正常

**耗时**: 约10分钟

---

### P1 测试套件（重要）

**包含测试**:
- P0所有测试
- Test 1.2: 窄领域查询
- Test 1.3: 宽泛查询
- Test 2.3: 零结果处理

**适用场景**:
- 系统改动后的回归测试
- 定期稳定性检查
- 性能优化后验证

**耗时**: 约20分钟

---

### P2 测试套件（建议）

**包含测试**:
- P0 + P1所有测试
- Test 2.1: 极短查询
- Test 2.4: 特殊字符查询

**适用场景**:
- 全面的系统验证
- 发布前的完整测试
- 边界条件验证

**耗时**: 约30分钟

---

## 🎯 测试用例详解

### Test 1.1: 标准材料科学查询

**目的**: 验证正常流程

**查询**: "graphene mechanical properties"

**预期结果**:
- 搜索结果: 30-50篇
- 引用扩展: 40-80篇
- 过滤后: 20-60篇
- 下载成功: ≥5篇

**成功标准**:
- ✅ 所有Agent正常执行
- ✅ 无ERROR级别日志
- ✅ 最终至少5篇论文

---

### Test 1.2: 窄领域查询

**目的**: 测试小规模结果集

**查询**: "topological insulators Bi2Se3 quantum transport"

**预期结果**:
- 搜索结果: 10-20篇
- 引用扩展: 15-30篇
- 过滤后: 5-15篇

**成功标准**:
- ✅ 即使结果少也不报错
- ✅ 至少返回1篇论文

---

### Test 1.3: 宽泛查询

**目的**: 测试大规模结果集

**查询**: "machine learning materials"

**预期结果**:
- 搜索结果: 50+篇
- 引用扩展: 80+篇
- 过滤后: 40+篇

**成功标准**:
- ✅ 能处理大量论文
- ✅ 去重正确
- ✅ OUTPUT_TOP_N=None生效（下载所有）

---

### Test 2.3: 零结果处理

**目的**: 测试异常情况处理

**查询**: "xyzabcdef123nonsense materials quantum"

**预期结果**:
- 搜索结果: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**成功标准**:
- ✅ 不抛出异常
- ✅ 优雅返回空结果
- ✅ 有明确日志说明

---

### Test 3.1: 引用扩展成功率

**目的**: 验证引用扩展修复效果

**查询**: "deep learning materials discovery"

**预期结果**:
- cited_by成功率: ≥80%
- references成功率: ≥80%
- 总扩展: ≥30篇

**成功标准**:
- ✅ 引用扩展功能正常
- ✅ 无429错误或正确重试
- ✅ 种子论文都能获取引用

---

## 📊 测试报告

### 报告位置

```
E:/整合/意图澄清+检索子图V1.1/test_results/
└── stability_test_report.json
```

### 报告格式

```json
{
  "test_time": "2026-07-14T10:30:00",
  "summary": {
    "total": 5,
    "passed": 5,
    "failed": 0,
    "pass_rate": 100.0
  },
  "tests": [
    {
      "test_id": "1.1",
      "test_name": "标准材料科学查询",
      "success": true,
      "metrics": {
        "elapsed_time": 45.23,
        "papers_searched": 35,
        "citations_expanded": 52,
        "papers_filtered": 42,
        "papers_downloaded": 38
      },
      "warnings": []
    }
  ]
}
```

---

## 🔧 自定义测试

### 添加新测试用例

编辑 `test_retrieval_stability.py`:

```python
def run_custom_tests(tester):
    """自定义测试套件"""
    
    # 添加你的测试
    tester.run_test(
        test_id="9.1",
        test_name="我的自定义测试",
        input_state={
            "query": "your query here",
            "domain": "materials_science",
            "filters": {
                "year_start": 2020,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 10,
            "min_citations": 20,
            "no_errors": True
        }
    )
```

### 验证标准说明

`expected_behavior`支持的字段:

| 字段 | 类型 | 说明 |
|------|------|------|
| `min_papers` | int | 最少过滤后论文数 |
| `max_papers` | int | 最多过滤后论文数 |
| `min_citations` | int | 最少引用扩展数 |
| `allow_empty` | bool | 是否允许空结果 |
| `no_errors` | bool | 是否不允许错误 |

---

## ⚠️ 常见问题

### Q1: 测试失败怎么办？

**Step 1**: 查看错误信息
```bash
# 查看控制台输出
# 或查看报告文件
cat test_results/stability_test_report.json
```

**Step 2**: 检查常见原因
- ✅ 网络连接是否正常
- ✅ OpenAlex API是否可访问
- ✅ 配置文件是否正确
- ✅ 是否遇到429速率限制

**Step 3**: 重试
```bash
# 单独运行失败的测试
python quick_test.py --query "失败的查询"
```

---

### Q2: 测试很慢怎么办？

**原因**:
- 引用扩展需要多次API调用
- 网络延迟
- 429速率限制导致等待

**解决方案**:
1. 只运行P0测试（最快）
2. 配置OpenAlex API key（提高速率限制）
3. 分批运行测试

---

### Q3: 引用扩展成功率低？

**检查项**:
1. 网络是否稳定
2. 是否频繁遇到429错误
3. 查看日志中的具体错误

**优化**:
- 增加请求延迟
- 使用API key
- 分批测试

---

### Q4: 下载成功率低？

**正常范围**:
- 开放获取论文: 60-80%
- 所有论文: 40-60%

**原因**:
- 非开放获取论文没有免费PDF
- PDF链接失效
- 下载超时

**这是正常的**, 不是bug。

---

## 📈 性能基准

### 预期性能指标

| 阶段 | 耗时 | 说明 |
|------|------|------|
| Agent A (查询扩展) | 5-10秒 | LLM调用 |
| Agent B (论文搜索) | 10-20秒 | OpenAlex API |
| Agent C (引用扩展) | 40-120秒 | 多次API调用 |
| Agent E (过滤排序) | 5-10秒 | 本地计算 |
| Agent D (下载) | 取决于论文数 | 每篇约2-3秒 |
| **总计** | **60-180秒** | 1-3分钟 |

### 影响因素

- **查询复杂度**: 宽泛查询耗时更长
- **网络速度**: 影响API调用和下载
- **速率限制**: 429错误会增加等待时间
- **论文数量**: OUTPUT_TOP_N=None会下载所有，耗时更长

---

## 🎓 最佳实践

### 开发中测试

```bash
# 使用快速测试验证修改
python quick_test.py
```

### 提交前测试

```bash
# 运行P0测试确保基本功能正常
python test_retrieval_stability.py --suite p0
```

### 发布前测试

```bash
# 运行完整测试
python test_retrieval_stability.py --suite all
```

### 定期测试

```bash
# 每周运行一次P1测试
python test_retrieval_stability.py --suite p1
```

---

## 📝 测试记录模板

### 手动记录

```
测试日期: ________
测试人: ________
测试套件: P0 / P1 / P2 / ALL

测试结果:
- 总测试数: ____
- 通过: ____
- 失败: ____
- 通过率: ____%

失败测试:
1. Test ___ : ___________
   原因: ___________

性能:
- 平均耗时: ____ 秒
- 最慢测试: ____ 秒

备注:
_______________
```

---

## 🔗 相关文档

- **详细测试计划**: `STABILITY_TEST_PLAN.md`
- **引用扩展修复**: `../DOWNLOAD_STRATEGY_CHANGE.md`
- **项目结构**: `E:/整合/PROJECT_STRUCTURE_FINAL.md`

---

## 💡 提示

1. **首次运行**: 建议先用`quick_test.py`快速验证
2. **定期测试**: 每周运行P1测试保持稳定性
3. **修改后**: 必须运行P0测试验证
4. **发布前**: 运行完整测试（all）
5. **遇到问题**: 查看日志和报告文件

---

**文档状态**: ✅ 完成  
**最后更新**: 2026-07-14
