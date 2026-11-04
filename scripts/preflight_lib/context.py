"""Execution context passed to every check runner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .sanitizer import Sanitizer


@dataclass
class CheckContext:
    repo_root: Path
    env: Mapping[str, str]
    sanitizer: Sanitizer = field(default_factory=Sanitizer)
    verbose: bool = False
