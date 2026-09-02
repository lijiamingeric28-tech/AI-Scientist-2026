# 检索子图系统稳定性测试报告

**测试日期**: 2026-07-14  
**测试时间**: 09:08:17 - 09:12:41  
**测试套件**: ALL (P0 + P1 + P2)  
**执行人**: 自动化测试

---

## 执行摘要

**测试状态**: ❌ 未通过  
**总测试数**: 7  
**通过数**: 1  
**失败数**: 6  
**通过率**: 14.3%

---

## 关键发现

### ⚠️ 主要问题：OpenAlex API认证失败

所有测试（除Test 2.3）均失败，原因是**OpenAlex API搜索返回0篇论文**。

**问题根源**:
1. **API密钥问题**: 系统可能仍在使用错误的API密钥
2. **认证方式问题**: OpenAlex API的认证方式需要进一步确认

**影响**:
- 无法完成论文搜索
- 无法测试引用扩展
- 无法测试下载功能

---

## 测试详细结果

### P0 测试套件（必须通过）

#### ❌ Test 1.1: 标准材料科学查询

**查询**: "graphene mechanical properties"  
**状态**: FAIL  
**耗时**: 38.19秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇
- 下载成功: 0篇

**失败原因**:
- 论文数不足: 期望≥5, 实际0
- 引用扩展不足: 期望≥20, 实际0
- 结果为空但预期不为空

---

#### ❌ Test 3.1: 引用扩展成功率

**查询**: "deep learning materials discovery"  
**状态**: FAIL  
**耗时**: 27.39秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**失败原因**:
- 论文数不足: 期望≥10, 实际0
- 引用扩展不足: 期望≥30, 实际0
- 结果为空但预期不为空

---

### P1 测试套件（重要）

#### ❌ Test 1.2: 窄领域查询

**查询**: "topological insulators Bi2Se3 quantum transport"  
**状态**: FAIL  
**耗时**: 22.06秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**失败原因**:
- 论文数不足: 期望≥1, 实际0
- 结果为空但预期不为空

---

#### ❌ Test 1.3: 宽泛查询

**查询**: "machine learning materials"  
**状态**: FAIL  
**耗时**: 61.43秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**失败原因**:
- 论文数不足: 期望≥20, 实际0
- 结果为空但预期不为空

---

#### ✅ Test 2.3: 零结果处理

**查询**: "xyzabcdef123nonsense materials quantum"  
**状态**: PASS  
**耗时**: 24.68秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**成功原因**:
- 允许空结果（预期行为）
- 系统优雅处理了零结果情况
- 无异常或崩溃

---

### P2 测试套件（建议）

#### ❌ Test 2.1: 极短查询

**查询**: "graphene"  
**状态**: FAIL  
**耗时**: 20.76秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**失败原因**:
- 论文数不足: 期望≥5, 实际0
- 结果为空但预期不为空

---

#### ❌ Test 2.4: 特殊字符查询

**查询**: "Cu-Zn alloy (70/30) @ 300°C"  
**状态**: FAIL  
**耗时**: 40.48秒

**结果**:
- 搜索论文: 0篇
- 引用扩展: 0篇
- 过滤后: 0篇

**失败原因**:
- 论文数不足: 期望≥1, 实际0
- 结果为空但预期不为空

---

## 性能统计

| 指标 | 数值 |
|------|------|
| 平均耗时 | 33.57秒 |
| 最快测试 | 20.76秒 (Test 2.1) |
| 最慢测试 | 61.43秒 (Test 1.3) |
| 总耗时 | 235秒 (~4分钟) |

---

## 问题分析

### 1. OpenAlex API认证问题

**现象**:
- 所有正常查询都返回0篇论文
- 只有"零结果测试"通过（因为期望结果就是空）

**可能原因**:
1. **API密钥错误**
   - 配置文件中的密钥: `ZLwbEQ2B1nOALHLdeukZGr`
   - 可能被旧密钥 `M4nUEG1eVxi3ExIT6kwScT` 覆盖

2. **认证方式错误**
   - OpenAlex可能不使用 `api_key` 参数
   - 可能需要使用不同的认证方式

3. **API密钥失效**
   - 密钥可能已过期或无效
   - 需要重新申请密钥

**修复过程**:
1. ✅ 修改 `call_openalex_api.py` - 从Bearer token改为api_key参数
2. ✅ 更新 `openalex_config.py` - 使用正确的密钥
3. ✅ 复制 `.env` 文件到主项目
4. ❌ 仍然失败 - 需要进一步调查

---

### 2. 测试框架问题

**发现的问题**:
1. **emoji编码问题**
   - Windows GBK编码无法处理emoji字符
   - 已修复：移除所有emoji

2. **intent_params缺失**
   - 测试脚本未提供必需的 `intent_params`
   - 已修复：自动从query构造

3. **配置缓存问题**
   - Python进程缓存了旧配置
   - 需要重启进程才能生效

---

## 系统功能测试

### ✅ 已验证的功能

1. **错误处理**
   - 零结果优雅处理 ✅
   - 无异常崩溃 ✅

2. **流程完整性**
   - Agent A (查询扩展) 正常执行 ✅
   - Agent B (论文搜索) 正常调用API ✅
   - Agent C (引用扩展) 正确跳过空输入 ✅
   - Agent E (过滤排序) 正确处理空数据 ✅

3. **配置加载**
   - LLM配置正确加载 ✅
   - 环境变量正确读取 ✅

### ❌ 未验证的功能

由于API认证失败，以下功能未能测试：

1. **论文搜索功能**
   - OpenAlex API搜索
   - 结果解析
   - 元数据提取

2. **引用扩展功能**
   - cited_by (前向引用)
   - references (后向引用)
   - 种子论文选择

3. **过滤与排序**
   - 引用数过滤
   - 年份过滤
   - 评分计算
   - TOP N选择（OUTPUT_TOP_N=None）

4. **论文下载**
   - PDF下载
   - 文件保存
   - 下载成功率

---

## 修复建议

### 优先级1：解决API认证问题

**方案A：验证API密钥**
```bash
# 测试API密钥是否有效
curl "https://api.openalex.org/works?search=graphene&api_key=ZLwbEQ2B1nOALHLdeukZGr"
```

**方案B：使用邮箱认证**
```python
# 不使用api_key，只使用mailto
params["mailto"] = "lijiamingeric28@gmail.com"
# 移除 params["api_key"]
```

**方案C：申请新的API密钥**
- 访问 OpenAlex 官网
- 申请新的API密钥
- 更新配置文件

---

### 优先级2：简化测试用例

建议创建一个最小测试：

```python
# minimal_test.py
import requests

# 测试1: 不使用API密钥
response1 = requests.get(
    "https://api.openalex.org/works",
    params={
        "search": "graphene",
        "mailto": "lijiamingeric28@gmail.com"
    }
)
print(f"不使用密钥: {response1.status_code}")

# 测试2: 使用API密钥
response2 = requests.get(
    "https://api.openalex.org/works",
    params={
        "search": "graphene",
        "api_key": "ZLwbEQ2B1nOALHLdeukZGr",
        "mailto": "lijiamingeric28@gmail.com"
    }
)
print(f"使用密钥: {response2.status_code}")
```

---

### 优先级3：增强日志输出

在 `call_openalex_api.py` 中添加：

```python
logger.info(f"Request URL: {response.url}")  # 打印完整URL
logger.info(f"Response status: {response.status_code}")
logger.info(f"Response headers: {response.headers}")
if response.status_code != 200:
    logger.error(f"Response body: {response.text}")
```

---

## 下一步行动

### 立即行动

1. **验证API密钥**
   - 运行最小测试脚本
   - 确认密钥是否有效

2. **检查OpenAlex文档**
   - 确认正确的认证方式
   - 查看是否有API变更

3. **尝试无密钥方式**
   - 只使用 `mailto` 参数
   - 测试是否可以正常工作

### 后续测试

待API问题解决后：

1. **重新运行P0测试**
   - 验证基本功能

2. **运行完整测试套件**
   - 验证所有功能

3. **性能基准测试**
   - 记录正常耗时
   - 建立性能基线

---

## 附录

### A. 测试环境信息

```
操作系统: Windows 11
Python版本: 3.14
项目路径: E:/整合/意图澄清+检索子图V1.1
配置文件: .env, configs/openalex_config.py
```

### B. 配置信息

```python
# OpenAlex配置
OPENALEX_API_KEY = "ZLwbEQ2B1nOALHLdeukZGr"
OPENALEX_EMAIL = "lijiamingeric28@gmail.com"
OPENALEX_BASE_URL = "https://api.openalex.org/works"

# 输出配置
OUTPUT_TOP_N = None  # 下载所有过滤后的论文
```

### C. 相关文件

- 测试脚本: `tests/test_retrieval_stability.py`
- 测试报告: `tests/test_results/stability_test_report_full.json`
- 执行日志: `test_results/test_execution.log`
- 配置文件: `configs/constants.py`, `configs/openalex_config.py`

---

## 总结

**测试执行**: ✅ 完成  
**测试结果**: ❌ 未通过 (14.3% 通过率)  
**主要问题**: OpenAlex API认证失败  
**下一步**: 修复API认证问题后重新测试

**测试框架状态**: ✅ 正常  
**系统稳定性**: ✅ 良好（无崩溃）  
**功能覆盖**: ⚠️ 受限（API问题导致大部分功能未测试）

---

**报告生成时间**: 2026-07-14 09:20:00  
**报告版本**: v1.0
