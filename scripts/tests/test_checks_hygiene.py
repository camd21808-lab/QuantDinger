"""TDD tests for EP-07: disk, git identity and secret-hygiene checks.

All subprocesses are faked; no real docker/git command runs in this file.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from preflight_lib import cli  # noqa: E402
from preflight_lib.checks import build_registry  # noqa: E402
from preflight_lib.checks.docker import CommandOutcome  # noqa: E402
from preflight_lib.checks.hygiene import (  # noqa: E402
    DISK_FREE_MIN_BYTES,
    SECRET_PATH_PATTERNS,
    check_disk_free,
    check_docker_disk_pressure,
    check_env_gitignored,
    check_git_identity,
    check_git_identity_temporary,
    parse_size,
)
from preflight_lib.context import CheckContext  # noqa: E402
from preflight_lib.registry import CheckSpec, Registry, resolve_profile  # noqa: E402
from preflight_lib.results import CheckResult, Severity, Status  # noqa: E402
from preflight_lib.sanitizer import Sanitizer  # noqa: E402

GIB = 1024**3
GB = 1000**3


def ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(repo_root=tmp_path, env={}, sanitizer=Sanitizer())


def run(coro):
    return asyncio.run(coro)


def command(returncode: int, stdout: str = "", stderr: str = ""):
    def runner(_args, _cwd, _timeout):
        return CommandOutcome(returncode, stdout, stderr)

    return runner


# --- disk_free ------------------------------------------------------------


def usage(free_bytes: int) -> tuple[int, int, int]:
    total = 200 * GIB
    return total, total - free_bytes, free_bytes


def test_disk_free_passes_at_exactly_twenty_gib(tmp_path: Path) -> None:
    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=lambda _path: usage(DISK_FREE_MIN_BYTES),
            docker_root=None,
        )
    )
    assert result.status == Status.PASS
    assert "20.00 GiB" in result.detail


def test_disk_free_fails_below_threshold(tmp_path: Path) -> None:
    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=lambda _path: usage(DISK_FREE_MIN_BYTES - 1),
            docker_root=None,
        )
    )
    assert result.status == Status.FAIL
    assert "repo" in result.detail


def test_disk_free_reports_docker_root_on_a_different_filesystem(tmp_path: Path) -> None:
    docker_root = Path("/var/lib/docker")

    def device_fn(path: Path) -> int:
        return 1 if Path(path) == tmp_path else 2

    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=lambda _path: usage(50 * GIB),
            docker_root=docker_root,
            device_fn=device_fn,
        )
    )
    assert result.status == Status.PASS
    assert "repo" in result.detail and "docker" in result.detail


def test_disk_free_same_filesystem_is_reported_once(tmp_path: Path) -> None:
    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=lambda _path: usage(50 * GIB),
            docker_root=Path("/var/lib/docker"),
            device_fn=lambda _path: 1,
        )
    )
    assert result.status == Status.PASS
    assert result.detail.count("free=") == 1


def test_disk_free_fails_when_distinct_docker_root_is_low(tmp_path: Path) -> None:
    def disk_usage(path: Path):
        if Path(path) == tmp_path:
            return usage(50 * GIB)
        return usage(DISK_FREE_MIN_BYTES - 1)

    def device_fn(path: Path) -> int:
        return 1 if Path(path) == tmp_path else 2

    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=disk_usage,
            docker_root=Path("/var/lib/docker"),
            device_fn=device_fn,
        )
    )
    assert result.status == Status.FAIL
    assert "docker" in result.detail


def test_disk_free_ignores_unknown_docker_root(tmp_path: Path) -> None:
    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=lambda _path: usage(50 * GIB),
            command_runner=command(1, "", "daemon not running"),
        )
    )
    assert result.status == Status.PASS
    assert "docker" not in result.detail


def test_disk_free_fails_when_repo_usage_raises(tmp_path: Path) -> None:
    def boom(_path):
        raise OSError("no such path")

    result = run(check_disk_free(ctx(tmp_path), disk_usage_fn=boom, docker_root=None))
    assert result.status == Status.FAIL
    assert "OSError" in result.detail


def test_disk_free_reports_unreadable_distinct_docker_root(tmp_path: Path) -> None:
    def disk_usage(path):
        if Path(path) == tmp_path:
            return usage(50 * GIB)
        raise OSError("unreadable")

    def device_fn(path: Path) -> int:
        return 1 if Path(path) == tmp_path else 2

    result = run(
        check_disk_free(
            ctx(tmp_path),
            disk_usage_fn=disk_usage,
            docker_root=Path("/var/lib/docker"),
            device_fn=device_fn,
        )
    )
    assert result.status == Status.PASS
    assert "usage unavailable" in result.detail


# --- docker_disk_pressure -------------------------------------------------


def df_rows(*sizes: str) -> str:
    return "\n".join(
        f'{{"Type":"Row{i}","Size":"{size}","Reclaimable":"0B","TotalCount":"1",'
        f'"ActiveCount":"1"}}'
        for i, size in enumerate(sizes)
    )


def test_docker_disk_pressure_passes_below_threshold(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path),
            command_runner=command(0, df_rows("1GB", "500MB")),
            total_bytes=100 * GB,
        )
    )
    assert result.status == Status.PASS
    assert "1.5" in result.detail


def test_docker_disk_pressure_warns_above_threshold(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path),
            command_runner=command(0, df_rows("81GB")),
            total_bytes=100 * GB,
        )
    )
    assert result.status == Status.WARN
    assert "81" in result.detail


def test_docker_disk_pressure_passes_at_exactly_eighty_percent(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path),
            command_runner=command(0, df_rows("80GB")),
            total_bytes=100 * GB,
        )
    )
    assert result.status == Status.PASS


def test_docker_disk_pressure_warns_when_command_fails(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path), command_runner=command(1, "", "boom"), total_bytes=100 * GB
        )
    )
    assert result.status == Status.WARN
    assert "unavailable" in result.detail


def test_docker_disk_pressure_warns_on_unparseable_output(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path), command_runner=command(0, "not json"), total_bytes=100 * GB
        )
    )
    assert result.status == Status.WARN


def test_docker_disk_pressure_warns_on_zero_total(tmp_path: Path) -> None:
    result = run(
        check_docker_disk_pressure(
            ctx(tmp_path), command_runner=command(0, df_rows("1GB")), total_bytes=0
        )
    )
    assert result.status == Status.WARN
    assert "unknown" in result.detail


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0B", 0),
        ("1kB", 1_000),
        ("1.5MB", 1_500_000),
        ("7.769GB", 7_769_000_000),
        ("2KiB", 2_048),
        ("1GiB", 1024**3),
        ("bogus", None),
        ("", None),
    ],
)
def test_parse_size_handles_docker_units(text: str, expected: int | None) -> None:
    assert parse_size(text) == expected


# --- git_identity ---------------------------------------------------------


def identity_runner(name: str | None, email: str | None):
    def runner(args, _cwd, _timeout):
        key = args[-1]
        value = name if key == "user.name" else email
        if value is None:
            return CommandOutcome(1)
        return CommandOutcome(0, value + "\n")

    return runner


def test_git_identity_passes_when_both_set(tmp_path: Path) -> None:
    result = run(
        check_git_identity(
            ctx(tmp_path), command_runner=identity_runner("Test User", "test@example.com")
        )
    )
    assert result.status == Status.PASS
    assert "user.name" in result.detail and "user.email" in result.detail


def test_git_identity_fails_when_name_missing(tmp_path: Path) -> None:
    result = run(
        check_git_identity(ctx(tmp_path), command_runner=identity_runner(None, "t@example.com"))
    )
    assert result.status == Status.FAIL
    assert "user.name" in result.detail


def test_git_identity_fails_when_email_missing(tmp_path: Path) -> None:
    result = run(
        check_git_identity(ctx(tmp_path), command_runner=identity_runner("Test User", None))
    )
    assert result.status == Status.FAIL
    assert "user.email" in result.detail


# --- git_identity_temporary ----------------------------------------------


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("haosanh-agent", "dev@example.com"),
        ("Dev", "haosanh@localhost"),
        ("HAOSANH-AGENT", "x@LOCALHOST"),
    ],
)
def test_git_identity_temporary_warns_for_temp_identities(
    tmp_path: Path, name: str, email: str
) -> None:
    result = run(
        check_git_identity_temporary(ctx(tmp_path), command_runner=identity_runner(name, email))
    )
    assert result.status == Status.WARN
    assert "temporary" in result.detail.lower()


def test_git_identity_temporary_passes_for_real_identity(tmp_path: Path) -> None:
    result = run(
        check_git_identity_temporary(
            ctx(tmp_path), command_runner=identity_runner("Real Dev", "dev@example.com")
        )
    )
    assert result.status == Status.PASS


def test_git_identity_temporary_warns_when_identity_unavailable(tmp_path: Path) -> None:
    result = run(
        check_git_identity_temporary(ctx(tmp_path), command_runner=identity_runner(None, None))
    )
    assert result.status == Status.WARN


# --- env_gitignored -------------------------------------------------------


def test_secret_patterns_are_the_seven_approved_paths() -> None:
    assert SECRET_PATH_PATTERNS == (
        ".env",
        "backend_api_python/.env",
        ".keys/",
        "secrets/",
        "*.pem",
        "*.key",
        "*.gpg",
    )


def probe_for(pattern: str) -> str:
    return {
        "*.pem": "probe.pem",
        "*.key": "probe.key",
        "*.gpg": "probe.gpg",
    }.get(pattern, pattern)


def git_runner(*, ignored: set[str], tracked: set[str]):
    """Fake git: *ignored*/*tracked* are keyed by the 7 approved patterns."""

    def runner(args, _cwd, _timeout):
        if args[:2] == ["git", "check-ignore"]:
            pattern = args[-1]
            pattern = next(
                (p for p in probe_for_all() if probe_for(p) == pattern), pattern
            )
            return CommandOutcome(0 if pattern in ignored else 1)
        if args[:2] == ["git", "ls-files"]:
            pattern = args[-1]
            pattern = next(
                (p for p in probe_for_all() if probe_for(p) == pattern), pattern
            )
            is_tracked = pattern in tracked
            if "--error-unmatch" in args:
                return CommandOutcome(0 if is_tracked else 1)
            return CommandOutcome(0, stdout="tracked-file\n" if is_tracked else "")
        return CommandOutcome(0)

    return runner


def probe_for_all() -> tuple[str, ...]:
    return SECRET_PATH_PATTERNS


def test_env_gitignored_passes_when_all_seven_are_ignored_and_untracked(
    tmp_path: Path,
) -> None:
    result = run(
        check_env_gitignored(
            ctx(tmp_path),
            command_runner=git_runner(ignored=set(SECRET_PATH_PATTERNS), tracked=set()),
        )
    )
    assert result.status == Status.PASS
    assert "7" in result.detail


def test_env_gitignored_fails_when_one_pattern_not_ignored(tmp_path: Path) -> None:
    ignored = set(SECRET_PATH_PATTERNS) - {"secrets/"}
    result = run(
        check_env_gitignored(
            ctx(tmp_path), command_runner=git_runner(ignored=ignored, tracked=set())
        )
    )
    assert result.status == Status.FAIL
    assert "secrets/" in result.detail


def test_env_gitignored_fails_when_env_is_tracked(tmp_path: Path) -> None:
    result = run(
        check_env_gitignored(
            ctx(tmp_path),
            command_runner=git_runner(
                ignored=set(SECRET_PATH_PATTERNS), tracked={".env"}
            ),
        )
    )
    assert result.status == Status.FAIL
    assert ".env" in result.detail and "tracked" in result.detail


def test_env_gitignored_fails_when_pem_is_tracked(tmp_path: Path) -> None:
    result = run(
        check_env_gitignored(
            ctx(tmp_path),
            command_runner=git_runner(
                ignored=set(SECRET_PATH_PATTERNS), tracked={"*.pem"}
            ),
        )
    )
    assert result.status == Status.FAIL
    assert "*.pem" in result.detail or "probe.pem" in result.detail


def test_env_gitignored_reports_git_failure(tmp_path: Path) -> None:
    result = run(
        check_env_gitignored(ctx(tmp_path), command_runner=command(128, "", "fatal"))
    )
    assert result.status == Status.FAIL
    assert "git" in result.detail.lower()


def test_env_gitignored_reports_missing_git_binary(tmp_path: Path) -> None:
    def runner(_args, _cwd, _timeout):
        return None

    result = run(check_env_gitignored(ctx(tmp_path), command_runner=runner))
    assert result.status == Status.FAIL
    assert "executed" in result.detail


# --- registry metadata, order and profile visibility ---------------------


def test_registry_contains_hygiene_checks_in_order() -> None:
    registry = build_registry()
    assert [spec.id for spec in registry.specs()][11:16] == [
        "disk_free",
        "docker_disk_pressure",
        "git_identity",
        "git_identity_temporary",
        "env_gitignored",
    ]
    by_id = {spec.id: spec for spec in registry.specs()}
    assert by_id["disk_free"].severity == Severity.CRITICAL
    assert by_id["docker_disk_pressure"].severity == Severity.WARNING
    assert by_id["env_gitignored"].severity == Severity.CRITICAL


def test_phase0_hides_temporary_identity_without_verbose() -> None:
    ids = [spec.id for spec in resolve_profile(build_registry(), "phase0")]
    assert "git_identity_temporary" not in ids


def test_phase0_shows_temporary_identity_with_verbose() -> None:
    ids = [spec.id for spec in resolve_profile(build_registry(), "phase0", verbose=True)]
    assert "git_identity_temporary" in ids


def test_phase1_shows_temporary_identity_by_default() -> None:
    ids = [spec.id for spec in resolve_profile(build_registry(), "phase1")]
    assert "git_identity_temporary" in ids


def test_cli_phase0_skips_hidden_check_unless_verbose(
    tmp_path: Path, capsys
) -> None:
    async def runner(_ctx: CheckContext) -> CheckResult:
        return CheckResult(Status.PASS)

    registry = Registry()
    registry.register(
        CheckSpec(
            id="visible_check",
            title="visible",
            severity=Severity.WARNING,
            timeout=1.0,
            runner=runner,
        )
    )
    registry.register(
        CheckSpec(
            id="hidden_warning",
            title="hidden",
            severity=Severity.WARNING,
            timeout=1.0,
            runner=runner,
            hide_in_phase0_unless_verbose=True,
        )
    )
    context = ctx(tmp_path)

    assert cli.main(["--profile", "phase0"], registry=registry, context=context) == 0
    output = capsys.readouterr().out
    assert "visible_check" in output and "hidden_warning" not in output

    assert (
        cli.main(["--profile", "phase0", "--verbose"], registry=registry, context=context)
        == 0
    )
    output = capsys.readouterr().out
    assert "visible_check" in output and "hidden_warning" in output
