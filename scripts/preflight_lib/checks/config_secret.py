"""EP-05 checks: tooling, .env file hygiene, secrets, safety flags, LLM config.

Every detail string contains key names, lengths or status words only. Secret
values are never included, even on failure.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from ..bootstrap import expected_venv_prefix, interpreter_error
from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status
from ..urls import INVALID_URL, safe_url

REQUIRED_KEYS = (
    "SECRET_KEY",
    "CREDENTIAL_ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "LLM_PROVIDER",
    "CUSTOM_API_URL",
    "CUSTOM_MODEL",
    "LIVE_TRADING_ENABLED",
    "JEV_ENABLED",
)

DURABLE_SECRET_LENGTHS = {
    "SECRET_KEY": 32,
    "CREDENTIAL_ENCRYPTION_KEY": 32,
    "POSTGRES_PASSWORD": 20,
}

DEFAULT_SECRET_VALUES = {"123456", "password", "postgres", "changeme", "admin"}
FALSE_VALUES = {"false", "0", "no", "off"}

_OLLAMA_HOST = "127.0.0.1"
_OLLAMA_PORT = 11434
_OLLAMA_PATH = "/v1"
_OLLAMA_MODEL = "qwen2.5:1.5b"

_MISSING = object()


async def check_tooling_python(
    ctx: CheckContext,
    *,
    version_info: tuple[int, ...] | None = None,
    prefix: str | None = None,
    expected_prefix: Path | None = None,
) -> CheckResult:
    version = tuple(version_info if version_info is not None else sys.version_info)
    expected = expected_prefix or expected_venv_prefix(ctx.repo_root)
    current_prefix = prefix if prefix is not None else sys.prefix
    error = interpreter_error(version, current_prefix, expected)
    if error is not None:
        return CheckResult(Status.FAIL, error)
    return CheckResult(Status.PASS, f"CPython {version[0]}.{version[1]}.{version[2]}")


def read_host_python_version() -> str | None:
    try:
        completed = subprocess.run(
            ["python3", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return text or None


async def check_host_python_info(
    ctx: CheckContext,
    *,
    version_text: str | None | object = _MISSING,
) -> CheckResult:
    text = read_host_python_version() if version_text is _MISSING else version_text
    if not text:
        return CheckResult(Status.WARN, "python3 not found on PATH (informational only)")
    return CheckResult(
        Status.PASS, f"{text}; informational only, tooling uses scripts/.venv"
    )


async def check_env_file(
    ctx: CheckContext,
    *,
    path: Path | None = None,
    uid: int | None = None,
) -> CheckResult:
    env_path = path or (ctx.repo_root / ".env")
    try:
        resolved = env_path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return CheckResult(Status.FAIL, f"{env_path.name} is missing")

    if not resolved.is_file():
        return CheckResult(Status.FAIL, f"{env_path.name} is not a regular file")

    try:
        info = resolved.stat()
    except OSError as exc:
        return CheckResult(Status.FAIL, f"{env_path.name} cannot be stat'ed ({type(exc).__name__})")

    owner = uid if uid is not None else os.geteuid()
    if info.st_uid != owner:
        return CheckResult(Status.FAIL, f"{env_path.name} is not owned by the current user")

    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        return CheckResult(
            Status.FAIL,
            f"{env_path.name} mode {mode:04o}; group/other bits must be clear",
        )

    try:
        with resolved.open("rb") as handle:
            handle.read(1)
    except OSError:
        return CheckResult(Status.FAIL, f"{env_path.name} is not readable")

    return CheckResult(Status.PASS, f"{env_path.name} mode {mode:04o}")


async def check_env_required_keys(
    ctx: CheckContext,
    *,
    env: dict[str, str] | None = None,
) -> CheckResult:
    values = ctx.env if env is None else env
    missing = [key for key in REQUIRED_KEYS if key not in values]
    empty = [key for key in REQUIRED_KEYS if key in values and not values[key].strip()]
    if missing or empty:
        parts = []
        if missing:
            parts.append("missing keys: " + ", ".join(missing))
        if empty:
            parts.append("empty values: " + ", ".join(empty))
        return CheckResult(Status.FAIL, "; ".join(parts))
    return CheckResult(Status.PASS, f"{len(REQUIRED_KEYS)} required keys present")


async def check_durable_secrets(
    ctx: CheckContext,
    *,
    env: dict[str, str] | None = None,
) -> CheckResult:
    values = ctx.env if env is None else env
    problems: list[str] = []
    lengths: list[str] = []
    for key, minimum in DURABLE_SECRET_LENGTHS.items():
        value = values.get(key, "")
        lengths.append(f"{key}={len(value)}")
        if len(value) < minimum:
            problems.append(f"{key} has {len(value)} chars, need >= {minimum}")
        elif value.strip().lower() in DEFAULT_SECRET_VALUES:
            problems.append(f"{key} uses a default value")
    detail = ", ".join(lengths)
    if problems:
        return CheckResult(Status.FAIL, "; ".join(problems))
    return CheckResult(Status.PASS, detail)


async def check_trading_safety_flags(
    ctx: CheckContext,
    *,
    env: dict[str, str] | None = None,
) -> CheckResult:
    values = ctx.env if env is None else env
    problems = []
    for key in ("LIVE_TRADING_ENABLED", "JEV_ENABLED"):
        raw = values.get(key, "")
        if raw.strip().lower() not in FALSE_VALUES:
            problems.append(f"{key} must be one of false/0/no/off")
    if problems:
        return CheckResult(Status.FAIL, "; ".join(problems))
    return CheckResult(Status.PASS, "LIVE_TRADING_ENABLED and JEV_ENABLED are disabled")


async def check_llm_config(
    ctx: CheckContext,
    *,
    env: dict[str, str] | None = None,
) -> CheckResult:
    values = ctx.env if env is None else env
    problems: list[str] = []

    provider = values.get("LLM_PROVIDER", "").strip().lower()
    if provider != "custom":
        problems.append("LLM_PROVIDER must be custom")

    raw_url = values.get("CUSTOM_API_URL", "")
    clean_url = safe_url(raw_url)
    if clean_url == INVALID_URL:
        problems.append("CUSTOM_API_URL is not a valid URL")
    else:
        parts = urlsplit(clean_url)
        if parts.hostname != _OLLAMA_HOST:
            problems.append(f"CUSTOM_API_URL host must be {_OLLAMA_HOST} (got {parts.hostname})")
        if parts.port != _OLLAMA_PORT:
            problems.append(f"CUSTOM_API_URL port must be {_OLLAMA_PORT}")
        if parts.path != _OLLAMA_PATH:
            problems.append(f"CUSTOM_API_URL path must be {_OLLAMA_PATH} (got {parts.path})")

    model = values.get("CUSTOM_MODEL", "").strip()
    if model != _OLLAMA_MODEL:
        problems.append(f"CUSTOM_MODEL must be {_OLLAMA_MODEL}")

    if values.get("CUSTOM_API_KEY", "").strip():
        problems.append("CUSTOM_API_KEY must be empty for local Ollama")

    if problems:
        return CheckResult(Status.FAIL, "; ".join(problems))

    return CheckResult(
        Status.PASS,
        f"provider=custom host={_OLLAMA_HOST}:{_OLLAMA_PORT} path={_OLLAMA_PATH} "
        f"model={_OLLAMA_MODEL}",
    )


CONFIG_SECRET_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="tooling_python",
        title="Tooling venv on CPython 3.12",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_tooling_python,
        requires="env",
        tags=("local", "tooling"),
        config_failure=True,
    ),
    CheckSpec(
        id="host_python_info",
        title="Host Python (informational)",
        severity=Severity.WARNING,
        timeout=2.0,
        runner=check_host_python_info,
        requires="env",
        tags=("local", "tooling"),
    ),
    CheckSpec(
        id="env_file",
        title=".env exists and is private",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_env_file,
        requires="env",
        tags=("local", "secret"),
    ),
    CheckSpec(
        id="env_required_keys",
        title="Required keys present",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_env_required_keys,
        requires="env",
        tags=("local", "secret"),
    ),
    CheckSpec(
        id="durable_secrets",
        title="Durable secrets strong and non-default",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_durable_secrets,
        requires="env",
        tags=("local", "secret"),
    ),
    CheckSpec(
        id="trading_safety_flags",
        title="Live trading and JEV disabled",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_trading_safety_flags,
        requires="env",
        tags=("local",),
    ),
    CheckSpec(
        id="llm_config",
        title="LLM points to local Ollama",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_llm_config,
        requires="env",
        tags=("local",),
    ),
)
