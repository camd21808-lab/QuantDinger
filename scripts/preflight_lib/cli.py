"""Preflight CLI: profiles, argument parsing and exit-code wiring."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .checks import build_registry
from .checks.config_secret import read_host_python_version
from .checks.ollama import warm_up_ollama
from .context import CheckContext
from .env_loader import EnvLoadError, load_env_file
from .registry import ProfileError, Registry, resolve_profile
from .reporting import render_human, render_json
from .results import Severity
from .runner import classify_exit_code, run_specs
from .sanitizer import Sanitizer

EXIT_OK = 0
EXIT_CRITICAL = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Environment preflight checks (Phase 0).",
    )
    parser.add_argument("--profile", default="phase0", help="phase profile (default: phase0)")
    parser.add_argument("--list-checks", action="store_true", help="list checks and exit")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit JSON")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--verbose", action="store_true", help="show extra diagnostics")
    return parser


def collect_environment() -> dict[str, str]:
    """Return report metadata for the two interpreters involved."""
    info = sys.version_info
    host_text = read_host_python_version() or ""
    host = host_text.removeprefix("Python ").strip() or "unknown"
    return {
        "tooling_python": f"{info.major}.{info.minor}.{info.micro}",
        "host_python": host,
    }


def _bootstrap_error(
    message: str,
    *,
    profile: str,
    json_output: bool,
    context: CheckContext | None,
) -> int:
    """Report a bootstrap/config error with the agreed prefix and exit 2."""
    sanitizer = context.sanitizer if context is not None else Sanitizer()
    safe = sanitizer.redact(message, fallback=True)
    print(f"CONFIG ERROR: {safe}", file=sys.stderr)
    if json_output:
        sys.stdout.write(
            render_json(
                profile,
                [],
                EXIT_CONFIG,
                environment=collect_environment(),
                error=safe,
            )
        )
    return EXIT_CONFIG


def _guess_profile(raw_args: list[str]) -> str:
    for index, value in enumerate(raw_args):
        if value == "--profile" and index + 1 < len(raw_args):
            return raw_args[index + 1]
        if value.startswith("--profile="):
            return value.split("=", 1)[1]
    return "unknown"


def build_context(verbose: bool) -> CheckContext:
    """Load .env into memory with the sanitizer in place. Never mutates os.environ."""
    repo_root = Path(__file__).resolve().parents[2]
    sanitizer = Sanitizer()
    values = load_env_file(repo_root / ".env")
    for value in values.values():
        sanitizer.add(value)
    return CheckContext(
        repo_root=repo_root, env=values, sanitizer=sanitizer, verbose=verbose
    )


def _print_check_list(registry: Registry) -> None:
    for spec in registry.specs():
        print(f"{spec.id:<28} {spec.severity.value:<8} timeout={spec.timeout:g}s  {spec.title}")


def main(
    argv: list[str] | None = None,
    *,
    registry: Registry | None = None,
    context: CheckContext | None = None,
) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:  # argparse already printed usage
        code = int(exc.code) if exc.code is not None else EXIT_CONFIG
        if code != EXIT_CONFIG:
            return code
        return _bootstrap_error(
            "invalid command-line arguments",
            profile=_guess_profile(raw_args),
            json_output="--json" in raw_args,
            context=context,
        )

    active_registry = registry if registry is not None else build_registry()

    if args.list_checks:
        _print_check_list(active_registry)
        return EXIT_OK

    try:
        specs = resolve_profile(active_registry, args.profile, verbose=args.verbose)
    except ProfileError as exc:
        return _bootstrap_error(
            str(exc),
            profile=args.profile,
            json_output=args.json_output,
            context=context,
        )

    if not specs:
        return _bootstrap_error(
            f"check registry is empty for profile '{args.profile}'",
            profile=args.profile,
            json_output=args.json_output,
            context=context,
        )

    if context is None:
        try:
            context = build_context(args.verbose)
        except EnvLoadError as exc:
            return _bootstrap_error(
                str(exc),
                profile=args.profile,
                json_output=args.json_output,
                context=None,
            )

    if any("ollama" in spec.tags for spec in specs):
        warmup_error = asyncio.run(warm_up_ollama(context))
        if warmup_error is not None:
            return _bootstrap_error(
                f"Ollama warm-up failed: {warmup_error}",
                profile=args.profile,
                json_output=args.json_output,
                context=context,
            )

    outcomes = asyncio.run(run_specs(specs, context))
    exit_code = classify_exit_code(outcomes)
    environment = collect_environment()

    if args.json_output:
        sys.stdout.write(
            render_json(args.profile, outcomes, exit_code, environment=environment)
        )
    else:
        use_color = (
            sys.stdout.isatty()
            and not args.no_color
            and "NO_COLOR" not in os.environ
        )
        sys.stdout.write(render_human(args.profile, outcomes, exit_code, use_color=use_color))

    return exit_code


__all__ = ["build_context", "build_parser", "main", "Severity"]
