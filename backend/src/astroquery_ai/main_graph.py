"""Compatibility import for the single persistent dispatcher."""
from .runtime.main_graph import create_main_graph
from . import run_pipeline

__all__ = ["create_main_graph", "run_pipeline"]
