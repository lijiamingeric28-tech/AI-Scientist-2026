"""
项目验证脚本

检查项目结构是否完整
"""

import os
from pathlib import Path


def check_structure():
    """检查项目结构"""
    root = Path(__file__).parent.parent

    required_files = [
        "langgraph.json",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
        ".gitignore",
        "README.md",
        "main_graph/graph.py",
        "main_graph/state.py",
        "main_graph/wrappers.py",
        "subgraphs/intent_clarification/graph.py",
        "subgraphs/intent_clarification/state.py",
        "subgraphs/retrieval/graph.py",
        "subgraphs/retrieval/state.py",
        "subgraphs/extraction/graph.py",
        "subgraphs/extraction/state.py",
        "subgraphs/quality/graph.py",
        "subgraphs/quality/state.py",
    ]

    print("检查项目结构...")
    print("=" * 60)

    missing = []
    for file_path in required_files:
        full_path = root / file_path
        if full_path.exists():
            print(f"[OK] {file_path}")
        else:
            print(f"[MISSING] {file_path}")
            missing.append(file_path)

    print("=" * 60)
    if missing:
        print(f"\n缺失 {len(missing)} 个文件")
        return False
    else:
        print("\n[SUCCESS] 项目结构完整")
        return True


if __name__ == "__main__":
    check_structure()
