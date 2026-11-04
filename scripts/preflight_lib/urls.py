"""URL redaction: keep scheme, host, port and path; drop credentials and query.

``safe_url`` is the only function allowed to turn a configured URL into text.
It never returns userinfo, query string or fragment, so tokens embedded in
``CUSTOM_API_URL`` cannot reach logs or JSON output.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

INVALID_URL = "<invalid-url>"


def safe_url(url: object) -> str:
    """Return a credential-free representation of *url*."""
    if not isinstance(url, str) or not url.strip():
        return INVALID_URL

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return INVALID_URL

    if not parts.scheme or not parts.hostname:
        return INVALID_URL

    try:
        port = parts.port
    except ValueError:
        return INVALID_URL

    host = parts.hostname
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, netloc, path, "", ""))
