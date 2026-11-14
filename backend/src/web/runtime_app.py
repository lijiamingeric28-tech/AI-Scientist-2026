"""Compatibility factory; no second HTTP implementation."""
from astroquery_ai.api.http import create_app

__all__ = ["create_app"]
