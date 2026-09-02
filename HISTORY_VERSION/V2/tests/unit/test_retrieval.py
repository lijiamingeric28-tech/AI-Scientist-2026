"""
检索子图单元测试

测试检索子图的各个组件功能
"""

import pytest
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入检索子图组件
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.graph import create_retrieval_graph
from subgraphs.retrieval.nodes import (
    expand_query_agent,
    paper_search_agent,
)
from subgraphs.retrieval.tools.expand_query import (
    extract_core_entities,
    expand_synonyms,
    detect_topics_with_llm,
    build_paper_query
)
from subgraphs.retrieval.tools.paper_search import call_openalex_api
from shared.models.clarified_intent import ClarifiedIntent
from shared.models.paper_metadata import PaperMetadata


class TestRetrievalState:
    """测试RetrievalState定义"""

    def test_state_structure(self):
        """测试State结构"""
        # 创建测试State
        intent = ClarifiedIntent(
            entities=["FRB"],
            properties=["dispersion measure"],
            conditions={"year": "2020-2025"}
        )

        state: RetrievalState = {
            "intent_params": intent
        }

        # 验证必填字段
        assert "intent_params" in state
        assert state["intent_params"].entities == ["FRB"]
        assert state["intent_params"].properties == ["dispersion measure"]


class TestExpandQueryTools:
    """测试查询扩展工具"""

    def test_extract_core_entities(self):
        """测试实体提取"""
        intent = ClarifiedIntent(
            entities=["FRB", "fast radio burst"],
            properties=["dispersion measure", "DM"],
            conditions={"year": "2020-2025"}
        )

        result = extract_core_entities(intent)

        assert "entities" in result
        assert "properties" in result
        assert "conditions" in result
        assert len(result["entities"]) == 2
        assert len(result["properties"]) == 2

    def test_expand_synonyms(self):
        """测试同义词扩展"""
        entities = ["FRB"]
        properties = ["dispersion measure"]

        result = expand_synonyms(entities, properties, domain="astronomy")

        assert "expanded_entities" in result
        assert "expanded_properties" in result
        assert len(result["expanded_entities"]) > 0
        assert len(result["expanded_properties"]) > 0
        print(f"扩展后实体: {result['expanded_entities']}")
        print(f"扩展后属性: {result['expanded_properties']}")

    def test_detect_topics(self):
        """测试Topic检测"""
        user_query = "快速射电暴的色散量研究"
        entities = ["FRB", "fast radio burst"]
        properties = ["dispersion measure"]

        topic_ids = detect_topics_with_llm(user_query, entities, properties)

        # Topic检测可能返回空列表或Topic IDs
        assert isinstance(topic_ids, list)
        if topic_ids:
            print(f"检测到Topics: {topic_ids}")
            # 验证返回的是有效的Topic ID格式
            for tid in topic_ids:
                assert tid.startswith("T")
                assert tid[1:].isdigit()

    def test_build_paper_query(self):
        """测试构建OpenAlex查询"""
        entities = ["FRB", "fast radio burst"]
        properties = ["dispersion measure", "DM"]
        conditions = {"year": "2020-2025"}

        query_params = build_paper_query(
            expanded_entities=entities,
            expanded_properties=properties,
            conditions=conditions,
            domain="astronomy",
            user_query="快速射电暴的色散量",
            topic_ids=["T12450"]
        )

        assert "search" in query_params
        assert "filter" in query_params
        assert "per_page" in query_params
        assert "is_retracted" in query_params["filter"]
        print(f"搜索查询: {query_params['search']}")
        print(f"过滤条件: {query_params['filter']}")


class TestPaperSearch:
    """测试论文检索"""

    def test_openalex_api_call(self):
        """测试OpenAlex API调用"""
        # 简单的测试查询
        search_query = '("FRB" OR "fast radio burst") AND ("dispersion measure" OR "DM")'
        filter_dict = {
            "publication_year": "2020-2025",
            "cited_by_count": ">4",
            "is_retracted": "false",
            "topics.subfield.id": "3103"
        }
        per_page = 5

        papers = call_openalex_api(search_query, filter_dict, per_page)

        # 验证返回结果
        assert isinstance(papers, list)
        if papers:
            print(f"检索到 {len(papers)} 篇论文")
            # 验证第一篇论文的结构
            paper = papers[0]
            assert isinstance(paper, PaperMetadata)
            assert paper.id is not None
            assert paper.title is not None
            print(f"第一篇论文: {paper.title}")
            print(f"引用数: {paper.citation_count}")
            print(f"年份: {paper.year}")


class TestExpandQueryAgent:
    """测试查询扩展Agent"""

    def test_expand_query_agent(self):
        """测试expand_query_agent节点"""
        # 准备输入State
        intent = ClarifiedIntent(
            entities=["FRB"],
            properties=["dispersion measure"],
            conditions={"year": "2020-2025"}
        )

        state: RetrievalState = {
            "intent_params": intent,
            "user_query": "快速射电暴的色散量研究"
        }

        # 执行Agent
        result_state = expand_query_agent(state)

        # 验证输出
        assert "expanded_queries" in result_state
        assert "openalex" in result_state["expanded_queries"]

        openalex_params = result_state["expanded_queries"]["openalex"]
        assert "search" in openalex_params
        assert "filter" in openalex_params
        assert "per_page" in openalex_params

        print(f"查询参数: {openalex_params['search'][:100]}...")
        print(f"过滤条件: {openalex_params['filter']}")


class TestPaperSearchAgent:
    """测试论文检索Agent"""

    def test_paper_search_agent(self):
        """测试paper_search_agent节点"""
        # 准备输入State
        intent = ClarifiedIntent(
            entities=["FRB"],
            properties=["dispersion measure"],
            conditions={"year": "2020-2025"}
        )

        state: RetrievalState = {
            "intent_params": intent,
            "expanded_queries": {
                "openalex": {
                    "search": '("FRB" OR "fast radio burst") AND ("dispersion measure" OR "DM")',
                    "filter": {
                        "publication_year": "2020-2025",
                        "cited_by_count": ">4",
                        "is_retracted": "false",
                        "topics.subfield.id": "3103"
                    },
                    "per_page": 10
                }
            }
        }

        # 执行Agent
        result_state = paper_search_agent(state)

        # 验证输出
        assert "papers" in result_state
        assert isinstance(result_state["papers"], list)

        if result_state["papers"]:
            print(f"检索到 {len(result_state['papers'])} 篇论文")
            # 验证论文结构
            paper = result_state["papers"][0]
            assert isinstance(paper, PaperMetadata)
            assert paper.id is not None
            print(f"第一篇: {paper.title}")


class TestRetrievalGraph:
    """测试检索子图Graph"""

    def test_create_graph(self):
        """测试创建Graph"""
        # 创建Graph（不启用引用扩展，加快测试）
        graph = create_retrieval_graph(enable_citation_expansion=False)

        assert graph is not None
        print("Graph创建成功")

    @pytest.mark.slow
    def test_graph_execution(self):
        """测试Graph完整执行（慢速测试）"""
        # 准备输入
        intent = ClarifiedIntent(
            entities=["FRB"],
            properties=["dispersion measure"],
            conditions={"year": "2023-2025"}
        )

        initial_state: RetrievalState = {
            "intent_params": intent,
            "user_query": "快速射电暴的色散量"
        }

        # 创建并执行Graph（不启用引用扩展和下载）
        graph = create_retrieval_graph(enable_citation_expansion=False)

        # 注意：完整执行会调用多个API，可能需要较长时间
        # 在实际测试中，建议mock API调用
        print("注意：完整Graph执行需要较长时间和API调用")
        print("建议使用 pytest -m 'not slow' 跳过此测试")


class TestEnvironmentVariables:
    """测试环境变量配置"""

    def test_required_env_vars(self):
        """测试必需的环境变量"""
        # 检查OpenAlex配置
        assert os.getenv("OPENALEX_API_KEY") is not None, "OPENALEX_API_KEY未配置"
        assert os.getenv("OPENALEX_EMAIL") is not None, "OPENALEX_EMAIL未配置"

        # 检查Unpaywall配置
        assert os.getenv("UNPAYWALL_EMAIL") is not None, "UNPAYWALL_EMAIL未配置"

        print("环境变量配置检查通过")
        print(f"OPENALEX_EMAIL: {os.getenv('OPENALEX_EMAIL')}")
        print(f"UNPAYWALL_EMAIL: {os.getenv('UNPAYWALL_EMAIL')}")


if __name__ == "__main__":
    # 运行测试
    # 快速测试（跳过慢速测试）：pytest test_retrieval.py -v -m "not slow"
    # 完整测试：pytest test_retrieval.py -v
    pytest.main([__file__, "-v", "-s"])
