"""Result model shared by checks, runner and reporters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"
    UNVERIFIED = "UNVERIFIED"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check. ``detail`` must already be secret-free."""

    status: Status
    detail: str = ""
    duration_ms: int = 0
    error_code: str | None = None
