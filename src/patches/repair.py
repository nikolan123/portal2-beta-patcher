"""Repair location-dependent files after a patched build is moved."""
from __future__ import annotations

from pathlib import Path

from patches.base import PatchError, sha256_file
from patches.build_852_0.hammer import repair_moved_tools as repair_852_0_tools
from patches.build_852_1.hammer import PATCHED_TIER0_SHA256 as PATCHED_852_1_TIER0_SHA256
from patches.build_852_1.hammer import repair_moved_tools as repair_852_1_tools
from patches.build_852_2.hammer import PATCHED_TIER0_SHA256 as PATCHED_852_2_TIER0_SHA256
from patches.build_852_2.hammer import repair_moved_tools as repair_852_2_tools


def repair_moved_build(root: Path) -> str:
    """Detect a supported patched layout, repair it, and return its build name."""
    root = root.expanduser().resolve()
    if (root / "game" / "bin" / "hammer.exe").is_file():
        repair_852_0_tools(root)
        return "852_0"
    if (root / "bin" / "hammer.exe").is_file():
        tier0 = root / "bin" / "tier0.dll"
        if tier0.is_file():
            tier0_hash = sha256_file(tier0)
            if tier0_hash == PATCHED_852_1_TIER0_SHA256:
                repair_852_1_tools(root)
                return "852_1"
            if tier0_hash == PATCHED_852_2_TIER0_SHA256:
                repair_852_2_tools(root)
                return "852_2"
    raise PatchError("This folder does not contain a supported patched Hammer build")
