"""TDD tests for the preflight CLI (EP-04).

These tests use fake checks only: no network, no docker, no real .env.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib import cli  # noqa: E402
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_CANARY_VALUE_0123456789"


def make_spec(
    check_id: str,
    *,
    severity: Severity = Severity.CRITICAL,
    status: Status = Status.PASS,
    detail: str = "",
    delay: float = 0.0,
    config_failure: bool = False,
    timeout: float = 2.0,
) -> CheckSpec:
    async def runner(_ctx: CheckContext) -> CheckResult:
        if delay:
            await asyncio.sleep(delay)
        return CheckResult(status=status, detail=detail, duration_ms=int(delay * 1000))

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


def make_context(tmp_path: Path, secrets: list[str] | None = None) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer(secrets or []))


def run_cli(registry: Registry, argv: list[str], ctx: CheckContext) -> int:
    return cli.main(argv, registry=registry, context=ctx)




def test_default_profile_is_phase0(tmp_path: Path) -> None:
    registry = build_registry(make_spec("a"))
    assert run_cli(registry, [], make_context(tmp_path)) == 0


def test_unknown_profile_exits_2_and_lists_profiles(tmp_path: Path, capsys) -> None:
    registry = build_registry(make_spec("a"))
    code = run_cli(registry, ["--profile", "phase99"], make_context(tmp_path))
    captured = capsys.readouterr()
    assert code == 2
    assert "phase0" in captured.err


def test_list_checks_prints_id_severity_timeout(tmp_path: Path, capsys) -> None:
    registry = build_registry(make_spec("alpha", severity=Severity.WARNING, timeout=7))
    code = run_cli(registry, ["--list-checks"], make_context(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "alpha" in out and "warning" in out and "7" in out


def test_empty_registry_exits_2(tmp_path: Path, capsys) -> None:
    code = run_cli(build_registry(), [], make_context(tmp_path))
    assert code == 2
    assert "empty" in capsys.readouterr().err.lower()


def test_cli_exit_codes_follow_classification(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    assert run_cli(build_registry(make_spec("a")), [], ctx) == 0
    assert run_cli(build_registry(make_spec("a", status=Status.FAIL)), [], ctx) == 1
    assert (
        run_cli(
            build_registry(make_spec("a", status=Status.FAIL, config_failure=True)), [], ctx
        )
        == 2
    )


def test_output_is_ordered_by_registry_not_completion(tmp_path: Path, capsys) -> None:
    registry = build_registry(
        make_spec("slow", delay=0.05), make_spec("fast", delay=0.0)
    )
    assert run_cli(registry, [], make_context(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.index("slow") < out.index("fast")


def test_json_output_is_parseable_and_has_exit_code(tmp_path: Path, capsys) -> None:
    registry = build_registry(make_spec("a", status=Status.FAIL))
    code = run_cli(registry, ["--json"], make_context(tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["schema_version"] == 1
    assert payload["profile"] == "phase0"
    assert payload["exit_code"] == 1
    assert payload["checks"][0]["id"] == "a"
    assert payload["checks"][0]["severity"] == "critical"
    assert payload["summary"]["critical_fail"] == 1


def test_details_are_sanitized_in_human_and_json(tmp_path: Path, capsys) -> None:
    ctx = make_context(tmp_path, secrets=[CANARY])
    registry = build_registry(make_spec("leaky", status=Status.FAIL, detail=f"got {CANARY}"))

    run_cli(registry, [], ctx)
    human = capsys.readouterr().out
    run_cli(registry, ["--json"], ctx)
    payload = capsys.readouterr().out

    assert CANARY not in human
    assert CANARY not in payload


def test_no_color_flag_is_accepted(tmp_path: Path, capsys) -> None:
    registry = build_registry(make_spec("a"))
    assert run_cli(registry, ["--no-color"], make_context(tmp_path)) == 0
    assert "\x1b[" not in capsys.readouterr().out


def test_phase1_profile_is_accepted(tmp_path: Path) -> None:
    registry = build_registry(make_spec("a"))
    assert run_cli(registry, ["--profile", "phase1"], make_context(tmp_path)) == 0
