"""Integration tests for the preflight pipeline (EP-13).

External I/O is mocked with httpx.MockTransport / fake subprocess runners.
Only read-only ``git`` invocations touch the real repository.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.hygiene import (  # noqa: E402
    check_env_gitignored,
    check_git_identity,
)
from preflight_lib.checks.network import (  # noqa: E402
    check_binance_testnet,
    check_dexscreener,
    check_jupiter_lite,
)
from preflight_lib.checks.precedence import check_config_precedence  # noqa: E402
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.env_loader import load_env_file  # noqa: E402
from preflight_lib.registry import CheckSpec  # noqa: E402
from preflight_lib.reporting import render_human, render_json  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.runner import classify_exit_code, run_specs  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_SECRET_FOR_TEST_ONLY_0123456789"
TS = "2026-11-04T22:30:00+07:00"

FAKE_ENV_BODY = (
    f"SECRET_KEY={'A' * 64}\n"
    f"CREDENTIAL_ENCRYPTION_KEY={'B' * 64}\n"
    f"POSTGRES_PASSWORD={CANARY}\n"
    "LLM_PROVIDER=custom\n"
    "CUSTOM_API_URL=http://127.0.0.1:11434/v1\n"
    "CUSTOM_MODEL=qwen2.5:1.5b\n"
    "LIVE_TRADING_ENABLED=false\n"
    "JEV_ENABLED=false\n"
)

ENV_CHECK_IDS = {
    "env_file",
    "env_required_keys",
    "durable_secrets",
    "trading_safety_flags",
    "llm_config",
}


def env_specs() -> tuple[CheckSpec, ...]:
    return tuple(
        spec for spec in build_registry().specs() if spec.id in ENV_CHECK_IDS
    )


def write_env(tmp_path: Path, body: str = FAKE_ENV_BODY, mode: int = 0o600) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def context_from_env(tmp_path: Path, path: Path) -> CheckContext:
    values = load_env_file(path)
    sanitizer = Sanitizer(values.values())
    return CheckContext(repo_root=tmp_path, env=values, sanitizer=sanitizer)


def run(coro):
    return asyncio.run(coro)


# --- .env fixture ---------------------------------------------------------


def test_env_fixture_pipeline_passes_and_never_leaks_the_canary(
    tmp_path: Path,
) -> None:
    path = write_env(tmp_path)
    ctx = context_from_env(tmp_path, path)
    outcomes = run(run_specs(env_specs(), ctx))

    assert classify_exit_code(outcomes) == 0
    assert all(effective(result) == Status.PASS for _, result in outcomes)

    document = render_json(
        "phase0", outcomes, 0, environment={"tooling_python": "3.12.15", "host_python": "3.14.4"},
        generated_at=TS,
    )
    human = render_human("phase0", outcomes, 0, generated_at=TS)
    assert CANARY not in document
    assert CANARY not in human


def effective(result: CheckResult) -> Status:
    return result.status


def test_env_fixture_with_unsafe_mode_fails_critical(tmp_path: Path) -> None:
    path = write_env(tmp_path, mode=0o644)
    outcomes = run(run_specs(env_specs(), context_from_env(tmp_path, path)))
    by_id = {spec.id: result for spec, result in outcomes}
    assert by_id["env_file"].status == Status.FAIL
    assert classify_exit_code(outcomes) == 1


def test_env_fixture_missing_required_key_fails_critical(tmp_path: Path) -> None:
    body = FAKE_ENV_BODY.replace(f"SECRET_KEY={'A' * 64}\n", "")
    path = write_env(tmp_path, body)
    outcomes = run(run_specs(env_specs(), context_from_env(tmp_path, path)))
    by_id = {spec.id: result for spec, result in outcomes}
    assert by_id["env_required_keys"].status == Status.FAIL
    assert "SECRET_KEY" in by_id["env_required_keys"].detail
    assert classify_exit_code(outcomes) == 1


def test_env_fixture_with_live_trading_enabled_fails_critical(tmp_path: Path) -> None:
    body = FAKE_ENV_BODY.replace(
        "LIVE_TRADING_ENABLED=false", "LIVE_TRADING_ENABLED=true"
    )
    path = write_env(tmp_path, body)
    outcomes = run(run_specs(env_specs(), context_from_env(tmp_path, path)))
    by_id = {spec.id: result for spec, result in outcomes}
    assert by_id["trading_safety_flags"].status == Status.FAIL
    assert classify_exit_code(outcomes) == 1


# --- compose JSON fixture -------------------------------------------------


def compose_fixture(
    *,
    backend_mount: bool = True,
    worker_mount: bool = True,
    postgres_env: dict | None = None,
) -> dict:
    def mount() -> list[dict]:
        return [{"type": "bind", "source": "/repo/.env", "target": "/app/.env"}]

    return {
        "services": {
            "backend": {
                "volumes": mount() if backend_mount else [],
                "environment": {"LOG_LEVEL": "info"},
            },
            "celery-worker": {
                "volumes": mount() if worker_mount else [],
                "environment": {},
            },
            "trading-worker": {
                "volumes": mount() if worker_mount else [],
                "environment": {},
            },
            "postgres": {"environment": postgres_env or {}},
        }
    }


COMPOSE_TEXT = "services:\n  postgres:\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"


def test_compose_fixture_with_mounted_env_passes(tmp_path: Path) -> None:
    ctx = CheckContext(
        repo_root=tmp_path, env={"POSTGRES_PASSWORD": CANARY}, sanitizer=Sanitizer()
    )
    result = run(
        check_config_precedence(
            ctx, compose_config=compose_fixture(), compose_text=COMPOSE_TEXT
        )
    )
    assert result.status == Status.PASS


def test_compose_fixture_missing_worker_mount_fails(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer()),
            compose_config=compose_fixture(worker_mount=False),
            compose_text="",
        )
    )
    assert result.status == Status.FAIL


def test_compose_fixture_environment_override_fails(tmp_path: Path) -> None:
    config = compose_fixture()
    config["services"]["backend"]["environment"]["SECRET_KEY"] = CANARY
    result = run(
        check_config_precedence(
            CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer()), compose_config=config
        )
    )
    assert result.status == Status.FAIL
    assert "SECRET_KEY" in result.detail
    assert CANARY not in result.detail


def test_compose_fixture_interpolated_shell_override_warns_exit_0(
    tmp_path: Path,
) -> None:
    config = compose_fixture(postgres_env={"POSTGRES_PASSWORD": "shell-value"})
    ctx = CheckContext(
        repo_root=tmp_path, env={"POSTGRES_PASSWORD": CANARY}, sanitizer=Sanitizer()
    )
    result = run(check_config_precedence(ctx, compose_config=config, compose_text=COMPOSE_TEXT))
    assert result.status == Status.WARN
    assert "shell override" in result.detail

    spec = next(s for s in build_registry().specs() if s.id == "config_precedence")
    assert classify_exit_code([(spec, result)]) == 0


# --- HTTP MockTransport scenarios ----------------------------------------


def test_mock_transport_classifies_200_429_500_and_timeout(tmp_path: Path) -> None:
    ctx = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())

    def binance(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/attempt-1":
            return httpx.Response(500)
        return httpx.Response(200, json={})

    calls = [0]

    def binance_500_then_200(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return httpx.Response(500) if calls[0] == 1 else httpx.Response(200, json={})

    binance_result = run(
        check_binance_testnet(
            ctx,
            transport=httpx.MockTransport(binance_500_then_200),
            sleep_fn=_no_sleep,
        )
    )
    assert binance_result.status == Status.PASS
    assert calls[0] == 2

    def jupiter_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    jupiter_result = run(
        check_jupiter_lite(
            ctx, transport=httpx.MockTransport(jupiter_429), sleep_fn=_no_sleep
        )
    )
    assert jupiter_result.status == Status.FAIL
    assert "429" in jupiter_result.detail

    def dexscreener_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    dex_result = run(
        check_dexscreener(
            ctx, transport=httpx.MockTransport(dexscreener_timeout), sleep_fn=_no_sleep
        )
    )
    assert dex_result.status == Status.FAIL
    assert "timeout" in dex_result.detail


async def _no_sleep(_delay: float) -> None:
    return None


# --- JSON schema and ordering --------------------------------------------


def test_json_schema_covers_all_22_checks_in_registry_order() -> None:
    specs = build_registry().specs()
    assert len(specs) == 22
    outcomes = [(spec, CheckResult(Status.PASS, detail="ok", duration_ms=1)) for spec in specs]

    payload = json.loads(
        render_json(
            "phase0",
            outcomes,
            0,
            environment={"tooling_python": "3.12.15", "host_python": "3.14.4"},
            generated_at=TS,
        )
    )

    assert payload["schema_version"] == 1
    assert payload["exit_code"] == 0
    assert payload["exit_phase"] == "run"
    assert payload["environment"]["tooling_python"] == "3.12.15"
    assert [check["id"] for check in payload["checks"]] == [spec.id for spec in specs]
    assert payload["summary"]["pass"] == 22
    assert payload["summary"]["critical_fail"] == 0

    required = {"id", "title", "severity", "status", "detail", "duration_ms", "tags"}
    for check in payload["checks"]:
        assert required <= set(check)
        assert "value" not in check
        assert check["severity"] in {"critical", "warning"}
        assert check["status"] in {"PASS", "FAIL", "WARN", "SKIP", "UNVERIFIED"}


def test_output_order_follows_registry_not_completion(tmp_path: Path) -> None:
    async def slow(_ctx: CheckContext) -> CheckResult:
        await asyncio.sleep(0.05)
        return CheckResult(Status.PASS)

    async def fast(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS)

    specs = [
        CheckSpec(id="slow", title="slow", severity=Severity.CRITICAL, timeout=1.0, runner=slow),
        CheckSpec(id="fast", title="fast", severity=Severity.CRITICAL, timeout=1.0, runner=fast),
    ]
    ctx = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())
    outcomes = run(run_specs(specs, ctx))
    assert [spec.id for spec, _ in outcomes] == ["slow", "fast"]
    payload = json.loads(render_json("phase0", outcomes, 0, generated_at=TS))
    assert [check["id"] for check in payload["checks"]] == ["slow", "fast"]


# --- secret leak across outcome branches ---------------------------------


def test_canary_is_absent_from_every_output_branch() -> None:
    targets = (REPO_ROOT,)

    async def passing(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS, detail=f"ok {CANARY}")

    async def failing(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.FAIL, detail=f"bad {CANARY}")

    async def exploding(_ctx: CheckContext) -> CheckResult:
        raise RuntimeError(f"boom {CANARY}")

    specs = [
        CheckSpec(id="pass", title="pass", severity=Severity.CRITICAL, timeout=1.0, runner=passing),
        CheckSpec(id="fail", title="fail", severity=Severity.CRITICAL, timeout=1.0, runner=failing),
        CheckSpec(id="boom", title="boom", severity=Severity.CRITICAL, timeout=1.0, runner=exploding),
    ]
    ctx = CheckContext(
        repo_root=targets[0], env={}, sanitizer=Sanitizer([CANARY])
    )
    outcomes = run(run_specs(specs, ctx))
    human = render_human("phase0", outcomes, 1, generated_at=TS)
    document = render_json("phase0", outcomes, 1, generated_at=TS)

    assert CANARY not in human
    assert CANARY not in document
    assert "***REDACTED***" in human
    assert "RuntimeError" in {spec.id: result for spec, result in outcomes}["boom"].detail


# --- real read-only git ---------------------------------------------------


def test_real_git_identity_is_read_only_and_present() -> None:
    ctx = CheckContext(repo_root=REPO_ROOT, env={}, sanitizer=Sanitizer())
    result = run(check_git_identity(ctx))
    assert result.status == Status.PASS


def test_real_repository_ignores_all_secret_paths() -> None:
    ctx = CheckContext(repo_root=REPO_ROOT, env={}, sanitizer=Sanitizer())
    result = run(check_env_gitignored(ctx))
    assert result.status == Status.PASS
