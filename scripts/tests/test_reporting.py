"""TDD tests for EP-10: human/JSON output and exit_phase semantics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib import cli  # noqa: E402
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry  # noqa: E402
from preflight_lib.reporting import render_human, render_json  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.runner import classify_exit_phase  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

TS = "2026-11-04T22:30:00+07:00"
ENVIRONMENT = {"tooling_python": "3.12.15", "host_python": "3.14.4"}


def outcome(
    check_id: str,
    *,
    status: Status = Status.PASS,
    severity: Severity = Severity.CRITICAL,
    config_failure: bool = False,
    detail: str = "ok",
    duration_ms: int = 10,
):
    async def runner(_ctx: CheckContext) -> CheckResult:
        return CheckResult(status)

    spec = CheckSpec(
        id=check_id,
        title=check_id,
        severity=severity,
        timeout=1.0,
        runner=runner,
        config_failure=config_failure,
    )
    return spec, CheckResult(status, detail=detail, duration_ms=duration_ms)


def make_context(tmp_path: Path) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())


def make_registry(*specs: CheckSpec) -> Registry:
    registry = Registry()
    for spec in specs:
        registry.register(spec)
    return registry


def spec_only(
    check_id: str,
    *,
    status: Status = Status.PASS,
    config_failure: bool = False,
    tags: tuple[str, ...] = (),
) -> CheckSpec:
    async def runner(_ctx: CheckContext) -> CheckResult:
        return CheckResult(status)

    return CheckSpec(
        id=check_id,
        title=check_id,
        severity=Severity.CRITICAL,
        timeout=1.0,
        runner=runner,
        config_failure=config_failure,
        tags=tags,
    )


# --- human ----------------------------------------------------------------


def test_human_header_uses_phase_profile_and_timestamp() -> None:
    text = render_human("phase0", [outcome("a")], 0, generated_at=TS)
    assert text.splitlines()[0] == (
        f"Phase 0 preflight — profile=phase0 — {TS}"
    )


def test_human_line_has_status_id_detail_and_duration() -> None:
    text = render_human(
        "phase0",
        [outcome("tooling_python", detail="CPython 3.12.15")],
        0,
        generated_at=TS,
    )
    line = next(line for line in text.splitlines() if "tooling_python" in line)
    assert line.startswith("[PASS]")
    assert "CPython 3.12.15" in line
    assert line.rstrip().endswith("0.01s")


def test_human_colors_are_opt_in() -> None:
    plain = render_human("phase0", [outcome("a")], 0, generated_at=TS)
    colored = render_human("phase0", [outcome("a")], 0, generated_at=TS, use_color=True)
    assert "\x1b[" not in plain
    assert "\x1b[32m" in colored

    failed = render_human(
        "phase0",
        [outcome("a", status=Status.FAIL)],
        1,
        generated_at=TS,
        use_color=True,
    )
    assert "\x1b[31m" in failed

    warned = render_human(
        "phase0",
        [outcome("a", status=Status.WARN, severity=Severity.WARNING)],
        0,
        generated_at=TS,
        use_color=True,
    )
    assert "\x1b[33m" in warned


def test_human_run_level_config_failure_has_check_config_fail_prefix() -> None:
    text = render_human(
        "phase0",
        [outcome("docker_compose_config", status=Status.FAIL, config_failure=True)],
        2,
        generated_at=TS,
    )
    assert "CHECK CONFIG FAIL: docker_compose_config" in text
    assert "CONFIG ERROR:" not in text


# --- exit phase -----------------------------------------------------------


def test_exit_phase_is_run_for_success_and_critical_failure() -> None:
    assert classify_exit_phase([outcome("a")], 0) == "run"
    assert classify_exit_phase([outcome("a", status=Status.FAIL)], 1) == "run"


def test_exit_phase_is_run_for_config_check_failure() -> None:
    outcomes = [outcome("docker_compose_plugin", status=Status.FAIL, config_failure=True)]
    assert classify_exit_phase(outcomes, 2) == "run"


def test_exit_phase_is_bootstrap_for_config_errors_without_check_failure() -> None:
    assert classify_exit_phase([], 2) == "bootstrap"
    assert classify_exit_phase([outcome("a")], 2) == "bootstrap"


# --- json -----------------------------------------------------------------


def test_json_has_environment_severity_summary_and_exit_phase() -> None:
    payload = json.loads(
        render_json(
            "phase0",
            [outcome("a")],
            0,
            environment=ENVIRONMENT,
            generated_at=TS,
        )
    )
    assert payload["schema_version"] == 1
    assert payload["profile"] == "phase0"
    assert payload["generated_at"] == TS
    assert payload["environment"] == ENVIRONMENT
    assert payload["exit_code"] == 0
    assert payload["exit_phase"] == "run"
    assert payload["checks"][0]["severity"] == "critical"
    assert payload["checks"][0]["status"] == "PASS"
    assert payload["summary"]["pass"] == 1


def test_json_run_level_config_failure_keeps_exit_2_and_marks_run() -> None:
    payload = json.loads(
        render_json(
            "phase0",
            [outcome("docker_compose_config", status=Status.FAIL, config_failure=True)],
            2,
            environment=ENVIRONMENT,
            generated_at=TS,
        )
    )
    assert payload["exit_code"] == 2
    assert payload["exit_phase"] == "run"
    assert payload["summary"]["critical_fail"] == 1


def test_json_bootstrap_error_document_is_complete() -> None:
    payload = json.loads(
        render_json(
            "phase0",
            [],
            2,
            environment=ENVIRONMENT,
            generated_at=TS,
            error="check registry is empty for profile 'phase0'",
        )
    )
    assert payload["exit_code"] == 2
    assert payload["exit_phase"] == "bootstrap"
    assert payload["checks"] == []
    assert payload["error"] == "check registry is empty for profile 'phase0'"
    assert payload["summary"]["pass"] == 0


# --- CLI integration ------------------------------------------------------


def test_cli_bootstrap_error_uses_config_error_prefix(tmp_path: Path, capsys) -> None:
    code = cli.main([], registry=Registry(), context=make_context(tmp_path))
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("CONFIG ERROR:")


def test_cli_bootstrap_error_json_has_exit_phase_bootstrap(
    tmp_path: Path, capsys
) -> None:
    code = cli.main(["--json"], registry=Registry(), context=make_context(tmp_path))
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 2
    assert payload["exit_code"] == 2
    assert payload["exit_phase"] == "bootstrap"
    assert "empty" in payload["error"]
    assert "CONFIG ERROR:" in captured.err


def test_cli_warmup_failure_uses_config_error_prefix(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    async def failing(_ctx: CheckContext) -> str:
        return "connection refused"

    monkeypatch.setattr(cli, "warm_up_ollama", failing)
    registry = make_registry(spec_only("fake_ollama", tags=("ollama",)))
    code = cli.main([], registry=registry, context=make_context(tmp_path))
    captured = capsys.readouterr()
    assert code == 2
    assert "CONFIG ERROR:" in captured.err
    assert "warm-up" in captured.err.lower()


def test_cli_run_level_config_failure_json_marks_run(tmp_path: Path, capsys) -> None:
    registry = make_registry(spec_only("docker_compose_config", status=Status.FAIL, config_failure=True))
    code = cli.main(["--json"], registry=registry, context=make_context(tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["exit_phase"] == "run"


def test_cli_human_report_has_check_config_fail_line(tmp_path: Path, capsys) -> None:
    registry = make_registry(spec_only("docker_compose_config", status=Status.FAIL, config_failure=True))
    code = cli.main([], registry=registry, context=make_context(tmp_path))
    out = capsys.readouterr().out
    assert code == 2
    assert "CHECK CONFIG FAIL: docker_compose_config" in out


def test_cli_json_environment_reports_both_pythons(tmp_path: Path, capsys) -> None:
    registry = make_registry(spec_only("a"))
    assert cli.main(["--json"], registry=registry, context=make_context(tmp_path)) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert payload["environment"]["tooling_python"] == expected
    assert isinstance(payload["environment"]["host_python"], str)
    assert payload["environment"]["host_python"]


def test_cli_json_stdout_contains_only_json(tmp_path: Path, capsys) -> None:
    registry = make_registry(spec_only("a"))
    assert cli.main(["--json"], registry=registry, context=make_context(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("{")
    assert "Phase 0 preflight" not in out
    json.loads(out)
