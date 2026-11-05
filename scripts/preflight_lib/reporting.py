"""Human-readable and JSON reporters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Sequence

from .results import Severity, Status
from .runner import CheckOutcome, classify_exit_phase, effective_status

_COLORS = {
    Status.PASS: "\x1b[32m",
    Status.FAIL: "\x1b[31m",
    Status.WARN: "\x1b[33m",
    Status.SKIP: "\x1b[33m",
    Status.UNVERIFIED: "\x1b[33m",
}
_RESET = "\x1b[0m"


def _status_of(spec, result) -> Status:  # type: ignore[no-untyped-def]
    return effective_status(spec, result)


def _timestamp(generated_at: str | None) -> str:
    return generated_at or datetime.now(timezone.utc).isoformat()


def _phase_title(profile: str) -> str:
    if profile.startswith("phase"):
        return f"Phase {profile[len('phase'):]} preflight"
    return f"{profile} preflight"


def summarize(outcomes: Sequence[CheckOutcome]) -> dict[str, int]:
    summary = {"pass": 0, "fail": 0, "warn": 0, "skip": 0, "unverified": 0,
               "critical_fail": 0, "critical_unverified": 0}
    for spec, result in outcomes:
        status = _status_of(spec, result)
        summary[status.value.lower()] += 1
        if spec.severity == Severity.CRITICAL:
            if status == Status.FAIL:
                summary["critical_fail"] += 1
            elif status == Status.UNVERIFIED:
                summary["critical_unverified"] += 1
    return summary


def render_human(
    profile: str,
    outcomes: Sequence[CheckOutcome],
    exit_code: int,
    *,
    use_color: bool = False,
    generated_at: str | None = None,
) -> str:
    lines = [f"{_phase_title(profile)} — profile={profile} — {_timestamp(generated_at)}", ""]
    for spec, result in outcomes:
        status = _status_of(spec, result)
        label = f"[{status.value}]"
        if use_color:
            label = f"{_COLORS[status]}{label}{_RESET}"
        seconds = result.duration_ms / 1000
        detail = f"  {result.detail}" if result.detail else ""
        lines.append(f"{label} {spec.id:<28}{detail} {seconds:.2f}s")

    summary = summarize(outcomes)
    lines.append("")
    lines.append(
        "Summary: "
        f"{summary['pass']} PASS, {summary['warn']} WARN, {summary['fail']} FAIL "
        f"({summary['critical_fail']} critical), {summary['unverified']} UNVERIFIED"
    )
    if exit_code == 2:
        config_failures = [
            spec.id
            for spec, result in outcomes
            if spec.config_failure and result.status == Status.FAIL
        ]
        if config_failures:
            lines.append("CHECK CONFIG FAIL: " + ", ".join(config_failures))
    lines.append(f"Result: {'PASS' if exit_code == 0 else 'FAIL'} — exit {exit_code}")
    return "\n".join(lines) + "\n"


def render_json(
    profile: str,
    outcomes: Sequence[CheckOutcome],
    exit_code: int,
    *,
    environment: Mapping[str, str] | None = None,
    generated_at: str | None = None,
    error: str | None = None,
    exit_phase: str | None = None,
) -> str:
    payload = {
        "schema_version": 1,
        "profile": profile,
        "generated_at": _timestamp(generated_at),
        "environment": dict(
            environment
            if environment is not None
            else {"tooling_python": "unknown", "host_python": "unknown"}
        ),
        "checks": [
            {
                "id": spec.id,
                "title": spec.title,
                "severity": spec.severity.value,
                "status": _status_of(spec, result).value,
                "detail": result.detail,
                "duration_ms": result.duration_ms,
                "tags": list(spec.tags),
            }
            for spec, result in outcomes
        ],
        "summary": summarize(outcomes),
        "exit_code": exit_code,
        "exit_phase": exit_phase or classify_exit_phase(outcomes, exit_code),
    }
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, indent=2) + "\n"
