"""Interpreter bootstrap rules shared by the wrapper entrypoint and checks."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_PYTHON = (3, 12)
EXIT_CONFIG_ERROR = 2


def expected_venv_prefix(repo_root: Path | None = None) -> Path:
    """Return the required scripts/.venv prefix for this checkout."""
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
    return root / "scripts" / ".venv"


def interpreter_error(
    version_info: tuple[int, ...],
    prefix: str,
    expected_prefix: Path,
) -> str | None:
    """Return an action-oriented error message, or None when the interpreter is valid."""
    actual = tuple(version_info[:3])
    if tuple(version_info[:2]) != REQUIRED_PYTHON:
        return (
            f"preflight requires CPython {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}.x, "
            f"got {actual[0]}.{actual[1]}.{actual[2]}; run it through scripts/preflight"
        )
    try:
        resolved_prefix = Path(prefix).resolve()
        resolved_expected = Path(expected_prefix).resolve()
    except OSError:
        resolved_prefix = Path(prefix)
        resolved_expected = Path(expected_prefix)
    if resolved_prefix != resolved_expected:
        return (
            f"preflight must run inside scripts/.venv (prefix {resolved_expected}), "
            f"got {resolved_prefix}"
        )
    return None


def current_interpreter_error(expected_prefix: Path) -> str | None:
    """Check the running interpreter against *expected_prefix*."""
    return interpreter_error(tuple(sys.version_info), sys.prefix, expected_prefix)
