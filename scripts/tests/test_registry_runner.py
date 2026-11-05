"""TDD tests for the check registry, runner and exit-code semantics (EP-04).

These tests use fake checks only: no network, no docker, no real .env.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.runner import (  # noqa: E402
    classify_exit_code,
    classify_exit_phase,
    effective_status,
    run_specs,
)
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_CANARY_VALUE_0123456789"


def make_spec(
    check_id: str,
    *,
    severity: Severity = Severity.CRITICAL,
    status: Status = Status.PASS,
    delay: float = 0.0,
    config_failure: bool = False,
    timeout: float = 2.0,
) -> CheckSpec:
    async def runner(_ctx: CheckContext) -> CheckResult:
        if delay:
            await asyncio.sleep(delay)
        return CheckResult(status=status, detail="", duration_ms=int(delay * 1000))

    return CheckSpec(
        id=check_id,
        title=check_id,
        severity=severity,
        timeout=timeout,
        runner=runner,
        config_failure=config_failure,
    )


def build_registry(*specs: CheckSpec) -> Registry:
    registry = Registry()
    for spec in specs:
        registry.register(spec)
    return registry


def test_registry_rejects_duplicate_ids() -> None:
    registry = build_registry(make_spec("alpha"))
    with pytest.raises(ValueError, match="alpha"):
        registry.register(make_spec("alpha"))


def test_registry_preserves_insertion_order() -> None:
    registry = build_registry(make_spec("zeta"), make_spec("alpha"))
    assert [spec.id for spec in registry.specs()] == ["zeta", "alpha"]


def test_critical_pass_exits_0() -> None:
    assert classify_exit_code([(make_spec("a"), CheckResult(Status.PASS))]) == 0


def test_critical_fail_exits_1() -> None:
    assert classify_exit_code([(make_spec("a"), CheckResult(Status.FAIL))]) == 1


def test_critical_skip_becomes_unverified_and_exits_1() -> None:
    spec = make_spec("a")
    assert effective_status(spec, CheckResult(Status.SKIP)) == Status.UNVERIFIED
    assert classify_exit_code([(spec, CheckResult(Status.SKIP))]) == 1


def test_critical_unverified_exits_1() -> None:
    assert classify_exit_code([(make_spec("a"), CheckResult(Status.UNVERIFIED))]) == 1


def test_warning_fail_becomes_warn_and_exits_0() -> None:
    spec = make_spec("w", severity=Severity.WARNING)
    assert effective_status(spec, CheckResult(Status.FAIL)) == Status.WARN
    assert classify_exit_code([(spec, CheckResult(Status.FAIL))]) == 0


def test_critical_warn_exits_0() -> None:
    assert classify_exit_code([(make_spec("a"), CheckResult(Status.WARN))]) == 0


def test_config_failure_exits_2() -> None:
    spec = make_spec("cfg", status=Status.FAIL, config_failure=True)
    assert classify_exit_code([(spec, CheckResult(Status.FAIL))]) == 2


def test_config_failure_wins_over_other_critical_fail() -> None:
    config = make_spec("cfg", status=Status.FAIL, config_failure=True)
    other = make_spec("other", status=Status.FAIL)
    assert (
        classify_exit_code(
            [(other, CheckResult(Status.FAIL)), (config, CheckResult(Status.FAIL))]
        )
        == 2
    )


def test_context_defaults_to_empty_sanitizer(tmp_path: Path) -> None:
    ctx = CheckContext(repo_root=tmp_path, env={})
    assert isinstance(ctx.sanitizer, Sanitizer)


def test_warning_skip_and_unverified_never_change_the_exit_code() -> None:
    warning = make_spec("w", severity=Severity.WARNING)
    assert effective_status(warning, CheckResult(Status.SKIP)) == Status.SKIP
    assert classify_exit_code([(warning, CheckResult(Status.SKIP))]) == 0
    assert classify_exit_code([(warning, CheckResult(Status.UNVERIFIED))]) == 0


def test_passing_config_check_does_not_exit_2() -> None:
    spec = make_spec("cfg", config_failure=True)
    assert classify_exit_code([(spec, CheckResult(Status.PASS))]) == 0


def test_exit_phase_uses_config_failures_only(tmp_path: Path) -> None:
    config = make_spec("cfg", config_failure=True)
    plain = make_spec("plain")
    assert classify_exit_phase([(config, CheckResult(Status.FAIL))], 2) == "run"
    assert classify_exit_phase([(plain, CheckResult(Status.FAIL))], 2) == "bootstrap"
    assert classify_exit_phase([(plain, CheckResult(Status.FAIL))], 1) == "run"


def test_runner_converts_exceptions_to_fail_without_leaking_message(
    tmp_path: Path,
) -> None:
    async def boom(_ctx: CheckContext) -> CheckResult:
        raise RuntimeError(f"secret={CANARY}")

    spec = CheckSpec(
        id="boom", title="boom", severity=Severity.CRITICAL, timeout=1.0, runner=boom
    )
    ctx = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer([CANARY]))
    _, result = asyncio.run(run_specs([spec], ctx))[0]

    assert result.status == Status.FAIL
    assert "RuntimeError" in result.detail
    assert CANARY not in result.detail


def test_budget_capped_timeout_is_reported_as_unverified(tmp_path: Path) -> None:
    async def hang(_ctx: CheckContext) -> CheckResult:
        await asyncio.sleep(999)
        return CheckResult(Status.PASS)

    spec = CheckSpec(
        id="slow", title="slow", severity=Severity.CRITICAL, timeout=5.0, runner=hang
    )
    ctx = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())
    _, result = asyncio.run(run_specs([spec], ctx, budget_seconds=0.05))[0]

    assert result.status == Status.UNVERIFIED
    assert "budget exhausted before critical check slow" in result.detail


def test_zero_budget_does_not_start_a_critical_check(tmp_path: Path) -> None:
    calls: list[int] = []

    async def runner(_ctx: CheckContext) -> CheckResult:
        calls.append(1)
        return CheckResult(Status.PASS)

    spec = CheckSpec(
        id="never", title="never", severity=Severity.CRITICAL, timeout=1.0, runner=runner
    )
    ctx = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())
    _, result = asyncio.run(run_specs([spec], ctx, budget_seconds=0.0))[0]

    assert calls == []
    assert result.status == Status.UNVERIFIED
    assert "budget exhausted before critical check never" in result.detail