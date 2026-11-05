"""TDD tests for EP-09: retrying network checks 20-22.

All HTTP is served by httpx.MockTransport; backoff sleeps are injected so the
suite never waits on real timers.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.network import (  # noqa: E402
    BINANCE_ATTEMPT_TIMEOUT,
    DEFAULT_ATTEMPT_TIMEOUT,
    DEXSCREENER_URL,
    JUPITER_MINT,
    JUPITER_URL,
    check_binance_testnet,
    check_dexscreener,
    check_jupiter_lite,
)
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.results import Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402


def ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())


def run(coro):
    return asyncio.run(coro)


def sleeper():
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    return delays, sleep


def scripted(outcomes: list[object]):
    """Return a handler that plays *outcomes* in order, repeating the last one."""
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(calls[0], len(outcomes) - 1)
        calls[0] += 1
        outcome = outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return handler, calls


def mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def ok(json_body: object = None) -> httpx.Response:
    return httpx.Response(200, json=json_body if json_body is not None else {})


def run_binance(handler, sleep=None):
    delays, default_sleep = sleeper()
    return run(
        check_binance_testnet(
            ctx(Path("/tmp")),
            transport=mock(handler),
            sleep_fn=sleep or default_sleep,
            jitter_fn=lambda: 0.0,
        )
    ), delays


# --- attempt timeouts -----------------------------------------------------


def test_attempt_timeouts_are_the_approved_values() -> None:
    assert BINANCE_ATTEMPT_TIMEOUT == 8.0
    assert DEFAULT_ATTEMPT_TIMEOUT == 5.0


# --- binance --------------------------------------------------------------


def test_binance_passes_on_empty_json_and_sends_no_credentials(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok({})

    result = run(
        check_binance_testnet(
            ctx(tmp_path), transport=mock(handler), sleep_fn=sleeper()[1]
        )
    )
    assert result.status == Status.PASS
    assert str(seen[0].url) == "https://testnet.binance.vision/api/v3/ping"
    assert "authorization" not in seen[0].headers


def test_binance_rejects_non_empty_body(tmp_path: Path) -> None:
    handler, _ = scripted([ok({"unexpected": True})])
    result = run(
        check_binance_testnet(
            ctx(tmp_path), transport=mock(handler), sleep_fn=sleeper()[1]
        )
    )
    assert result.status == Status.FAIL
    assert "body" in result.detail.lower()


def test_binance_retries_5xx_then_passes(tmp_path: Path) -> None:
    handler, calls = scripted(
        [httpx.Response(500), httpx.Response(503), ok({})]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert calls[0] == 3
    assert delays == [0.5, 1.5]


def test_binance_fails_after_three_timeouts(tmp_path: Path) -> None:
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    result = run(
        check_binance_testnet(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert calls[0] == 3
    assert "timeout" in result.detail


def test_binance_does_not_retry_4xx(tmp_path: Path) -> None:
    handler, calls = scripted([httpx.Response(404)])
    result, delays = run_binance(handler)
    assert result.status == Status.FAIL
    assert calls[0] == 1
    assert delays == []


def test_binance_429_exhausts_retries_and_fails(tmp_path: Path) -> None:
    handler, calls = scripted([httpx.Response(429)])
    result, delays = run_binance(handler)
    assert result.status == Status.FAIL
    assert calls[0] == 3
    assert "429" in result.detail
    assert delays == [0.5, 1.5], "429 without Retry-After uses normal backoff"


def test_binance_honours_retry_after_but_caps_at_two_seconds(tmp_path: Path) -> None:
    handler, calls = scripted(
        [httpx.Response(429, headers={"Retry-After": "10"}), ok({})]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert calls[0] == 2
    assert delays == [2.0]


def test_binance_retry_after_below_cap_is_used(tmp_path: Path) -> None:
    handler, _ = scripted(
        [httpx.Response(429, headers={"Retry-After": "1"}), ok({})]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert delays == [1.0]


def test_connection_errors_are_retried_and_reported(tmp_path: Path) -> None:
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        raise httpx.ConnectError("refused", request=request)

    result = run(
        check_binance_testnet(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert calls[0] == 3
    assert "ConnectError" in result.detail


def test_invalid_json_is_not_retried(tmp_path: Path) -> None:
    handler, calls = scripted([httpx.Response(200, text="not json")])
    result = run(
        check_binance_testnet(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert calls[0] == 1
    assert "JSON" in result.detail


def test_invalid_retry_after_falls_back_to_normal_backoff(tmp_path: Path) -> None:
    handler, _ = scripted(
        [httpx.Response(429, headers={"Retry-After": "soon"}), ok({})]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert delays == [0.5]


def test_http_date_retry_after_is_ignored(tmp_path: Path) -> None:
    handler, _ = scripted(
        [
            httpx.Response(
                429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
            ),
            ok({}),
        ]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert delays == [0.5]


def test_negative_retry_after_is_clamped_to_zero(tmp_path: Path) -> None:
    handler, _ = scripted(
        [httpx.Response(429, headers={"Retry-After": "-5"}), ok({})]
    )
    result, delays = run_binance(handler)
    assert result.status == Status.PASS
    assert delays == [0.0]


def test_jitter_is_added_to_the_backoff(tmp_path: Path) -> None:
    handler, _ = scripted([httpx.Response(500), ok({})])
    delays, sleep = sleeper()
    result = run(
        check_binance_testnet(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleep,
            jitter_fn=lambda: 1.0,
        )
    )
    assert result.status == Status.PASS
    assert delays[0] == pytest.approx(0.6)


# --- jupiter --------------------------------------------------------------


def jupiter_url() -> str:
    return JUPITER_URL


def test_jupiter_passes_when_mint_key_present(tmp_path: Path) -> None:
    handler, _ = scripted([ok({JUPITER_MINT: {"usdPrice": 1.0}})])
    result = run(
        check_jupiter_lite(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.PASS
    assert JUPITER_MINT in result.detail


def test_jupiter_rejects_missing_mint_key(tmp_path: Path) -> None:
    handler, _ = scripted([ok({"other": {}})])
    result = run(
        check_jupiter_lite(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert JUPITER_MINT in result.detail


def test_jupiter_retries_then_fails_on_persistent_429(tmp_path: Path) -> None:
    handler, calls = scripted([httpx.Response(429)])
    result = run(
        check_jupiter_lite(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert calls[0] == 3


def test_jupiter_url_targets_lite_api_and_sol_mint(tmp_path: Path) -> None:
    assert jupiter_url().startswith("https://lite-api.jup.ag/price/v3?ids=")
    assert JUPITER_MINT in jupiter_url()


# --- dexscreener ----------------------------------------------------------


def test_dexscreener_passes_when_pairs_array_present(tmp_path: Path) -> None:
    handler, _ = scripted([ok({"pairs": []})])
    result = run(
        check_dexscreener(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.PASS


def test_dexscreener_rejects_missing_pairs_array(tmp_path: Path) -> None:
    handler, _ = scripted([ok({"pairs": "nope"})])
    result = run(
        check_dexscreener(
            ctx(tmp_path),
            transport=mock(handler),
            sleep_fn=sleeper()[1],
            jitter_fn=lambda: 0.0,
        )
    )
    assert result.status == Status.FAIL
    assert "pairs" in result.detail


def test_dexscreener_url_is_the_approved_endpoint(tmp_path: Path) -> None:
    assert DEXSCREENER_URL == "https://api.dexscreener.com/latest/dex/search?q=SOL"


# --- registry metadata ----------------------------------------------------


def test_registry_contains_network_checks_in_order() -> None:
    registry = build_registry()
    assert [spec.id for spec in registry.specs()][19:22] == [
        "binance_testnet",
        "jupiter_lite",
        "dexscreener",
    ]
    by_id = {spec.id: spec for spec in registry.specs()}
    for check_id in ("binance_testnet", "jupiter_lite", "dexscreener"):
        assert by_id[check_id].severity == Severity.CRITICAL
        assert "network" in by_id[check_id].tags
        assert by_id[check_id].config_failure is False
    assert by_id["binance_testnet"].timeout == 27.0
    assert by_id["jupiter_lite"].timeout == 18.0
    assert by_id["dexscreener"].timeout == 18.0
