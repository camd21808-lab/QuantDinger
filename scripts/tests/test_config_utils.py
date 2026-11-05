"""TDD tests for the .env loader and secret sanitizer (EP-03a).

All values are synthetic (FAKE_*); the real .env is never read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.env_loader import EnvLoadError, load_env_file  # noqa: E402
from preflight_lib.sanitizer import REDACTED, Sanitizer  # noqa: E402

CANARY = "FAKE_CANARY_VALUE_0123456789"


def _write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# --- loader ---------------------------------------------------------------


def test_loads_mapping_and_ignores_comments(tmp_path: Path) -> None:
    env = _write_env(
        tmp_path / ".env",
        "# comment\nSECRET_KEY=FAKE_SECRET_FOR_TEST_ONLY\nQUOTED='single value'\n",
    )
    values = load_env_file(env)
    assert values["SECRET_KEY"] == "FAKE_SECRET_FOR_TEST_ONLY"
    assert values["QUOTED"] == "single value"


def test_loader_does_not_mutate_os_environ(tmp_path: Path) -> None:
    env = _write_env(tmp_path / ".env", f"PREFLIGHT_TEST_ONLY_KEY={CANARY}\n")
    os.environ.pop("PREFLIGHT_TEST_ONLY_KEY", None)
    load_env_file(env)
    assert "PREFLIGHT_TEST_ONLY_KEY" not in os.environ


def test_missing_file_raises_with_kind_and_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent.env"
    with pytest.raises(EnvLoadError) as excinfo:
        load_env_file(missing)
    message = str(excinfo.value)
    assert "absent.env" in message
    assert "missing" in message


def test_directory_path_raises_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(EnvLoadError) as excinfo:
        load_env_file(tmp_path)
    assert "not_a_file" in str(excinfo.value)


def test_parser_exception_does_not_leak_value(tmp_path: Path, monkeypatch) -> None:
    env = _write_env(tmp_path / ".env", f"SECRET_KEY={CANARY}\n")

    def boom(*_args, **_kwargs):
        raise ValueError(f"could not parse SECRET_KEY={CANARY}")

    monkeypatch.setattr("preflight_lib.env_loader.dotenv_values", boom)
    with pytest.raises(EnvLoadError) as excinfo:
        load_env_file(env)
    message = str(excinfo.value)
    assert CANARY not in message
    assert "ValueError" in message
    assert ".env" in message


# --- sanitizer ------------------------------------------------------------


def test_sanitizer_redacts_known_values_of_sufficient_length() -> None:
    sanitizer = Sanitizer([CANARY, "short"])
    out = sanitizer.redact(f"value={CANARY} short=short")
    assert CANARY not in out
    assert REDACTED in out
    assert "short=short" in out


def test_sanitizer_redacts_longest_value_first() -> None:
    sanitizer = Sanitizer(["FAKE_SECRET_FOR_TEST_ONLY", "FAKE_SECRET_FOR_TEST"])
    out = sanitizer.redact("FAKE_SECRET_FOR_TEST_ONLY")
    assert out == REDACTED


def test_sanitizer_can_add_values_after_construction() -> None:
    sanitizer = Sanitizer()
    sanitizer.add(CANARY)
    assert CANARY not in sanitizer.redact(f"x {CANARY} y")


def test_sanitizer_fallback_masks_long_alphanumeric_tokens() -> None:
    sanitizer = Sanitizer()
    out = sanitizer.redact(f"boom token={CANARY}", fallback=True)
    assert CANARY not in out
    assert REDACTED in out


def test_sanitizer_without_fallback_keeps_unknown_tokens() -> None:
    sanitizer = Sanitizer()
    assert sanitizer.redact(CANARY) == CANARY


def test_sanitizer_is_idempotent() -> None:
    sanitizer = Sanitizer([CANARY])
    once = sanitizer.redact(CANARY)
    assert sanitizer.redact(once) == once


def test_sanitizer_ignores_none_empty_and_short_values() -> None:
    sanitizer = Sanitizer()
    sanitizer.add(None)
    sanitizer.add("")
    sanitizer.add("1234567")  # one short of MIN_SECRET_LENGTH
    assert sanitizer.redact("1234567") == "1234567"


def test_sanitizer_accepts_a_value_of_exactly_minimum_length() -> None:
    sanitizer = Sanitizer(["12345678"])
    assert sanitizer.redact("x12345678x") == f"x{REDACTED}x"


def test_sanitizer_does_not_duplicate_values() -> None:
    sanitizer = Sanitizer([CANARY, CANARY])
    sanitizer.add(CANARY)
    assert sanitizer.redact(CANARY) == REDACTED


def test_sanitizer_converts_non_string_input() -> None:
    sanitizer = Sanitizer([CANARY])
    assert sanitizer.redact(1234) == "1234"
    assert sanitizer.redact(None) == "None"


def test_sanitizer_fallback_leaves_short_tokens_alone() -> None:
    sanitizer = Sanitizer()
    text = "path=/tmp/x token=short"
    assert sanitizer.redact(text, fallback=True) == text


def test_sanitizer_fallback_does_not_double_redact_the_marker() -> None:
    sanitizer = Sanitizer([CANARY])
    once = sanitizer.redact(CANARY, fallback=True)
    assert sanitizer.redact(once, fallback=True) == once
