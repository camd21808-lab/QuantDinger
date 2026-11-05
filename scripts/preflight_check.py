"""Preflight CLI entrypoint.

The bootstrap guard runs before any third-party import so that a wrong
interpreter fails fast with exit code 2 instead of an ImportError traceback.
"""

from __future__ import annotations

import sys

from preflight_lib.bootstrap import (  # noqa: F401 - re-exported for tests
    EXIT_CONFIG_ERROR,
    REQUIRED_PYTHON,
    expected_venv_prefix,
    interpreter_error,
)


def main(
    argv: list[str] | None = None,
    version_info: tuple[int, ...] | None = None,
    prefix: str | None = None,
    expected_prefix=None,  # type: ignore[no-untyped-def]
) -> int:
    """Run the interpreter guard, then hand over to the CLI."""
    args = list(sys.argv[1:] if argv is None else argv)
    version = version_info if version_info is not None else sys.version_info
    current_prefix = prefix if prefix is not None else sys.prefix
    expected = expected_prefix if expected_prefix is not None else expected_venv_prefix()

    error = interpreter_error(tuple(version), current_prefix, expected)
    if error is not None:
        print(f"CONFIG ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # Imported only after the guard: the CLI may load third-party modules.
    from preflight_lib.cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
