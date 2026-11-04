"""Preflight check catalogue. Individual checks are added from EP-05 onwards."""

from __future__ import annotations

from ..registry import Registry


def build_registry() -> Registry:
    """Return the registry for this build (empty until check groups land)."""
    return Registry()
