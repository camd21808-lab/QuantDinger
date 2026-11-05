"""TDD tests for EP-06: config_precedence + Docker checks (4 checks)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.docker import (  # noqa: E402
    CommandOutcome,
    check_docker_compose_config,
    check_docker_compose_plugin,
    check_docker_daemon,
)
from preflight_lib.checks.precedence import (  # noqa: E402
    SAFETY_KEYS,
    check_config_precedence,
)
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.results import Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_SECRET_FOR_TEST_ONLY_0123456789"

ENV = {"POSTGRES_PASSWORD": "FAKE_DB_PASSWORD_FOR_TEST"}
COMPOSE_TEXT = "services:\n  postgres:\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"


def ctx(tmp_path: Path, secrets: list[str] | None = None) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env=ENV, sanitizer=Sanitizer(secrets or []))


def run(coro):
    return asyncio.run(coro)


def bind_env() -> list[dict]:
    return [
        {
            "type": "bind",
            "source": "/repo/.env",
            "target": "/app/.env",
        }
    ]


def compose_config(
    *,
    backend_mount: bool = True,
    worker_mount: bool = True,
    backend_env: dict | None = None,
    worker_env: dict | None = None,
    extra_services: dict | None = None,
) -> dict:
    services = {
        "backend": {
            "volumes": bind_env() if backend_mount else [],
            "environment": backend_env or {},
        },
        "celery-worker": {
            "volumes": bind_env() if worker_mount else [],
            "environment": worker_env or {},
        },
    }
    if extra_services:
        services.update(extra_services)
    return {"services": services}


# --- config_precedence ----------------------------------------------------


def test_safety_keys_are_the_eight_approved_names() -> None:
    assert SAFETY_KEYS == (
        "LIVE_TRADING_ENABLED",
        "JEV_ENABLED",
        "LLM_PROVIDER",
        "CUSTOM_API_URL",
        "CUSTOM_MODEL",
        "CUSTOM_API_KEY",
        "SECRET_KEY",
        "CREDENTIAL_ENCRYPTION_KEY",
    )


def test_precedence_passes_with_mounted_env_and_clean_environment(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path), compose_config=compose_config(), compose_text="services:\n"
        )
    )
    assert result.status == Status.PASS
    assert "mounted .env" in result.detail
    assert "8 safety keys" in result.detail


def test_precedence_fails_when_backend_does_not_mount_env(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path),
            compose_config=compose_config(backend_mount=False),
            compose_text="",
        )
    )
    assert result.status == Status.FAIL
    assert "backend" in result.detail


def test_precedence_fails_when_no_worker_mounts_env(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path),
            compose_config=compose_config(worker_mount=False),
            compose_text="",
        )
    )
    assert result.status == Status.FAIL
    assert "worker" in result.detail


def test_precedence_fails_when_worker_overrides_safety_key(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path),
            compose_config=compose_config(worker_env={"LIVE_TRADING_ENABLED": "true"}),
            compose_text="",
        )
    )
    assert result.status == Status.FAIL
    assert "celery-worker" in result.detail
    assert "LIVE_TRADING_ENABLED" in result.detail


def test_precedence_fails_when_backend_overrides_secret_key(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path),
            compose_config=compose_config(backend_env={"SECRET_KEY": CANARY}),
            compose_text="",
        )
    )
    assert result.status == Status.FAIL
    assert "SECRET_KEY" in result.detail
    assert CANARY not in result.detail


def test_precedence_allows_unrelated_environment_keys(tmp_path: Path) -> None:
    result = run(
        check_config_precedence(
            ctx(tmp_path),
            compose_config=compose_config(backend_env={"LOG_LEVEL": "info"}),
            compose_text="",
        )
    )
    assert result.status == Status.PASS


def test_precedence_warns_on_shell_override_of_interpolated_key(tmp_path: Path) -> None:
    config = compose_config(
        extra_services={"postgres": {"environment": {"POSTGRES_PASSWORD": "shell-value"}}}
    )
    result = run(
        check_config_precedence(ctx(tmp_path), compose_config=config, compose_text=COMPOSE_TEXT)
    )
    assert result.status == Status.WARN
    assert "POSTGRES_PASSWORD" in result.detail
    assert "shell override" in result.detail
    assert "shell-value" not in result.detail


def test_precedence_does_not_warn_when_interpolated_value_matches(tmp_path: Path) -> None:
    config = compose_config(
        extra_services={
            "postgres": {"environment": {"POSTGRES_PASSWORD": ENV["POSTGRES_PASSWORD"]}}
        }
    )
    result = run(
        check_config_precedence(ctx(tmp_path), compose_config=config, compose_text=COMPOSE_TEXT)
    )
    assert result.status == Status.PASS


# --- docker checks --------------------------------------------------------


def command(returncode: int, stdout: str = "", stderr: str = ""):
    def runner(_args, _cwd, _timeout):
        return CommandOutcome(returncode, stdout, stderr)

    return runner


def test_compose_plugin_passes_and_reports_version(tmp_path: Path) -> None:
    result = run(
        check_docker_compose_plugin(
            ctx(tmp_path),
            command_runner=command(0, "Docker Compose version v2.40.3\n"),
        )
    )
    assert result.status == Status.PASS
    assert "2.40.3" in result.detail


def test_compose_plugin_missing_fails(tmp_path: Path) -> None:
    result = run(check_docker_compose_plugin(ctx(tmp_path), command_runner=command(127)))
    assert result.status == Status.FAIL
    assert "compose" in result.detail.lower()


def test_compose_plugin_handles_missing_binary(tmp_path: Path) -> None:
    def runner(_args, _cwd, _timeout):
        return None

    result = run(check_docker_compose_plugin(ctx(tmp_path), command_runner=runner))
    assert result.status == Status.FAIL


def test_compose_config_passes_on_zero_exit(tmp_path: Path) -> None:
    result = run(
        check_docker_compose_config(ctx(tmp_path), command_runner=command(0, "", ""))
    )
    assert result.status == Status.PASS


def test_compose_config_failure_redacts_stderr(tmp_path: Path) -> None:
    result = run(
        check_docker_compose_config(
            ctx(tmp_path, secrets=[CANARY]),
            command_runner=command(1, "", f"invalid interpolation near {CANARY}"),
        )
    )
    assert result.status == Status.FAIL
    assert CANARY not in result.detail


def test_docker_daemon_passes_with_version(tmp_path: Path) -> None:
    result = run(check_docker_daemon(ctx(tmp_path), command_runner=command(0, "28.5.2\n")))
    assert result.status == Status.PASS
    assert "28.5.2" in result.detail


def test_docker_daemon_empty_version_fails(tmp_path: Path) -> None:
    result = run(check_docker_daemon(ctx(tmp_path), command_runner=command(0, "")))
    assert result.status == Status.FAIL


def test_docker_daemon_connection_error_fails(tmp_path: Path) -> None:
    result = run(
        check_docker_daemon(
            ctx(tmp_path), command_runner=command(1, "", "Cannot connect to the Docker daemon")
        )
    )
    assert result.status == Status.FAIL


# --- registry metadata ----------------------------------------------------


def test_registry_contains_precedence_and_docker_checks_in_order() -> None:
    registry = build_registry()
    ids = [spec.id for spec in registry.specs()]
    assert ids[7:11] == [
        "config_precedence",
        "docker_compose_plugin",
        "docker_compose_config",
        "docker_daemon",
    ]
    by_id = {spec.id: spec for spec in registry.specs()}
    assert by_id["config_precedence"].severity == Severity.CRITICAL
    assert by_id["docker_compose_plugin"].config_failure is True
    assert by_id["docker_compose_config"].config_failure is True
    assert by_id["docker_daemon"].config_failure is False
