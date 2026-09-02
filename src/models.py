from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Protocol


@dataclass(frozen=True)
class BuildInputs:
    blob_path: Path
    dat_path: Path
    hl2_path: Path
    output_path: Path


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    completed: int
    total: int
    message: str


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class BuildReport:
    app_version: str = "0.1.0"
    input_hashes: dict[str, str] = field(default_factory=dict)
    extraction: dict[str, object] = field(default_factory=dict)
    hl2_archives: list[dict[str, object]] = field(default_factory=list)
    patches: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backups: list[str] = field(default_factory=list)


@dataclass
class PatchContext:
    root: Path
    hl2_source: Path
    report: BuildReport
    cancel_event: Event


class Patch(Protocol):
    id: str
    display_name: str

    def check(self, context: PatchContext) -> bool: ...
    def apply(self, context: PatchContext, progress: ProgressCallback) -> None: ...
    def verify(self, context: PatchContext) -> None: ...


class BuildCancelled(RuntimeError):
    pass

