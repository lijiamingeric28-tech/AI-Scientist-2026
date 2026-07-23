"""configs/ — 配置文件解析"""
import os, yaml

def load_yaml(filename: str) -> dict:
    config_dir = os.path.dirname(__file__)
    filepath = os.path.join(config_dir, filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
