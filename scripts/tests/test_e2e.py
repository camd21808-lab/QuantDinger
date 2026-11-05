"""E2E tests for the real preflight CLI (EP-14).

These tests are opt-in: they are skipped unless ``PREFLIGHT_E2E=1`` is set.
They run the real ``scripts/preflight --profile phase0`` on this machine, so
they belong to the manual Step 8 run rather than the normal unit suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
WRAPPER = SCRIPTS_DIR / "preflight"
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib import cli  # noqa: E402
from preflight_lib.checks.network import check_binance_testnet  # noqa: E402
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("PREFLIGHT_E2E") != "1",
        reason="E2E tests are opt-in: set PREFLIGHT_E2E=1",
    ),
]


def run_preflight(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(WRAPPER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_real_phase0_preflight_exits_zero() -> None:
    result = run_preflight("--profile", "phase0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[FAIL]" not in result.stdout
    assert "Result: PASS" in result.stdout


def test_real_phase0_json_is_valid_and_secret_free() -> None:
    result = run_preflight("--profile", "phase0", "--json")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["profile"] == "phase0"
    assert payload["exit_code"] == 0
    assert payload["exit_phase"] == "run"
    assert isinstance(payload["environment"]["tooling_python"], str)
    assert payload["environment"]["tooling_python"]

    checks = payload["checks"]
    assert checks, "the phase0 profile must report its checks"
    for check in checks:
        assert "value" not in check
        assert check["severity"] in {"critical", "warning"}
        assert check["status"] in {"PASS", "FAIL", "WARN", "SKIP", "UNVERIFIED"}


def test_blocked_critical_endpoint_reports_failure_and_exit_one(
    tmp_path: Path, capsys
) -> None:
    async def blocked(_ctx: CheckContext) -> CheckResult:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("blocked by E2E test", request=request)

        async def no_sleep(_delay: float) -> None:
            return None

        return await check_binance_testnet(
            _ctx,
            transport=httpx.MockTransport(handler),
            sleep_fn=no_sleep,
            jitter_fn=lambda: 0.0,
        )

    async def passing(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS, detail="ok")

    registry = Registry()
    registry.register(
        CheckSpec(
            id="binance_testnet",
            title="Binance spot testnet reachable",
            severity=Severity.CRITICAL,
            timeout=28.0,
            runner=blocked,
            tags=("network",),
        )
    )
    registry.register(
        CheckSpec(
            id="always_pass",
            title="always pass",
            severity=Severity.CRITICAL,
            timeout=1.0,
            runner=passing,
        )
    )

    context = CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())
    code = cli.main(["--profile", "phase0"], registry=registry, context=context)
    captured = capsys.readouterr()

    assert code == 1
    assert "binance_testnet" in captured.out
    assert "[FAIL]" in captured.out
    assert "always_pass" in captured.out
    assert "ConnectError" in captured.out
