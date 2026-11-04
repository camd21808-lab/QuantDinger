"""Preflight CLI: profiles, argument parsing and exit-code wiring."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .checks import build_registry
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
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed usage
        return int(exc.code) if exc.code is not None else EXIT_CONFIG

    active_registry = registry if registry is not None else build_registry()

    if args.list_checks:
        _print_check_list(active_registry)
        return EXIT_OK

    try:
        specs = resolve_profile(active_registry, args.profile)
    except ProfileError as exc:
        print(f"preflight: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if not specs:
        print(
            f"preflight: check registry is empty for profile '{args.profile}'",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if context is None:
        try:
            context = build_context(args.verbose)
        except EnvLoadError as exc:
            print(f"preflight: {exc}", file=sys.stderr)
            return EXIT_CONFIG

    outcomes = asyncio.run(run_specs(specs, context))
    exit_code = classify_exit_code(outcomes)

    if args.json_output:
        sys.stdout.write(render_json(args.profile, outcomes, exit_code))
    else:
        use_color = (
            sys.stdout.isatty()
            and not args.no_color
            and "NO_COLOR" not in os.environ
        )
        sys.stdout.write(render_human(args.profile, outcomes, exit_code, use_color=use_color))

    return exit_code


__all__ = ["build_context", "build_parser", "main", "Severity"]
