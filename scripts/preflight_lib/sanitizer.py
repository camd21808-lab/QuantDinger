"""Redact secret values from any text that may reach stdout, stderr or JSON.

Values shorter than :data:`MIN_SECRET_LENGTH` are ignored so that ordinary
words are never mangled. ``redact(..., fallback=True)`` additionally masks
long alphanumeric tokens, which is the safety net used on parser errors where
the concrete secret values are not known yet.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "***REDACTED***"
MIN_SECRET_LENGTH = 8

# A long token that is not part of a path or an already-redacted marker.
_FALLBACK_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{16,}(?![A-Za-z0-9+/=_-])")


class Sanitizer:
    """Holds known secret values and redacts them from text."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: list[str] = []
        for value in secrets:
            self.add(value)

    def add(self, value: str | None) -> None:
        if not value or len(value) < MIN_SECRET_LENGTH:
            return
        if value in self._secrets:
            return
        self._secrets.append(value)
        # Longest first, so a value that contains another is replaced whole.
        self._secrets.sort(key=len, reverse=True)

    def redact(self, text: object, fallback: bool = False) -> str:
        result = text if isinstance(text, str) else str(text)
        for secret in self._secrets:
            result = result.replace(secret, REDACTED)
        if fallback:
            result = _FALLBACK_TOKEN.sub(REDACTED, result)
        return result
