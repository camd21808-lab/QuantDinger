"""TDD tests for EP-05 config/secret checks (7 checks).

Synthetic values only (FAKE_*); the real .env is never read.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.config_secret import (  # noqa: E402
    check_env_file,
    check_env_required_keys,
    check_durable_secrets,
    check_host_python_info,
    check_llm_config,
    check_tooling_python,
    check_trading_safety_flags,
)
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.results import Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_SECRET_FOR_TEST_ONLY_0123456789"

GOOD_ENV = {
    "SECRET_KEY": "A" * 64,
    "CREDENTIAL_ENCRYPTION_KEY": "B" * 64,
    "POSTGRES_PASSWORD": "C" * 36,
    "LLM_PROVIDER": "custom",
    "CUSTOM_API_URL": "http://127.0.0.1:11434/v1",
    "CUSTOM_MODEL": "qwen2.5:1.5b",
    "LIVE_TRADING_ENABLED": "false",
    "JEV_ENABLED": "false",
}


def ctx(tmp_path: Path, env: dict[str, str] | None = None) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env=env or {}, sanitizer=Sanitizer())


def run(coro):
    return asyncio.run(coro)


def test_registry_has_the_seven_config_secret_checks_in_order() -> None:
    registry = build_registry()
    ids = [spec.id for spec in registry.specs()]
    assert ids[:7] == [
        "tooling_python",
        "host_python_info",
        "env_file",
        "env_required_keys",
        "durable_secrets",
        "trading_safety_flags",
        "llm_config",
    ]
    by_id = {spec.id: spec for spec in registry.specs()}
    assert by_id["host_python_info"].severity == Severity.WARNING
    assert by_id["tooling_python"].config_failure is True
    assert by_id["env_file"].config_failure is False


# --- tooling_python -------------------------------------------------------


def test_tooling_python_accepts_312(tmp_path: Path) -> None:
    env_dir = tmp_path / "scripts" / ".venv"
    env_dir.mkdir(parents=True)
    result = run(
        check_tooling_python(
            ctx(tmp_path),
            version_info=(3, 12, 15),
            prefix=str(env_dir),
            expected_prefix=env_dir,
        )
    )
    assert result.status == Status.PASS
    assert "3.12.15" in result.detail


def test_tooling_python_rejects_host_version(tmp_path: Path) -> None:
    env_dir = tmp_path / "scripts" / ".venv"
    env_dir.mkdir(parents=True)
    result = run(
        check_tooling_python(
            ctx(tmp_path),
            version_info=(3, 14, 4),
            prefix=str(env_dir),
            expected_prefix=env_dir,
        )
    )
    assert result.status == Status.FAIL
    assert "3.12" in result.detail


# --- host_python_info -----------------------------------------------------


def test_host_python_info_is_informational(tmp_path: Path) -> None:
    result = run(check_host_python_info(ctx(tmp_path), version_text="Python 3.14.4"))
    assert result.status == Status.PASS
    assert "3.14.4" in result.detail


def test_host_python_info_warns_when_missing(tmp_path: Path) -> None:
    result = run(check_host_python_info(ctx(tmp_path), version_text=None))
    assert result.status == Status.WARN


# --- env_file -------------------------------------------------------------


def test_env_file_accepts_0600(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o600)
    result = run(check_env_file(ctx(tmp_path), path=path, uid=os.geteuid()))
    assert result.status == Status.PASS
    assert "0600" in result.detail


def test_env_file_rejects_group_or_world_bits(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o644)
    result = run(check_env_file(ctx(tmp_path), path=path, uid=os.geteuid()))
    assert result.status == Status.FAIL


def test_env_file_accepts_read_only_0400(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o400)
    result = run(check_env_file(ctx(tmp_path), path=path, uid=os.geteuid()))
    assert result.status == Status.PASS


def test_env_file_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.env"
    target.write_text("A=1\n")
    target.chmod(0o600)
    link = tmp_path / ".env"
    link.symlink_to(target)
    result = run(check_env_file(ctx(tmp_path), path=link, uid=os.geteuid()))
    assert result.status == Status.PASS


def test_env_file_missing_fails(tmp_path: Path) -> None:
    result = run(check_env_file(ctx(tmp_path), path=tmp_path / "missing.env"))
    assert result.status == Status.FAIL


# --- env_required_keys ----------------------------------------------------


def test_env_required_keys_accepts_complete_env(tmp_path: Path) -> None:
    result = run(check_env_required_keys(ctx(tmp_path, GOOD_ENV)))
    assert result.status == Status.PASS


def test_env_required_keys_allows_empty_custom_api_key(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, CUSTOM_API_KEY="")
    assert run(check_env_required_keys(ctx(tmp_path, env))).status == Status.PASS


def test_env_required_keys_lists_missing_names(tmp_path: Path) -> None:
    env = dict(GOOD_ENV)
    del env["SECRET_KEY"]
    del env["JEV_ENABLED"]
    result = run(check_env_required_keys(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "SECRET_KEY" in result.detail and "JEV_ENABLED" in result.detail


def test_env_required_keys_rejects_empty_required_value(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, LLM_PROVIDER="")
    assert run(check_env_required_keys(ctx(tmp_path, env))).status == Status.FAIL


# --- durable_secrets ------------------------------------------------------


def test_durable_secrets_accepts_strong_values(tmp_path: Path) -> None:
    result = run(check_durable_secrets(ctx(tmp_path, GOOD_ENV)))
    assert result.status == Status.PASS
    assert "64" in result.detail and "36" in result.detail


def test_durable_secrets_rejects_short_value_without_leaking_it(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, SECRET_KEY="short-value")
    result = run(check_durable_secrets(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "SECRET_KEY" in result.detail
    assert "short-value" not in result.detail


def test_durable_secrets_rejects_default_values_without_leaking(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, POSTGRES_PASSWORD="changeme")
    result = run(check_durable_secrets(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "changeme" not in result.detail


def test_durable_secrets_rejects_short_encryption_key(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, CREDENTIAL_ENCRYPTION_KEY="too-short")
    result = run(check_durable_secrets(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "CREDENTIAL_ENCRYPTION_KEY" in result.detail
    assert "too-short" not in result.detail


# --- trading_safety_flags -------------------------------------------------


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_trading_safety_flags_accepts_falsey_allowlist(tmp_path: Path, value: str) -> None:
    env = dict(GOOD_ENV, LIVE_TRADING_ENABLED=value, JEV_ENABLED=value)
    assert run(check_trading_safety_flags(ctx(tmp_path, env))).status == Status.PASS


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "", "maybe"])
def test_trading_safety_flags_rejects_anything_else(tmp_path: Path, value: str) -> None:
    env = dict(GOOD_ENV, LIVE_TRADING_ENABLED=value)
    assert run(check_trading_safety_flags(ctx(tmp_path, env))).status == Status.FAIL


def test_trading_safety_flags_rejects_jev_enabled(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, JEV_ENABLED="true")
    result = run(check_trading_safety_flags(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "JEV_ENABLED" in result.detail


# --- llm_config -----------------------------------------------------------


def test_llm_config_accepts_local_ollama(tmp_path: Path) -> None:
    result = run(check_llm_config(ctx(tmp_path, GOOD_ENV)))
    assert result.status == Status.PASS
    assert "11434" in result.detail


def test_llm_config_rejects_remote_host(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, CUSTOM_API_URL="http://example.com:11434/v1")
    assert run(check_llm_config(ctx(tmp_path, env))).status == Status.FAIL


def test_llm_config_rejects_invalid_url(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, CUSTOM_API_URL="not a url")
    result = run(check_llm_config(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "valid URL" in result.detail


def test_llm_config_rejects_wrong_model_and_provider(tmp_path: Path) -> None:
    env = dict(GOOD_ENV, CUSTOM_MODEL="qwen2.5:7b", LLM_PROVIDER="openai")
    result = run(check_llm_config(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert "CUSTOM_MODEL" in result.detail or "LLM_PROVIDER" in result.detail


def test_llm_config_failure_never_leaks_url_credentials(tmp_path: Path) -> None:
    env = dict(
        GOOD_ENV,
        CUSTOM_API_URL="https://user:" + CANARY + "@example.com:11434/v1?token=" + CANARY,
    )
    result = run(check_llm_config(ctx(tmp_path, env)))
    assert result.status == Status.FAIL
    assert CANARY not in result.detail
