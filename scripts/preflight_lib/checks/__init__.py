"""Preflight check catalogue. Individual checks are added from EP-05 onwards."""

from __future__ import annotations

from ..registry import Registry
from .config_secret import CONFIG_SECRET_SPECS


def build_registry() -> Registry:
    """Return the registry for this build."""
    registry = Registry()
    for spec in CONFIG_SECRET_SPECS:
        registry.register(spec)
    return registry
