"""Network checks 20-22 with bounded retries.

Rules (approved):
- at most 2 retries (3 attempts), backoff 0.5s -> 1.5s + small jitter;
- retry only on timeout, connection error, HTTP 5xx and HTTP 429;
- HTTP 429 honours ``Retry-After`` but never waits more than 2s;
- no API keys, no orders: plain read-only GETs.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from ..context import CheckContext
from ..registry import CheckSpec
from ..results import CheckResult, Severity, Status

BINANCE_URL = "https://testnet.binance.vision/api/v3/ping"
JUPITER_MINT = "So11111111111111111111111111111111111111112"
JUPITER_URL = f"https://lite-api.jup.ag/price/v3?ids={JUPITER_MINT}"
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/search?q=SOL"

BINANCE_ATTEMPT_TIMEOUT = 8.0
DEFAULT_ATTEMPT_TIMEOUT = 5.0

MAX_ATTEMPTS = 3
_BACKOFF = (0.5, 1.5)
_JITTER_MAX = 0.1
_RETRY_AFTER_CAP = 2.0

SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[], float]


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if seconds < 0:
        return 0.0
    return min(seconds, _RETRY_AFTER_CAP)


def _backoff_delay(attempt: int, jitter_fn: JitterFn) -> float:
    base = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
    return base + jitter_fn() * _JITTER_MAX


async def _fetch_json(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None,
    timeout: float,
    sleep_fn: SleepFn,
    jitter_fn: JitterFn,
) -> tuple[object | None, str | None]:
    last_error = "unknown error"
    async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
        for attempt in range(MAX_ATTEMPTS):
            retryable = False
            retry_after: float | None = None
            try:
                response = await client.get(url)
            except httpx.TimeoutException:
                last_error = f"timeout after {timeout:g}s"
                retryable = True
            except httpx.HTTPError as exc:
                last_error = f"request error ({type(exc).__name__})"
                retryable = True
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json(), None
                    except ValueError:
                        return None, "invalid JSON response"
                if status == 429:
                    last_error = "HTTP 429"
                    retryable = True
                    retry_after = _retry_after_seconds(response.headers)
                elif 500 <= status < 600:
                    last_error = f"HTTP {status}"
                    retryable = True
                else:
                    return None, f"HTTP {status}"

            if not retryable or attempt == MAX_ATTEMPTS - 1:
                break
            delay = retry_after if retry_after is not None else _backoff_delay(
                attempt, jitter_fn
            )
            await sleep_fn(delay)

    return None, last_error


async def check_binance_testnet(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep_fn: SleepFn = asyncio.sleep,
    jitter_fn: JitterFn = random.random,
    timeout: float = BINANCE_ATTEMPT_TIMEOUT,
) -> CheckResult:
    data, error = await _fetch_json(
        BINANCE_URL,
        transport=transport,
        timeout=timeout,
        sleep_fn=sleep_fn,
        jitter_fn=jitter_fn,
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)
    if data != {}:
        return CheckResult(Status.FAIL, "ping returned an unexpected body")
    return CheckResult(Status.PASS, "binance testnet reachable")


async def check_jupiter_lite(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep_fn: SleepFn = asyncio.sleep,
    jitter_fn: JitterFn = random.random,
    timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
) -> CheckResult:
    data, error = await _fetch_json(
        JUPITER_URL,
        transport=transport,
        timeout=timeout,
        sleep_fn=sleep_fn,
        jitter_fn=jitter_fn,
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)
    if not isinstance(data, dict) or JUPITER_MINT not in data:
        return CheckResult(
            Status.FAIL, f"response missing mint {JUPITER_MINT}"
        )
    return CheckResult(Status.PASS, f"jupiter lite reachable; {JUPITER_MINT} present")


async def check_dexscreener(
    ctx: CheckContext,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep_fn: SleepFn = asyncio.sleep,
    jitter_fn: JitterFn = random.random,
    timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
) -> CheckResult:
    data, error = await _fetch_json(
        DEXSCREENER_URL,
        transport=transport,
        timeout=timeout,
        sleep_fn=sleep_fn,
        jitter_fn=jitter_fn,
    )
    if error is not None:
        return CheckResult(Status.FAIL, error)
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        return CheckResult(Status.FAIL, "response has no pairs array")
    return CheckResult(Status.PASS, "dexscreener reachable")


NETWORK_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="binance_testnet",
        title="Binance spot testnet reachable",
        severity=Severity.CRITICAL,
        timeout=27.0,
        runner=check_binance_testnet,
        requires="network",
        tags=("network",),
    ),
    CheckSpec(
        id="jupiter_lite",
        title="Jupiter Lite price API reachable",
        severity=Severity.CRITICAL,
        timeout=18.0,
        runner=check_jupiter_lite,
        requires="network",
        tags=("network",),
    ),
    CheckSpec(
        id="dexscreener",
        title="DexScreener API reachable",
        severity=Severity.CRITICAL,
        timeout=18.0,
        runner=check_dexscreener,
        requires="network",
        tags=("network",),
    ),
)
