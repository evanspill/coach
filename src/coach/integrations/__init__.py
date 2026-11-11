"""Data sources. Each implements an ABC from base.py and returns normalized models, never raw JSON."""

from coach.integrations.base import Sources, get_sources

__all__ = ["Sources", "get_sources"]
