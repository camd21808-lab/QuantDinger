"""Sequential check runner and exit-code classification."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Sequence

from .context import CheckContext
from .registry import CheckSpec
from .results import CheckResult, Severity, Status

CheckOutcome = tuple[CheckSpec, CheckResult]


def effective_status(spec: CheckSpec, result: CheckResult) -> Status:
    """Apply severity rules: warning FAIL -> WARN, critical SKIP -> UNVERIFIED."""
    if spec.severity == Severity.WARNING and result.status in (Status.FAIL, Status.WARN):
        return Status.WARN
    if spec.severity == Severity.CRITICAL and result.status == Status.SKIP:
        return Status.UNVERIFIED
    return result.status


def classify_exit_code(outcomes: Sequence[CheckOutcome]) -> int:
    """Return 2 for config-class failures, 1 for critical problems, else 0."""
    for spec, result in outcomes:
        if spec.config_failure and result.status == Status.FAIL:
            return 2
    for spec, result in outcomes:
        if spec.severity == Severity.CRITICAL and effective_status(spec, result) in (
            Status.FAIL,
            Status.UNVERIFIED,
        ):
            return 1
    return 0


async def run_specs(specs: Sequence[CheckSpec], context: CheckContext) -> list[CheckOutcome]:
    """Run checks sequentially in registry order, preserving that order in output."""
    outcomes: list[CheckOutcome] = []
    for spec in specs:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(spec.runner(context), timeout=spec.timeout)
        except asyncio.TimeoutError:
            result = CheckResult(
                status=Status.FAIL, detail=f"timeout after {spec.timeout:g}s"
            )
        except Exception as exc:  # noqa: BLE001 - report type only, never the message
            result = CheckResult(
                status=Status.FAIL, detail=f"check error ({type(exc).__name__})"
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = replace(
            result,
            detail=context.sanitizer.redact(result.detail),
            duration_ms=duration_ms,
        )
        outcomes.append((spec, result))
    return outcomes
