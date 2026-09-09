"""Repair location-dependent files after a patched build is moved."""
from __future__ import annotations

from pathlib import Path

from patches.base import PatchError
from patches.build_852_0.hammer import repair_moved_tools as repair_852_0_tools
from patches.build_852_2.hammer import repair_moved_tools as repair_852_2_tools


def repair_moved_build(root: Path) -> str:
    """Detect a supported patched layout, repair it, and return its build name."""
    root = root.expanduser().resolve()
    if (root / "game" / "bin" / "hammer.exe").is_file():
        repair_852_0_tools(root)
        return "852_0"
    if (root / "bin" / "hammer.exe").is_file():
        repair_852_2_tools(root)
        return "852_2"
    raise PatchError("This folder does not contain a supported patched Hammer build (852_0 or 852_2)")
