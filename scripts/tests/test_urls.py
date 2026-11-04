"""TDD tests for safe_url() credential redaction (EP-03b).

All values are synthetic (FAKE_*); the real .env is never read.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.urls import safe_url  # noqa: E402


def test_safe_url_strips_userinfo_query_and_fragment() -> None:
    url = (
        "https://user:FAKE_PASSWORD_FOR_TEST@example.com:8443/v1/models"
        "?token=FAKE_TOKEN#frag"
    )
    out = safe_url(url)
    assert "user" not in out
    assert "FAKE_PASSWORD_FOR_TEST" not in out
    assert "FAKE_TOKEN" not in out
    assert "frag" not in out
    assert out == "https://example.com:8443/v1/models"


def test_safe_url_keeps_plain_localhost_url() -> None:
    assert safe_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"


def test_safe_url_normalizes_trailing_slash() -> None:
    assert safe_url("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434/v1"


def test_safe_url_rejects_empty_or_missing_scheme() -> None:
    assert safe_url("") == "<invalid-url>"
    assert safe_url("127.0.0.1:11434") == "<invalid-url>"


def test_safe_url_does_not_leak_query_when_no_host() -> None:
    out = safe_url("https://?token=FAKE_TOKEN_FOR_TEST")
    assert "FAKE_TOKEN_FOR_TEST" not in out
