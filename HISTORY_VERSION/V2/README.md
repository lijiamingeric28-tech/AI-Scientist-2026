# Scientific Data Pipeline

基于LangGraph的多智能体科学数据处理管道

## 项目结构

```
scientific_data_pipeline/
├── config/                    # 配置文件
├── shared/                    # 共享组件
├── subgraphs/                 # 四个子图
│   ├── intent_clarification/  # 子图1：意图澄清
│   ├── retrieval/             # 子图2：检索
│   ├── extraction/            # 子图3：提取
│   └── quality/               # 子图4：质检
├── main_graph/                # 主图
├── data/                      # 数据存储
└── tests/                     # 测试
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑.env填入必要的API密钥
```

### 3. 运行管道

```bash
python scripts/run_pipeline.py
```

## 开发指南

### 子图开发规范

每个子图必须包含：
- `graph.py` - 子图定义和编译函数
- `state.py` - State类型定义
- `nodes/` - 节点函数实现

### 测试

```bash
pytest tests/
```

## 迁移状态

- [ ] 子图1：意图澄清
- [ ] 子图2：检索
- [ ] 子图3：提取
- [ ] 子图4：质检
- [ ] 主图集成

## 文档

详见各子图目录下的README.md
