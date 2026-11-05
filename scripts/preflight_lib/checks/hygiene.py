"""Disk, git identity and secret-hygiene checks (checks 12-16).

All commands are read-only. Git/subprocess output is parsed, never echoed with
secret values.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status
from .docker import CommandRunner, run_command

DISK_FREE_MIN_BYTES = 20 * 1024**3  # 21,474,836,480 bytes
DOCKER_PRESSURE_THRESHOLD_PCT = 80.0

SECRET_PATH_PATTERNS = (
    ".env",
    "backend_api_python/.env",
    ".keys/",
    "secrets/",
    "*.pem",
    "*.key",
    "*.gpg",
)

# Glob patterns need a concrete probe name to be evaluated by git.
_SECRET_PROBES = {
    "*.pem": "probe.pem",
    "*.key": "probe.key",
    "*.gpg": "probe.gpg",
}

_TEMPORARY_IDENTITY_MARKERS = ("@localhost", "haosanh-agent")

_GIB = 1024**3

_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*$")
_SIZE_UNITS = {
    "B": 1,
    "kB": 1000,
    "KB": 1000,
    "kb": 1000,
    "MB": 1000**2,
    "mb": 1000**2,
    "GB": 1000**3,
    "gb": 1000**3,
    "TB": 1000**4,
    "tb": 1000**4,
    "PB": 1000**5,
    "pb": 1000**5,
    "KiB": 1024,
    "kib": 1024,
    "MiB": 1024**2,
    "mib": 1024**2,
    "GiB": 1024**3,
    "gib": 1024**3,
    "TiB": 1024**4,
    "tib": 1024**4,
}

DeviceFn = Callable[[Path], int]
DiskUsageFn = Callable[[Path], tuple[int, int, int]]


def _default_device(path: Path) -> int:
    return os.stat(path).st_dev


def _gib(value: int) -> str:
    return f"{value / _GIB:.2f} GiB"


def parse_size(text: str) -> int | None:
    """Parse a Docker human-readable size (``7.769GB``, ``0B``) into bytes."""
    match = _SIZE_RE.match(text or "")
    if match is None:
        return None
    number, unit = match.groups()
    multiplier = _SIZE_UNITS.get(unit)
    if multiplier is None:
        return None
    return int(round(float(number) * multiplier))


def _resolve_docker_root(ctx: CheckContext, command_runner: CommandRunner) -> Path | None:
    outcome = command_runner(
        ["docker", "info", "--format", "{{.DockerRootDir}}"], ctx.repo_root, 1.5
    )
    if outcome is None or outcome.returncode != 0:
        return None
    text = outcome.stdout.strip()
    return Path(text) if text else None


async def check_disk_free(
    ctx: CheckContext,
    *,
    disk_usage_fn: DiskUsageFn = shutil.disk_usage,
    docker_root: Path | None = None,
    device_fn: DeviceFn = _default_device,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    try:
        _, _, repo_free = disk_usage_fn(ctx.repo_root)
    except OSError as exc:
        return CheckResult(
            Status.FAIL, f"repo disk usage unavailable ({type(exc).__name__})"
        )

    parts = [f"repo free={_gib(repo_free)}"]
    problems: list[str] = []
    if repo_free < DISK_FREE_MIN_BYTES:
        problems.append(f"repo free={_gib(repo_free)} is below {_gib(DISK_FREE_MIN_BYTES)}")

    root = docker_root if docker_root is not None else _resolve_docker_root(ctx, command_runner)
    if root is not None:
        try:
            distinct_filesystem = device_fn(root) != device_fn(ctx.repo_root)
        except OSError:
            distinct_filesystem = False
        if distinct_filesystem:
            try:
                _, _, docker_free = disk_usage_fn(root)
            except OSError:
                parts.append(f"docker({root}) usage unavailable")
            else:
                parts.append(f"docker({root}) free={_gib(docker_free)}")
                if docker_free < DISK_FREE_MIN_BYTES:
                    problems.append(
                        f"docker free={_gib(docker_free)} is below "
                        f"{_gib(DISK_FREE_MIN_BYTES)}"
                    )

    if problems:
        return CheckResult(Status.FAIL, "; ".join(problems + parts))
    return CheckResult(Status.PASS, "; ".join(parts))


async def check_docker_disk_pressure(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
    total_bytes: int | None = None,
) -> CheckResult:
    outcome = command_runner(
        ["docker", "system", "df", "--format", "{{json .}}"], ctx.repo_root, 5
    )
    if outcome is None or outcome.returncode != 0:
        return CheckResult(
            Status.WARN, "docker system df unavailable; disk pressure unknown"
        )

    used = 0
    for line in outcome.stdout.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return CheckResult(
                Status.WARN, "docker system df output unparseable; disk pressure unknown"
            )
        size = parse_size(str(row.get("Size", ""))) if isinstance(row, dict) else None
        if size is None:
            return CheckResult(
                Status.WARN, "docker system df output unparseable; disk pressure unknown"
            )
        used += size

    if total_bytes is None:
        try:
            total_bytes = shutil.disk_usage(ctx.repo_root).total
        except OSError:
            return CheckResult(
                Status.WARN, "filesystem size unavailable; disk pressure unknown"
            )
    if total_bytes <= 0:
        return CheckResult(Status.WARN, "filesystem size unavailable; disk pressure unknown")

    percent = used / total_bytes * 100
    detail = f"docker uses {_gib(used)} = {percent:.1f}% of {_gib(total_bytes)}"
    if percent > DOCKER_PRESSURE_THRESHOLD_PCT:
        return CheckResult(Status.WARN, detail + " (>80%)")
    return CheckResult(Status.PASS, detail)


def _git_config(ctx: CheckContext, key: str, command_runner: CommandRunner) -> str | None:
    outcome = command_runner(
        ["git", "config", "--local", "--get", key], ctx.repo_root, 2
    )
    if outcome is None or outcome.returncode != 0:
        return None
    value = outcome.stdout.strip()
    return value or None


async def check_git_identity(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    missing = [
        key
        for key in ("user.name", "user.email")
        if not _git_config(ctx, key, command_runner)
    ]
    if missing:
        return CheckResult(
            Status.FAIL, "missing local git identity: " + ", ".join(missing)
        )
    return CheckResult(Status.PASS, "user.name and user.email set")


async def check_git_identity_temporary(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    name = (_git_config(ctx, "user.name", command_runner) or "").lower()
    email = (_git_config(ctx, "user.email", command_runner) or "").lower()
    if not name and not email:
        return CheckResult(Status.WARN, "git identity unavailable; cannot tell if temporary")

    haystack = f"{name} {email}"
    if any(marker in haystack for marker in _TEMPORARY_IDENTITY_MARKERS):
        return CheckResult(
            Status.WARN, "temporary git identity detected (reset before Phase 1)"
        )
    return CheckResult(Status.PASS, "git identity is not temporary")


def _is_tracked(
    pattern: str, ctx: CheckContext, command_runner: CommandRunner
) -> bool | None:
    probe = _SECRET_PROBES.get(pattern, pattern)
    if "*" in pattern:
        outcome = command_runner(["git", "ls-files", "--", pattern], ctx.repo_root, 5)
        if outcome is None:
            return None
        return bool(outcome.returncode == 0 and outcome.stdout.strip())
    outcome = command_runner(
        ["git", "ls-files", "--error-unmatch", "--", probe], ctx.repo_root, 5
    )
    if outcome is None:
        return None
    return outcome.returncode == 0


async def check_env_gitignored(
    ctx: CheckContext,
    *,
    command_runner: CommandRunner = run_command,
) -> CheckResult:
    problems: list[str] = []

    for pattern in SECRET_PATH_PATTERNS:
        probe = _SECRET_PROBES.get(pattern, pattern)
        outcome = command_runner(
            ["git", "check-ignore", "--no-index", "-q", "--", probe], ctx.repo_root, 5
        )
        if outcome is None:
            return CheckResult(Status.FAIL, "git check-ignore could not be executed")
        if outcome.returncode == 1:
            problems.append(f"{pattern} is not ignored")
        elif outcome.returncode != 0:
            return CheckResult(
                Status.FAIL, f"git check-ignore failed (exit {outcome.returncode})"
            )

    for pattern in SECRET_PATH_PATTERNS:
        tracked = _is_tracked(pattern, ctx, command_runner)
        if tracked is None:
            return CheckResult(Status.FAIL, "git ls-files could not be executed")
        if tracked:
            problems.append(f"{pattern} is tracked by git")

    if problems:
        return CheckResult(Status.FAIL, "; ".join(problems))
    return CheckResult(
        Status.PASS, f"{len(SECRET_PATH_PATTERNS)} secret paths ignored and untracked"
    )


HYGIENE_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="disk_free",
        title=">=20 GiB free for repo and Docker root",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_disk_free,
        requires="none",
        tags=("local", "disk"),
    ),
    CheckSpec(
        id="docker_disk_pressure",
        title="Docker disk pressure (informational)",
        severity=Severity.WARNING,
        timeout=5.0,
        runner=check_docker_disk_pressure,
        requires="docker",
        tags=("local", "disk", "docker"),
    ),
    CheckSpec(
        id="git_identity",
        title="Local git identity present",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_git_identity,
        requires="git",
        tags=("local", "git"),
    ),
    CheckSpec(
        id="git_identity_temporary",
        title="Git identity is not temporary",
        severity=Severity.WARNING,
        timeout=2.0,
        runner=check_git_identity_temporary,
        requires="git",
        tags=("local", "git"),
        hide_in_phase0_unless_verbose=True,
    ),
    CheckSpec(
        id="env_gitignored",
        title="Secret paths ignored and untracked",
        severity=Severity.CRITICAL,
        timeout=5.0,
        runner=check_env_gitignored,
        requires="git",
        tags=("local", "git", "secret"),
    ),
)
