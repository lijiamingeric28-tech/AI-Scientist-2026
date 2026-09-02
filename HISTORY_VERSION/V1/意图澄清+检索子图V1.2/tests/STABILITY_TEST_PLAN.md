# 检索子图系统稳定性测试方案

**创建日期**: 2026-07-14  
**测试范围**: 检索子图（Agent A-E）  
**排除范围**: 意图澄清子图（已测试通过）

---

## 测试目标

验证检索子图在以下场景下的稳定性：
1. ✅ 正常流程完整性
2. ✅ 异常情况处理
3. ✅ API限制和重试
4. ✅ 大规模数据处理
5. ✅ 边界条件测试

---

## 测试环境

### 前置条件
- OpenAlex API配置正确
- 邮箱: `lijiamingeric28@gmail.com`
- 网络连接正常
- 磁盘空间充足（>500MB）

### 配置状态
```python
# configs/constants.py
OUTPUT_TOP_N = None              # 下载所有过滤后的论文
MAX_SEED_PAPERS = 5              # 引用扩展种子数
MAX_CITED_BY_PER_SEED = 10       # 每个种子的前向引用数
MAX_REFERENCES_PER_SEED = 10     # 每个种子的后向引用数
FILTER_MIN_CITATION_COUNT = 3    # 最小引用数过滤
```

---

## 测试用例设计

### Test Suite 1: 正常流程测试

#### Test 1.1: 标准材料科学查询
**测试目的**: 验证完整流程的正常运行

**输入**:
```python
{
    "query": "graphene mechanical properties",
    "domain": "materials_science",
    "filters": {
        "year_start": 2020,
        "year_end": 2024,
        "min_citations": 10
    }
}
```

**预期行为**:
- Agent A: 成功扩展查询（生成3-5个变体）
- Agent B: 搜索到30-50篇论文
- Agent C: 选择TOP5种子，获取前后引用（约50-100篇）
- Agent E: 合并去重，过滤后30-80篇
- Agent D: 成功下载所有论文

**成功标准**:
- ✅ 无异常退出
- ✅ 每个Agent都有输出
- ✅ 最终下载至少10篇论文
- ✅ 日志无ERROR级别信息

**测试数据记录**:
```
搜索结果数: _____
引用扩展数: _____
过滤后数量: _____
下载成功数: _____
总耗时: _____秒
```

---

#### Test 1.2: 窄领域查询
**测试目的**: 验证小规模结果集的处理

**输入**:
```python
{
    "query": "topological insulators Bi2Se3 quantum transport",
    "domain": "materials_science",
    "filters": {
        "year_start": 2023,
        "year_end": 2024,
        "min_citations": 20
    }
}
```

**预期行为**:
- 搜索结果较少（10-20篇）
- 引用扩展也较少
- 过滤后可能<10篇
- 仍能正常完成流程

**成功标准**:
- ✅ 即使结果少也不报错
- ✅ 能正确处理<5篇种子的情况
- ✅ 下载至少1篇论文

---

#### Test 1.3: 宽泛查询
**测试目的**: 验证大规模结果集的处理

**输入**:
```python
{
    "query": "machine learning materials",
    "domain": "materials_science",
    "filters": {
        "year_start": 2020,
        "year_end": 2024,
        "min_citations": 5
    }
}
```

**预期行为**:
- 搜索结果很多（可能50+篇）
- 引用扩展后可能100+篇
- 过滤后仍有大量论文
- OUTPUT_TOP_N=None会下载所有

**成功标准**:
- ✅ 能处理大量论文
- ✅ 去重正确工作
- ✅ 下载不超时
- ✅ 内存占用合理

---

### Test Suite 2: 边界条件测试

#### Test 2.1: 极短查询
**测试目的**: 测试单词查询的处理

**输入**:
```python
{
    "query": "graphene",
    "domain": "materials_science"
}
```

**预期行为**:
- Agent A仍能扩展查询
- 结果可能过多，需要过滤

**成功标准**:
- ✅ 不因查询过短而失败
- ✅ 扩展后的查询更具体

---

#### Test 2.2: 极长查询
**测试目的**: 测试复杂查询的处理

**输入**:
```python
{
    "query": "first-principles density functional theory calculations of electronic band structure and optical properties of two-dimensional transition metal dichalcogenides for photovoltaic applications",
    "domain": "materials_science"
}
```

**预期行为**:
- Agent A能处理长查询
- 可能简化查询

**成功标准**:
- ✅ 不因查询过长而截断
- ✅ 扩展合理

---

#### Test 2.3: 零结果查询
**测试目的**: 测试无搜索结果的处理

**输入**:
```python
{
    "query": "xyzabcdef123nonsense materials",
    "domain": "materials_science"
}
```

**预期行为**:
- Agent B: 搜索返回0篇论文
- Agent C: 跳过引用扩展
- Agent E: 无可过滤内容
- Agent D: 无可下载内容

**成功标准**:
- ✅ 优雅处理空结果
- ✅ 不抛出异常
- ✅ 返回空结果集

---

#### Test 2.4: 特殊字符查询
**测试目的**: 测试特殊字符的处理

**输入**:
```python
{
    "query": "Cu-Zn alloy (70/30) @ 300°C",
    "domain": "materials_science"
}
```

**预期行为**:
- 正确转义特殊字符
- API调用不出错

**成功标准**:
- ✅ 特殊字符不导致API错误
- ✅ 能正常搜索

---

### Test Suite 3: 引用扩展专项测试

#### Test 3.1: 引用扩展成功率
**测试目的**: 验证引用扩展功能的修复效果

**输入**: 使用Test 1.1的查询

**测试点**:
1. **前向引用（cited_by）**
   - TOP5种子论文都能获取前向引用
   - 每个种子至少获取5篇
   - 无429错误或合理重试

2. **后向引用（references）**
   - TOP5种子论文都能获取后向引用
   - 每个种子至少获取5篇
   - 无API错误

**成功标准**:
- ✅ cited_by成功率 ≥ 80%
- ✅ references成功率 ≥ 80%
- ✅ 总扩展论文数 ≥ 40篇

---

#### Test 3.2: 种子论文选择
**测试目的**: 验证种子论文选择逻辑

**测试方法**:
```python
# 手动检查日志
# 验证选择的5篇种子论文特征
```

**验证点**:
- ✅ 按引用数降序选择
- ✅ 偏好开放获取论文
- ✅ 选择的种子都有有效的work_id

---

#### Test 3.3: 引用扩展去重
**测试目的**: 验证引用论文不与搜索结果重复

**测试方法**:
1. 记录Agent B搜索的论文ID
2. 记录Agent C扩展的论文ID
3. 在Agent E合并后检查去重效果

**成功标准**:
- ✅ 重复论文被正确去除
- ✅ 去重后数量 ≤ (搜索数 + 扩展数)

---

### Test Suite 4: 过滤与排序测试

#### Test 4.1: 引用数过滤
**测试目的**: 验证低引用论文被过滤

**测试方法**:
```python
# 使用较高的过滤标准
filters = {
    "min_citations": 50  # 提高到50
}
```

**验证点**:
- ✅ 过滤后所有论文引用数 ≥ 50
- ✅ 过滤比例合理

---

#### Test 4.2: 年份过滤
**测试目的**: 验证年份范围过滤

**测试方法**:
```python
filters = {
    "year_start": 2023,
    "year_end": 2023  # 只要2023年
}
```

**验证点**:
- ✅ 过滤后所有论文年份在范围内
- ✅ 考虑了FILTER_YEAR_RELAXATION=2的容差

---

#### Test 4.3: 评分逻辑
**测试目的**: 验证论文评分的合理性

**测试方法**:
1. 记录排名前5的论文
2. 验证评分计算

**验证点**:
- ✅ 高引论文得分较高
- ✅ 新论文有时效性加分
- ✅ 综合评分合理

---

#### Test 4.4: 无限制下载
**测试目的**: 验证OUTPUT_TOP_N=None的效果

**测试方法**:
使用宽泛查询，确保过滤后>25篇

**验证点**:
- ✅ 下载数量 > 25
- ✅ 下载数量 = 过滤后数量
- ✅ 所有论文都尝试下载

---

### Test Suite 5: 论文下载测试

#### Test 5.1: 下载成功率
**测试目的**: 验证论文下载的成功率

**测试方法**:
统计下载成功/失败的论文数

**成功标准**:
- ✅ 开放获取论文下载成功率 ≥ 60%
- ✅ 失败原因有明确日志
- ✅ 重试机制正常工作

---

#### Test 5.2: 下载并发控制
**测试目的**: 验证并发下载不超限

**配置**:
```python
DOWNLOAD_MAX_CONCURRENT = 3
```

**验证点**:
- ✅ 同时下载不超过3个
- ✅ 不触发服务器限制

---

#### Test 5.3: 文件完整性
**测试目的**: 验证下载的PDF完整性

**测试方法**:
```python
# 检查下载的文件
for pdf in downloaded_pdfs:
    assert file_size > MIN_FILE_SIZE
    assert file_size < MAX_FILE_SIZE
    assert is_valid_pdf(pdf)
```

**成功标准**:
- ✅ 文件大小在合理范围
- ✅ PDF文件可打开
- ✅ 无损坏文件

---

#### Test 5.4: 下载重试
**测试目的**: 验证下载失败后的重试机制

**测试方法**:
模拟网络不稳定（通过日志观察）

**验证点**:
- ✅ 失败后自动重试
- ✅ 最多重试DOWNLOAD_MAX_RETRIES次
- ✅ 重试有延迟

---

### Test Suite 6: 异常处理测试

#### Test 6.1: API限流处理
**测试目的**: 验证429错误的处理

**触发方式**:
连续运行多次测试

**预期行为**:
- 捕获429错误
- 等待后重试
- 日志记录限流信息

**成功标准**:
- ✅ 不因429而崩溃
- ✅ 自动恢复继续执行

---

#### Test 6.2: 网络超时处理
**测试目的**: 验证超时的处理

**预期行为**:
- 超时后重试
- 最终失败返回空结果

**成功标准**:
- ✅ 超时不导致程序崩溃
- ✅ 有明确超时日志

---

#### Test 6.3: 无效API响应
**测试目的**: 验证异常API响应的处理

**可能场景**:
- JSON解析失败
- 缺少必需字段
- 数据格式错误

**成功标准**:
- ✅ 捕获异常
- ✅ 记录详细错误信息
- ✅ 继续处理其他论文

---

#### Test 6.4: 磁盘空间不足
**测试目的**: 验证磁盘空间不足的处理

**测试方法**:
（手动测试，限制下载目录空间）

**预期行为**:
- 捕获磁盘空间异常
- 停止下载
- 保存已下载的文件

---

### Test Suite 7: 性能测试

#### Test 7.1: 执行时间测试
**测试目的**: 测量各阶段耗时

**测试方法**:
```python
# 记录每个Agent的执行时间
times = {
    "expand_query": 0,
    "search_papers": 0,
    "citation_expansion": 0,
    "filter_rank": 0,
    "download_papers": 0
}
```

**性能基准**:
- Agent A (查询扩展): < 10秒
- Agent B (论文搜索): < 30秒
- Agent C (引用扩展): < 120秒（取决于种子数）
- Agent E (过滤排序): < 10秒
- Agent D (下载): 取决于论文数

---

#### Test 7.2: 内存占用测试
**测试目的**: 监控内存使用

**测试方法**:
```python
import psutil
process = psutil.Process()
memory_usage = process.memory_info().rss / 1024 / 1024  # MB
```

**成功标准**:
- ✅ 内存占用 < 500MB
- ✅ 无内存泄漏

---

#### Test 7.3: 大规模数据测试
**测试目的**: 测试处理100+篇论文的能力

**测试方法**:
使用非常宽泛的查询

**验证点**:
- ✅ 能处理100+篇论文
- ✅ 去重效率高
- ✅ 不超时

---

### Test Suite 8: 数据质量测试

#### Test 8.1: 元数据完整性
**测试目的**: 验证论文元数据的完整性

**验证点**:
```python
for paper in papers:
    assert paper.id is not None
    assert paper.title is not None
    assert paper.year is not None
    assert paper.citation_count >= 0
```

---

#### Test 8.2: 相关性验证
**测试目的**: 人工验证搜索结果的相关性

**测试方法**:
1. 使用明确的查询
2. 检查前10篇论文的标题
3. 评估相关性

**成功标准**:
- ✅ 前10篇至少7篇相关

---

#### Test 8.3: 去重准确性
**测试目的**: 验证去重的准确性

**测试方法**:
检查最终论文列表中是否有重复

**验证点**:
- ✅ 无重复的work_id
- ✅ 无重复的DOI

---

### Test Suite 9: 配置测试

#### Test 9.1: OUTPUT_TOP_N配置
**测试目的**: 验证不同OUTPUT_TOP_N值的效果

**测试场景**:
1. `OUTPUT_TOP_N = None` → 下载所有
2. `OUTPUT_TOP_N = 10` → 下载10篇
3. `OUTPUT_TOP_N = 50` → 下载50篇

**验证点**:
- ✅ 配置正确生效
- ✅ 下载数量符合配置

---

#### Test 9.2: 引用扩展配置
**测试目的**: 验证引用扩展参数的效果

**测试场景**:
调整`MAX_CITED_BY_PER_SEED`和`MAX_REFERENCES_PER_SEED`

**验证点**:
- ✅ 获取的引用数符合配置

---

### Test Suite 10: 集成测试

#### Test 10.1: 完整流程端到端
**测试目的**: 验证完整流程的稳定性

**测试方法**:
连续运行5次完整流程

**成功标准**:
- ✅ 5次都成功完成
- ✅ 结果一致性合理
- ✅ 无内存泄漏

---

#### Test 10.2: 多查询测试
**测试目的**: 测试连续多个不同查询

**测试数据**:
```python
queries = [
    "graphene mechanical properties",
    "perovskite solar cells",
    "topological insulators",
    "quantum dots synthesis",
    "metallic glass formation"
]
```

**成功标准**:
- ✅ 所有查询都成功
- ✅ 结果不互相干扰

---

## 测试执行计划

### 优先级分类

**P0 - 必须通过**:
- Test 1.1: 标准材料科学查询
- Test 3.1: 引用扩展成功率
- Test 4.4: 无限制下载
- Test 5.1: 下载成功率
- Test 6.1: API限流处理

**P1 - 重要**:
- Test 1.2, 1.3: 窄领域和宽泛查询
- Test 2.3: 零结果处理
- Test 3.2, 3.3: 种子选择和去重
- Test 4.1, 4.2: 过滤逻辑
- Test 6.2, 6.3: 超时和异常处理

**P2 - 建议**:
- Test 2.1, 2.2, 2.4: 边界条件
- Test 5.2, 5.3: 并发和文件完整性
- Test 7.1, 7.2: 性能测试
- Test 8.1, 8.2: 数据质量

**P3 - 可选**:
- Test 7.3: 大规模数据
- Test 10.2: 多查询测试

---

## 测试脚本模板

### 自动化测试脚本

```python
"""
检索子图系统稳定性测试
"""

import sys
from pathlib import Path
import time
import json

# 添加项目路径
project_path = Path(__file__).parent
sys.path.insert(0, str(project_path))

from pipeline.retrieval.graph import create_retrieval_graph
from state.retrieval_state import RetrievalState


class RetrievalSystemTester:
    """检索子图系统测试器"""
    
    def __init__(self):
        self.graph = create_retrieval_graph()
        self.results = []
    
    def run_test(self, test_name, input_state, expected_behavior):
        """
        运行单个测试
        
        Args:
            test_name: 测试名称
            input_state: 输入状态
            expected_behavior: 预期行为（用于验证）
        
        Returns:
            测试结果字典
        """
        print(f"\n{'='*80}")
        print(f"[TEST] {test_name}")
        print(f"{'='*80}")
        
        result = {
            "test_name": test_name,
            "success": False,
            "start_time": time.time(),
            "errors": [],
            "metrics": {}
        }
        
        try:
            # 执行检索流程
            start = time.time()
            output = self.graph.invoke(input_state)
            elapsed = time.time() - start
            
            # 记录指标
            result["metrics"] = {
                "elapsed_time": elapsed,
                "papers_searched": len(output.get("papers", [])),
                "citations_expanded": len(output.get("citation_papers", [])),
                "papers_filtered": len(output.get("filtered_papers", [])),
                "papers_downloaded": len(output.get("downloaded_papers", []))
            }
            
            # 验证预期行为
            result["success"] = self.validate_output(output, expected_behavior)
            
            print(f"\n[RESULT] {'PASS' if result['success'] else 'FAIL'}")
            print(f"耗时: {elapsed:.2f}秒")
            print(f"指标: {result['metrics']}")
            
        except Exception as e:
            result["errors"].append(str(e))
            print(f"\n[ERROR] {e}")
        
        finally:
            result["end_time"] = time.time()
            self.results.append(result)
        
        return result
    
    def validate_output(self, output, expected):
        """
        验证输出是否符合预期
        
        Args:
            output: 实际输出
            expected: 预期行为
        
        Returns:
            bool: 是否通过验证
        """
        # 基本验证
        if not output:
            return False
        
        # 验证必需字段
        required_fields = ["papers", "filtered_papers"]
        for field in required_fields:
            if field not in output:
                return False
        
        # 验证数量
        if "min_papers" in expected:
            if len(output.get("filtered_papers", [])) < expected["min_papers"]:
                return False
        
        # 验证无错误
        if "no_errors" in expected and expected["no_errors"]:
            # 检查是否有错误日志
            pass
        
        return True
    
    def generate_report(self):
        """生成测试报告"""
        print(f"\n{'='*80}")
        print("测试报告")
        print(f"{'='*80}")
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r["success"])
        
        print(f"\n总测试数: {total}")
        print(f"通过: {passed}")
        print(f"失败: {total - passed}")
        print(f"通过率: {passed/total*100:.1f}%")
        
        print(f"\n详细结果:")
        for r in self.results:
            status = "[PASS]" if r["success"] else "[FAIL]"
            print(f"  {status} {r['test_name']}")
            if r["errors"]:
                for err in r["errors"]:
                    print(f"       错误: {err}")
        
        # 保存JSON报告
        report_file = Path("test_results/stability_test_report.json")
        report_file.parent.mkdir(exist_ok=True)
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"\n详细报告已保存: {report_file}")


def main():
    """主测试函数"""
    tester = RetrievalSystemTester()
    
    # Test 1.1: 标准材料科学查询
    tester.run_test(
        test_name="Test 1.1: 标准材料科学查询",
        input_state={
            "query": "graphene mechanical properties",
            "domain": "materials_science",
            "filters": {
                "year_start": 2020,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 10,
            "no_errors": True
        }
    )
    
    # Test 1.2: 窄领域查询
    tester.run_test(
        test_name="Test 1.2: 窄领域查询",
        input_state={
            "query": "topological insulators Bi2Se3 quantum transport",
            "domain": "materials_science",
            "filters": {
                "year_start": 2023,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 1,
            "no_errors": True
        }
    )
    
    # Test 2.3: 零结果查询
    tester.run_test(
        test_name="Test 2.3: 零结果查询",
        input_state={
            "query": "xyzabcdef123nonsense materials",
            "domain": "materials_science"
        },
        expected_behavior={
            "no_errors": True
        }
    )
    
    # 生成报告
    tester.generate_report()


if __name__ == "__main__":
    main()
```

---

## 测试数据记录表

### 标准测试记录

| Test ID | 测试名称 | 状态 | 搜索数 | 扩展数 | 过滤数 | 下载数 | 耗时 | 备注 |
|---------|---------|------|-------|-------|-------|-------|------|------|
| 1.1 | 标准查询 | | | | | | | |
| 1.2 | 窄领域 | | | | | | | |
| 1.3 | 宽泛查询 | | | | | | | |
| 2.3 | 零结果 | | | | | | | |
| 3.1 | 引用扩展 | | | | | | | |

---

## 问题追踪

### 发现的问题

| 问题ID | 严重程度 | 问题描述 | 复现步骤 | 状态 |
|-------|---------|---------|---------|------|
| | | | | |

---

## 测试总结模板

```
测试执行时间: ____
测试环境: ____
执行人: ____

总测试数: ____
通过: ____
失败: ____
通过率: ____%

关键发现:
1. 
2. 
3. 

建议优化:
1. 
2. 
3. 
```

---

**测试文档状态**: ✅ 已完成  
**下一步**: 执行测试并记录结果
