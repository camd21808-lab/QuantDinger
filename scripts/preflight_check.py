#!/usr/bin/env python3
"""Preflight CLI entrypoint.

The bootstrap guard runs before any third-party import so that a wrong
interpreter fails fast with exit code 2 instead of an ImportError traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_PYTHON = (3, 12)
EXIT_CONFIG_ERROR = 2


def expected_venv_prefix(repo_root: Path | None = None) -> Path:
    """Return the required scripts/.venv prefix for this checkout."""
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[1]
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


def main(
    argv: list[str] | None = None,
    version_info: tuple[int, ...] | None = None,
    prefix: str | None = None,
    expected_prefix: Path | None = None,
) -> int:
    """Run the interpreter guard. The CLI itself is wired in a later task."""
    args = list(sys.argv[1:] if argv is None else argv)
    version = version_info if version_info is not None else sys.version_info
    current_prefix = prefix if prefix is not None else sys.prefix
    expected = expected_prefix if expected_prefix is not None else expected_venv_prefix()

    error = interpreter_error(tuple(version), current_prefix, expected)
    if error is not None:
        print(f"preflight: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # Imported only after the guard: the CLI may load third-party modules.
    from preflight_lib.cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
