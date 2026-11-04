"""EP-11: per-check timeout, global budget, concurrency limit, fail-continue.

Timings are scaled down (injected budget / short sleeps) so the suite stays fast;
the production default budget is asserted separately.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.runner import (  # noqa: E402
    DEFAULT_BUDGET_SECONDS,
    classify_exit_code,
    run_specs,
)
from preflight_lib.sanitizer import Sanitizer  # noqa: E402


def make_context(tmp_path: Path) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())


def hanging_spec(check_id: str, timeout: float) -> CheckSpec:
    async def runner(_ctx: CheckContext) -> CheckResult:
        await asyncio.sleep(999)
        return CheckResult(Status.PASS)

    return CheckSpec(
        id=check_id, title=check_id, severity=Severity.CRITICAL,
        timeout=timeout, runner=runner,
    )


def sleep_spec(
    check_id: str,
    delay: float,
    *,
    status: Status = Status.PASS,
    severity: Severity = Severity.CRITICAL,
    tags: tuple[str, ...] = (),
    counter: list[int] | None = None,
    peak: list[int] | None = None,
) -> CheckSpec:
    async def runner(_ctx: CheckContext) -> CheckResult:
        if counter is not None:
            counter[0] += 1
            if peak is not None:
                peak[0] = max(peak[0], counter[0])
        try:
            await asyncio.sleep(delay)
        finally:
            if counter is not None:
                counter[0] -= 1
        return CheckResult(status, detail=f"{check_id} done")

    return CheckSpec(
        id=check_id, title=check_id, severity=severity, timeout=10.0,
        runner=runner, tags=tags,
    )


def test_default_budget_is_180_seconds() -> None:
    assert DEFAULT_BUDGET_SECONDS == 180.0


def test_per_check_timeout_is_independent_of_global_budget(tmp_path: Path) -> None:
    """A hanging check times out on its own timer, not on the global budget."""
    specs = [hanging_spec("hangs", timeout=0.05), sleep_spec("after", 0.01)]
    started = time.perf_counter()
    outcomes = asyncio.run(
        run_specs(specs, make_context(tmp_path), budget_seconds=10.0)
    )
    elapsed = time.perf_counter() - started

    by_id = {spec.id: result for spec, result in outcomes}
    assert elapsed < 1.0, elapsed
    assert by_id["hangs"].status == Status.FAIL
    assert "timeout" in by_id["hangs"].detail
    assert by_id["after"].status == Status.PASS, "slow check must not consume another's budget"


def test_budget_exhaustion_marks_remaining_critical_unverified_exit_1(tmp_path: Path) -> None:
    """22 slow checks with a 0.3s budget stop early with exit 1, never hang/exit 0/2."""
    specs = [sleep_spec(f"check_{i:02d}", 0.05) for i in range(22)]
    started = time.perf_counter()
    outcomes = asyncio.run(
        run_specs(specs, make_context(tmp_path), budget_seconds=0.3)
    )
    elapsed = time.perf_counter() - started
    code = classify_exit_code(outcomes)

    assert elapsed < 1.0, elapsed
    assert code == 1
    unverified = [(spec, res) for spec, res in outcomes if res.status == Status.UNVERIFIED]
    assert unverified, "budget exhaustion must mark not-run critical checks UNVERIFIED"
    first_spec, first_result = unverified[0]
    assert f"budget exhausted before critical check {first_spec.id}" in first_result.detail
    assert len(outcomes) == 22, "every check must still be reported once"
    assert any(res.status == Status.PASS for _, res in outcomes), "some checks ran first"


def test_semaphore_limits_network_concurrency_to_four(tmp_path: Path) -> None:
    """10 network checks x 0.1s under semaphore 4 finish in ~3 waves, never 10-wide."""
    counter = [0]
    peak = [0]
    specs = [
        sleep_spec(f"net_{i}", 0.1, tags=("network",), counter=counter, peak=peak)
        for i in range(10)
    ]
    started = time.perf_counter()
    outcomes = asyncio.run(
        run_specs(specs, make_context(tmp_path), budget_seconds=10.0, max_concurrency=4)
    )
    elapsed = time.perf_counter() - started

    assert all(result.status == Status.PASS for _, result in outcomes)
    assert peak[0] <= 4, f"concurrency exceeded limit: {peak[0]}"
    assert peak[0] >= 2, "network checks should run in parallel"
    assert 0.25 <= elapsed < 0.7, elapsed


def test_critical_failure_does_not_stop_remaining_checks(tmp_path: Path) -> None:
    """Check #2 fails; checks #3-#5 still run and are reported; exit is 1."""
    specs = [
        sleep_spec("one", 0.01),
        sleep_spec("two", 0.05, status=Status.FAIL),
        sleep_spec("three", 0.01),
        sleep_spec("four", 0.01),
        sleep_spec("five", 0.01),
    ]
    outcomes = asyncio.run(
        run_specs(specs, make_context(tmp_path), budget_seconds=10.0)
    )

    assert [spec.id for spec, _ in outcomes] == ["one", "two", "three", "four", "five"]
    by_id = {spec.id: result for spec, result in outcomes}
    assert by_id["two"].status == Status.FAIL
    for check_id in ("three", "four", "five"):
        assert by_id[check_id].status == Status.PASS
    assert classify_exit_code(outcomes) == 1


def test_budget_exhaustion_skips_warning_checks(tmp_path: Path) -> None:
    specs = [sleep_spec("warn_never_runs", 0.01, severity=Severity.WARNING)]
    outcomes = asyncio.run(
        run_specs(specs, make_context(tmp_path), budget_seconds=0.0)
    )
    by_id = {spec.id: result for spec, result in outcomes}
    assert by_id["warn_never_runs"].status == Status.SKIP
    assert "budget exhausted" in by_id["warn_never_runs"].detail
    assert classify_exit_code(outcomes) == 0
