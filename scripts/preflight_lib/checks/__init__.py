"""Preflight check catalogue. Individual checks are added from EP-05 onwards."""

from __future__ import annotations

from ..registry import Registry
from .config_secret import CONFIG_SECRET_SPECS
from .docker import DOCKER_SPECS
from .hygiene import HYGIENE_SPECS
from .network import NETWORK_SPECS
from .ollama import OLLAMA_SPECS
from .precedence import PRECEDENCE_SPECS


def build_registry() -> Registry:
    """Return the registry for this build."""
    registry = Registry()
    for spec in (
        *CONFIG_SECRET_SPECS,
        *PRECEDENCE_SPECS,
        *DOCKER_SPECS,
        *HYGIENE_SPECS,
        *OLLAMA_SPECS,
        *NETWORK_SPECS,
    ):
        registry.register(spec)
    return registry
