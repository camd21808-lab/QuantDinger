"""TDD tests for EP-08: Ollama warm-up and the 3 Ollama checks.

All HTTP is served by httpx.MockTransport; no real network access.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib import cli  # noqa: E402
from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.ollama import (  # noqa: E402
    OLLAMA_MODEL,
    check_ollama_model,
    check_ollama_service,
    check_ollama_smoke,
    warm_up_ollama,
)
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

CANARY = "FAKE_SECRET_FOR_TEST_ONLY_0123456789"


def ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())


def run(coro):
    return asyncio.run(coro)


def handler_for(routes: dict[str, object]):
    """Map ``(method, path)`` to a response dict, text or an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        outcome = routes.get(key)
        if outcome is None:
            return httpx.Response(404)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        if isinstance(outcome, dict):
            return httpx.Response(200, json=outcome)
        return httpx.Response(200, text=str(outcome))

    return handler


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --- warm-up --------------------------------------------------------------


def test_warmup_sends_small_non_streaming_generate_request(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "done": True})

    result = run(warm_up_ollama(ctx(tmp_path), transport=transport(handler)))
    assert result is None
    assert seen["path"] == "/api/generate"
    assert seen["body"]["stream"] is False
    assert seen["body"]["model"] == OLLAMA_MODEL


def test_warmup_reports_timeout(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    error = run(warm_up_ollama(ctx(tmp_path), transport=transport(handler), timeout=0.1))
    assert error is not None and "timeout" in error


def test_warmup_reports_connection_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    error = run(warm_up_ollama(ctx(tmp_path), transport=transport(handler)))
    assert error is not None and "error" in error.lower()


def test_warmup_non_200_is_an_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    error = run(warm_up_ollama(ctx(tmp_path), transport=transport(handler)))
    assert error is not None and "500" in error


def test_warmup_200_with_error_key_is_an_error(tmp_path: Path) -> None:
    error = run(
        warm_up_ollama(
            ctx(tmp_path),
            transport=transport(
                handler_for({("POST", "/api/generate"): {"error": "model not found"}})
            ),
        )
    )
    assert error is not None
    assert "model not found" in error


# --- ollama_service -------------------------------------------------------


def test_service_passes_with_version(tmp_path: Path) -> None:
    result = run(
        check_ollama_service(
            ctx(tmp_path),
            transport=transport(handler_for({("GET", "/api/version"): {"version": "0.40.14"}})),
        )
    )
    assert result.status == Status.PASS
    assert "0.40.14" in result.detail


def test_service_fails_without_version_key(tmp_path: Path) -> None:
    result = run(
        check_ollama_service(
            ctx(tmp_path), transport=transport(handler_for({("GET", "/api/version"): {}}))
        )
    )
    assert result.status == Status.FAIL
    assert "version" in result.detail.lower()


def test_service_fails_on_non_200(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = run(check_ollama_service(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert "503" in result.detail


def test_service_reports_timeout(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    result = run(check_ollama_service(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert "timeout" in result.detail


def test_service_reports_invalid_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    result = run(check_ollama_service(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert "JSON" in result.detail


# --- ollama_model ---------------------------------------------------------


def tags(*names: str) -> dict:
    return {"models": [{"name": name, "model": name} for name in names]}


def test_model_passes_with_exact_tag(tmp_path: Path) -> None:
    result = run(
        check_ollama_model(
            ctx(tmp_path),
            transport=transport(handler_for({("GET", "/api/tags"): tags(OLLAMA_MODEL)})),
        )
    )
    assert result.status == Status.PASS
    assert OLLAMA_MODEL in result.detail


def test_model_rejects_near_miss_tag(tmp_path: Path) -> None:
    result = run(
        check_ollama_model(
            ctx(tmp_path),
            transport=transport(
                handler_for({("GET", "/api/tags"): tags("qwen2.5:1.5b-instruct")})
            ),
        )
    )
    assert result.status == Status.FAIL
    assert OLLAMA_MODEL in result.detail


def test_model_fails_on_non_200(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    result = run(check_ollama_model(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL


def test_model_fails_when_models_is_not_a_list(tmp_path: Path) -> None:
    result = run(
        check_ollama_model(
            ctx(tmp_path),
            transport=transport(handler_for({("GET", "/api/tags"): {"models": "x"}})),
        )
    )
    assert result.status == Status.FAIL
    assert "models" in result.detail


# --- ollama_smoke ---------------------------------------------------------


def test_smoke_passes_on_http_200(tmp_path: Path) -> None:
    result = run(
        check_ollama_smoke(
            ctx(tmp_path),
            transport=transport(
                handler_for({("POST", "/api/generate"): {"response": "a", "done": True}})
            ),
        )
    )
    assert result.status == Status.PASS


def test_smoke_failure_never_leaks_response_body(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": CANARY})

    result = run(check_ollama_smoke(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert CANARY not in result.detail
    assert "500" in result.detail


def test_smoke_does_not_retry(tmp_path: Path) -> None:
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    result = run(check_ollama_smoke(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert calls[0] == 1
    assert "timeout" in result.detail


def test_smoke_fails_on_invalid_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    result = run(check_ollama_smoke(ctx(tmp_path), transport=transport(handler)))
    assert result.status == Status.FAIL
    assert "JSON" in result.detail


def test_warmup_fails_on_invalid_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    error = run(warm_up_ollama(ctx(tmp_path), transport=transport(handler)))
    assert error is not None
    assert "JSON" in error


# --- registry metadata ----------------------------------------------------


def test_registry_contains_ollama_checks_in_order() -> None:
    registry = build_registry()
    assert [spec.id for spec in registry.specs()][16:19] == [
        "ollama_service",
        "ollama_model",
        "ollama_smoke",
    ]
    by_id = {spec.id: spec for spec in registry.specs()}
    assert by_id["ollama_service"].severity == Severity.CRITICAL
    assert by_id["ollama_service"].timeout == 2.0
    assert by_id["ollama_model"].timeout == 5.0
    assert by_id["ollama_smoke"].timeout == 15.0
    assert all("ollama" in by_id[name].tags for name in (
        "ollama_service",
        "ollama_model",
        "ollama_smoke",
    ))


# --- CLI wiring -----------------------------------------------------------


def ollama_registry() -> Registry:
    async def runner(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS)

    registry = Registry()
    registry.register(
        CheckSpec(
            id="fake_ollama",
            title="fake",
            severity=Severity.CRITICAL,
            timeout=1.0,
            runner=runner,
            tags=("ollama",),
        )
    )
    return registry


def test_cli_warmup_failure_exits_2(tmp_path: Path, capsys, monkeypatch) -> None:
    async def failing(_ctx: CheckContext) -> str:
        return "connection refused"

    monkeypatch.setattr(cli, "warm_up_ollama", failing)
    code = cli.main([], registry=ollama_registry(), context=ctx(tmp_path))
    captured = capsys.readouterr()
    assert code == 2
    assert "warm-up" in captured.err.lower()


def test_cli_runs_warmup_once_when_ollama_checks_present(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls = [0]

    async def ok(_ctx: CheckContext) -> None:
        calls[0] += 1

    monkeypatch.setattr(cli, "warm_up_ollama", ok)
    assert cli.main([], registry=ollama_registry(), context=ctx(tmp_path)) == 0
    assert calls[0] == 1


def test_cli_skips_warmup_when_no_ollama_checks(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls = [0]

    async def ok(_ctx: CheckContext) -> None:
        calls[0] += 1

    async def runner(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS)

    monkeypatch.setattr(cli, "warm_up_ollama", ok)
    registry = Registry()
    registry.register(
        CheckSpec(
            id="plain",
            title="plain",
            severity=Severity.CRITICAL,
            timeout=1.0,
            runner=runner,
        )
    )
    assert cli.main([], registry=registry, context=ctx(tmp_path)) == 0
    assert calls[0] == 0
