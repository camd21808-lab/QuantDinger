"""Check runner: per-check timeout, global budget, concurrency and exit codes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Sequence

from .context import CheckContext
from .registry import CheckSpec
from .results import CheckResult, Severity, Status

DEFAULT_BUDGET_SECONDS = 180.0
DEFAULT_MAX_CONCURRENCY = 4

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


def _budget_exhausted_result(spec: CheckSpec) -> CheckResult:
    if spec.severity == Severity.WARNING:
        return CheckResult(
            status=Status.SKIP,
            detail=f"budget exhausted before warning check {spec.id}",
        )
    return CheckResult(
        status=Status.UNVERIFIED,
        detail=f"budget exhausted before critical check {spec.id}",
    )


async def _run_one(
    spec: CheckSpec,
    context: CheckContext,
    deadline: float,
    clock,  # type: ignore[no-untyped-def]
) -> CheckOutcome:
    remaining = deadline - clock()
    if remaining <= 0:
        result = _budget_exhausted_result(spec)
        return spec, replace(result, detail=context.sanitizer.redact(result.detail))

    started = time.perf_counter()
    effective_timeout = min(spec.timeout, remaining)
    budget_capped = remaining < spec.timeout
    try:
        result = await asyncio.wait_for(spec.runner(context), timeout=effective_timeout)
    except asyncio.TimeoutError:
        if budget_capped:
            result = _budget_exhausted_result(spec)
        else:
            result = CheckResult(
                status=Status.FAIL, detail=f"timeout after {effective_timeout:g}s"
            )
    except Exception as exc:  # noqa: BLE001 - report type only, never the message
        result = CheckResult(
            status=Status.FAIL, detail=f"check error ({type(exc).__name__})"
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return spec, replace(
        result,
        detail=context.sanitizer.redact(result.detail),
        duration_ms=duration_ms,
    )


async def run_specs(
    specs: Sequence[CheckSpec],
    context: CheckContext,
    *,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    clock=time.monotonic,
) -> list[CheckOutcome]:
    """Run checks in registry order: local -> ollama (serial) -> network (bounded).

    Output is always returned in registry order, independent of completion order.
    """
    deadline = clock() + budget_seconds
    outcomes: dict[str, CheckOutcome] = {}

    local = [s for s in specs if "network" not in s.tags and "ollama" not in s.tags]
    ollama = [s for s in specs if "ollama" in s.tags]
    network = [s for s in specs if "network" in s.tags and "ollama" not in s.tags]

    for spec in local:
        outcomes[spec.id] = await _run_one(spec, context, deadline, clock)
    for spec in ollama:
        outcomes[spec.id] = await _run_one(spec, context, deadline, clock)

    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_network(spec: CheckSpec) -> None:
        async with semaphore:
            outcomes[spec.id] = await _run_one(spec, context, deadline, clock)

    if network:
        await asyncio.gather(*(run_network(spec) for spec in network))

    return [outcomes[spec.id] for spec in specs]
