"""Check registry: ordered check specifications and profile resolution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .context import CheckContext
from .results import CheckResult, Severity

PHASE_PROFILES = tuple(f"phase{index}" for index in range(10))


class ProfileError(ValueError):
    """Raised for an unknown or unsupported profile name."""


@dataclass(frozen=True)
class CheckSpec:
    id: str
    title: str
    severity: Severity
    timeout: float
    runner: Callable[[CheckContext], Awaitable[CheckResult]]
    requires: str = "none"
    tags: tuple[str, ...] = field(default_factory=tuple)
    config_failure: bool = False


class Registry:
    """Ordered collection of check specifications."""

    def __init__(self) -> None:
        self._specs: dict[str, CheckSpec] = {}

    def register(self, spec: CheckSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"duplicate check id: {spec.id}")
        self._specs[spec.id] = spec

    def specs(self) -> tuple[CheckSpec, ...]:
        return tuple(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)


def resolve_profile(registry: Registry, profile: str) -> tuple[CheckSpec, ...]:
    """Return the checks for *profile*.

    Phase 0 is the base profile; later phases are placeholders that currently
    inherit every registered check.
    """
    if profile not in PHASE_PROFILES:
        valid = ", ".join(PHASE_PROFILES)
        raise ProfileError(f"unknown profile '{profile}'; valid profiles: {valid}")
    return registry.specs()
