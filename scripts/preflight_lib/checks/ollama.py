"""Ollama warm-up and checks 17-19.

Requests are read-only and local. Response bodies are never echoed, except for
the warm-up error text (sanitized by the CLI).
"""

from __future__ import annotations

import httpx

from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:1.5b"
WARMUP_TIMEOUT = 30.0

_WARMUP_PROMPT = "Reply with OK."
_GENERATE_BODY = {
    "model": OLLAMA_MODEL,
    "prompt": _WARMUP_PROMPT,
    "stream": False,
    "options": {"num_predict": 1},
}


async def _request_json(
    *,
    transport: httpx.AsyncBaseTransport | None,
    base_url: str,
    timeout: float,
    method: str,
    path: str,
    json_body: dict | None = None,
) -> tuple[object | None, str | None]:
    try:
        async with httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout
        ) as client:
            response = await client.request(method, path, json=json_body)
    except httpx.TimeoutException:
        return None, f"timeout after {timeout:g}s"
    except httpx.HTTPError as exc:
        return None, f"request error ({type(exc).__name__})"

    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    try:
        return response.json(), None
    except ValueError:
        return None, "invalid JSON response"


async def warm_up_ollama(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = WARMUP_TIMEOUT,
) -> str | None:
    """Load the model before the registry runs. Return an error string on failure."""
    data, error = await _request_json(
        transport=transport,
        base_url=base_url,
        timeout=timeout,
        method="POST",
        path="/api/generate",
        json_body=_GENERATE_BODY,
    )
    if error is not None:
        return error
    if isinstance(data, dict) and data.get("error"):
        return f"ollama error: {str(data['error'])[:120]}"
    return None


async def check_ollama_service(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 2.0,
) -> CheckResult:
    data, error = await _request_json(
        transport=transport,
        base_url=base_url,
        timeout=timeout,
        method="GET",
        path="/api/version",
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version.strip():
        return CheckResult(Status.FAIL, "response has no version")
    return CheckResult(Status.PASS, f"ollama {version.strip()}")


async def check_ollama_model(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 5.0,
) -> CheckResult:
    data, error = await _request_json(
        transport=transport,
        base_url=base_url,
        timeout=timeout,
        method="GET",
        path="/api/tags",
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return CheckResult(Status.FAIL, "response has no models list")

    names: set[str] = set()
    for entry in models:
        if not isinstance(entry, dict):
            continue
        for key in ("name", "model"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())

    if OLLAMA_MODEL not in names:
        return CheckResult(
            Status.FAIL, f"model {OLLAMA_MODEL} not found (exact tag required)"
        )
    return CheckResult(Status.PASS, f"model {OLLAMA_MODEL} present")


async def check_ollama_smoke(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 15.0,
) -> CheckResult:
    data, error = await _request_json(
        transport=transport,
        base_url=base_url,
        timeout=timeout,
        method="POST",
        path="/api/generate",
        json_body=_GENERATE_BODY,
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)
    if isinstance(data, dict) and data.get("error"):
        return CheckResult(Status.FAIL, "model returned an error")
    return CheckResult(Status.PASS, "model generated 1 token")


OLLAMA_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="ollama_service",
        title="Ollama responds on 127.0.0.1:11434",
        severity=Severity.CRITICAL,
        timeout=2.0,
        runner=check_ollama_service,
        requires="ollama",
        tags=("local", "ollama"),
    ),
    CheckSpec(
        id="ollama_model",
        title=f"Model {OLLAMA_MODEL} present",
        severity=Severity.CRITICAL,
        timeout=5.0,
        runner=check_ollama_model,
        requires="ollama",
        tags=("local", "ollama"),
    ),
    CheckSpec(
        id="ollama_smoke",
        title="Model generates one token after warm-up",
        severity=Severity.CRITICAL,
        timeout=15.0,
        runner=check_ollama_smoke,
        requires="ollama",
        tags=("local", "ollama"),
    ),
)
