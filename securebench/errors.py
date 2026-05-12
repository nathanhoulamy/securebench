"""Shared SecureBench exception types."""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a run config is invalid."""
