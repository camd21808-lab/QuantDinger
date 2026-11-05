"""config_precedence: verify the mounted-.env model and detect overrides.

Steps (approved Option A):
1. backend and at least one worker must bind-mount ./.env to /app/.env.
2. none of the 8 safety keys may appear in any service ``environment:``.
3. shell overrides of interpolated keys are reported as WARN (not exit code).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status
from .docker import CommandRunner, run_command

SAFETY_KEYS = (
    "LIVE_TRADING_ENABLED",
    "JEV_ENABLED",
    "LLM_PROVIDER",
    "CUSTOM_API_URL",
    "CUSTOM_MODEL",
    "CUSTOM_API_KEY",
    "SECRET_KEY",
    "CREDENTIAL_ENCRYPTION_KEY",
)

_ENV_TARGET = "/app/.env"
_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


def _normalize_env(block: object) -> dict[str, str]:
    if isinstance(block, Mapping):
        return {str(key): "" if value is None else str(value) for key, value in block.items()}
    if isinstance(block, list):
        result = {}
        for item in block:
            text = str(item)
            key, _, value = text.partition("=")
            result[key] = value
        return result
    return {}


def _mounts_env(service: Mapping) -> bool:
    for volume in service.get("volumes") or []:
        if isinstance(volume, str):
            parts = volume.split(":")
            if len(parts) >= 2 and parts[1] == _ENV_TARGET:
                return True
        elif isinstance(volume, Mapping):
            if volume.get("target") == _ENV_TARGET and volume.get("type", "bind") == "bind":
                return True
    return False


def _interpolated_keys(compose_text: str) -> set[str]:
    return set(_INTERPOLATION.findall(compose_text or ""))


def _read_compose_text(ctx: CheckContext) -> str:
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        path = Path(ctx.repo_root) / name
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def _load_compose_config(ctx: CheckContext, command_runner: CommandRunner) -> dict | None:
    outcome = command_runner(
        ["docker", "compose", "config", "--format", "json"], ctx.repo_root, 10
    )
    if outcome is None or outcome.returncode != 0:
        return None
    try:
        data = json.loads(outcome.stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def evaluate_config_precedence(
    compose_config: Mapping,
    env: Mapping[str, str],
    compose_text: str,
) -> CheckResult:
    services = compose_config.get("services")
    if not isinstance(services, Mapping) or not services:
        return CheckResult(Status.FAIL, "compose config has no services")

    backend = services.get("backend")
    if not isinstance(backend, Mapping):
        return CheckResult(Status.FAIL, "compose config has no backend service")
    if not _mounts_env(backend):
        return CheckResult(
            Status.FAIL,
            "backend service does not mount .env; runtime config source unclear",
        )

    workers = [name for name in services if "worker" in str(name)]
    if not workers:
        return CheckResult(Status.FAIL, "no worker service found in compose config")
    if not any(_mounts_env(services[name]) for name in workers):
        return CheckResult(
            Status.FAIL,
            "no worker service mounts .env; runtime config source unclear",
        )

    overrides = []
    for name, service in services.items():
        if not isinstance(service, Mapping):
            continue
        service_env = _normalize_env(service.get("environment"))
        for key in SAFETY_KEYS:
            if key in service_env:
                overrides.append(f"{name} overrides safety key {key}")
    if overrides:
        return CheckResult(
            Status.FAIL,
            "; ".join(overrides) + " via environment:; mounted .env can be bypassed",
        )

    warnings = []
    for key in sorted(_interpolated_keys(compose_text)):
        if key not in env:
            continue
        expected = env[key]
        for name, service in services.items():
            if not isinstance(service, Mapping):
                continue
            service_env = _normalize_env(service.get("environment"))
            if key in service_env and service_env[key] != expected:
                warnings.append(
                    f"shell override on {key} (interpolated); container uses shell value, "
                    "not .env. Not safety-critical but verify auth/connection"
                )
                break

    base = "mounted .env model verified; 8 safety keys not overridden via environment:"
    if warnings:
        return CheckResult(Status.WARN, base + " " + " ".join(warnings))
    return CheckResult(Status.PASS, base)


async def check_config_precedence(
    ctx: CheckContext,
    *,
    compose_config: Mapping | None = None,
    compose_text: str | None = None,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    config = compose_config
    if config is None:
        config = _load_compose_config(ctx, command_runner)
        if config is None:
            return CheckResult(
                Status.FAIL, "cannot read docker compose config; runtime config source unclear"
            )
    text = _read_compose_text(ctx) if compose_text is None else compose_text
    return evaluate_config_precedence(config, ctx.env, text)


PRECEDENCE_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="config_precedence",
        title="Mounted .env model verified; safety keys not overridden",
        severity=Severity.CRITICAL,
        timeout=10.0,
        runner=check_config_precedence,
        requires="docker",
        tags=("local", "docker"),
    ),
)
