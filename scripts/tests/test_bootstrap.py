"""Bootstrap tests: wrapper script and interpreter guard (EP-02).

These tests do not touch the network, the real .env, or any secret value.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
WRAPPER = SCRIPTS_DIR / "preflight"

sys.path.insert(0, str(SCRIPTS_DIR))

import preflight_check  # noqa: E402  (path setup must happen first)


def test_interpreter_error_accepts_expected_venv() -> None:
    expected = Path("/repo/scripts/.venv")
    assert preflight_check.interpreter_error((3, 12, 15), str(expected), expected) is None


def test_interpreter_error_rejects_host_python() -> None:
    expected = Path("/repo/scripts/.venv")
    message = preflight_check.interpreter_error((3, 14, 4), str(expected), expected)
    assert message is not None
    assert "3.12" in message


def test_interpreter_error_rejects_foreign_prefix() -> None:
    expected = Path("/repo/scripts/.venv")
    message = preflight_check.interpreter_error((3, 12, 15), "/usr", expected)
    assert message is not None
    assert "scripts/.venv" in message


def test_main_returns_2_without_traceback_when_guard_fails(capsys) -> None:
    code = preflight_check.main(
        [], version_info=(3, 14, 4), prefix="/usr", expected_prefix=Path("/repo/scripts/.venv")
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    assert "3.12" in captured.err


def test_main_returns_0_when_guard_passes() -> None:
    expected = Path("/repo/scripts/.venv")
    code = preflight_check.main(
        [], version_info=(3, 12, 15), prefix=str(expected), expected_prefix=expected
    )
    assert code == 0


def _install_wrapper(root: Path) -> Path:
    """Create <root>/scripts/preflight from the real wrapper (no venv)."""
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "preflight"
    wrapper.write_text(WRAPPER.read_text())
    wrapper.chmod(0o755)
    return wrapper


def _install_fake_venv(root: Path, body: str) -> Path:
    """Create <root>/scripts/.venv/bin/python running `body` instead of CPython."""
    scripts = root / "scripts"
    fake_python = scripts / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\n" + body)
    fake_python.chmod(0o755)
    return scripts / "preflight"


def test_wrapper_exits_2_with_instructions_when_venv_missing(tmp_path: Path) -> None:
    wrapper = _install_wrapper(tmp_path)
    proc = subprocess.run(
        [str(wrapper), "--profile", "phase0"], capture_output=True, text=True, timeout=10
    )
    assert proc.returncode == 2
    assert "uv venv" in proc.stderr


def test_wrapper_forwards_arguments_to_venv_python(tmp_path: Path) -> None:
    _install_wrapper(tmp_path)
    wrapper = _install_fake_venv(tmp_path, 'shift\nprintf "%s\\n" "$@"\n')
    proc = subprocess.run(
        [str(wrapper), "--profile", "phase0", "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.split() == ["--profile", "phase0", "--json"]


def test_wrapper_runs_the_preflight_entrypoint(tmp_path: Path) -> None:
    _install_wrapper(tmp_path)
    wrapper = _install_fake_venv(tmp_path, 'echo "$1"\n')
    proc = subprocess.run([str(wrapper)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stdout.strip().endswith("scripts/preflight_check.py")
