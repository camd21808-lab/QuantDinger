"""Read-only Docker and Compose checks.

Subprocess output is captured and sanitized; no compose-resolved values are
ever printed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], Path, float], CommandOutcome | None]


def run_command(
    args: Sequence[str], cwd: Path, timeout: float
) -> CommandOutcome | None:
    """Run a read-only command; return None when it cannot be executed."""
    try:
        completed = subprocess.run(
            list(args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return CommandOutcome(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _first_line(text: str, limit: int = 160) -> str:
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return line[:limit]


async def check_docker_compose_plugin(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    outcome = command_runner(["docker", "compose", "version"], ctx.repo_root, 5)
    if outcome is None or outcome.returncode != 0:
        return CheckResult(
            Status.FAIL,
            "docker compose plugin is not available; install Docker Compose v2",
        )
    version = _first_line(outcome.stdout)
    return CheckResult(Status.PASS, version or "docker compose plugin available")


async def check_docker_compose_config(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    outcome = command_runner(
        ["docker", "compose", "config", "--quiet"], ctx.repo_root, 10
    )
    if outcome is None:
        return CheckResult(Status.FAIL, "docker compose config could not be executed")
    if outcome.returncode != 0:
        reason = _first_line(outcome.stderr) or "unknown error"
        reason = ctx.sanitizer.redact(reason, fallback=True)
        return CheckResult(Status.FAIL, f"docker compose config failed: {reason}")
    return CheckResult(Status.PASS, "docker compose config valid")


async def check_docker_daemon(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    outcome = command_runner(
        ["docker", "info", "--format", "{{.ServerVersion}}"], ctx.repo_root, 5
    )
    if outcome is None or outcome.returncode != 0:
        return CheckResult(
            Status.FAIL, "docker daemon is not reachable; start Docker or check permissions"
        )
    version = _first_line(outcome.stdout)
    if not version:
        return CheckResult(Status.FAIL, "docker daemon returned an empty version")
    return CheckResult(Status.PASS, f"docker {version}")


DOCKER_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="docker_compose_plugin",
        title="Docker Compose v2 plugin available",
        severity=Severity.CRITICAL,
        timeout=5.0,
        runner=check_docker_compose_plugin,
        requires="docker",
        tags=("local", "docker"),
        config_failure=True,
    ),
    CheckSpec(
        id="docker_compose_config",
        title="Compose file and .env interpolation valid",
        severity=Severity.CRITICAL,
        timeout=10.0,
        runner=check_docker_compose_config,
        requires="docker",
        tags=("local", "docker"),
        config_failure=True,
    ),
    CheckSpec(
        id="docker_daemon",
        title="Docker daemon reachable",
        severity=Severity.CRITICAL,
        timeout=5.0,
        runner=check_docker_daemon,
        requires="docker",
        tags=("local", "docker"),
    ),
)
