"""Read ``.env`` into a plain mapping without touching ``os.environ``.

Parser failures are converted into :class:`EnvLoadError` messages that contain
only the file path, an error kind and (when known) a line number. Raw lines,
values and original exception text are never included, so a broken ``.env``
cannot leak a secret through stderr or a traceback.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

from dotenv import dotenv_values

_DOTENV_LOGGER = "dotenv"


class EnvLoadError(RuntimeError):
    """Raised when the .env file cannot be read or parsed."""


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


def load_env_file(path: Path) -> dict[str, str]:
    """Return key/value pairs from *path*; never mutates ``os.environ``."""
    env_path = Path(path)

    try:
        if not env_path.exists():
            raise EnvLoadError(f"cannot load {env_path}: missing")
        if not env_path.is_file():
            raise EnvLoadError(f"cannot load {env_path}: not_a_file")
    except OSError as exc:
        raise EnvLoadError(f"cannot load {env_path}: unreadable ({_kind(exc)})") from None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logging.getLogger(_DOTENV_LOGGER).setLevel(logging.CRITICAL)
            values = dotenv_values(env_path, interpolate=False)
    except OSError as exc:
        raise EnvLoadError(f"cannot load {env_path}: unreadable ({_kind(exc)})") from None
    except Exception as exc:  # noqa: BLE001 - converted to a sanitized error
        raise EnvLoadError(f"cannot load {env_path}: parse_error ({_kind(exc)})") from None

    return {key: value for key, value in values.items() if value is not None}
