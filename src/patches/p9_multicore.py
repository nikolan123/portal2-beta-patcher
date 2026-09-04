"""Patch 9: disable multicore rendering"""
from __future__ import annotations

from models import PatchContext, ProgressCallback
from patches.base import atomic_write


MULTICORE_CONFIG = b"mat_queue_mode 0\r\n"


class MulticorePatch:
    id = "p9"
    display_name = "Disable Multicore Rendering"
    description = "Fixes weird reflections in some builds"

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "cfg" / "patcher_multicore.cfg"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        return not path.is_file() or path.read_bytes() != MULTICORE_CONFIG

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, MULTICORE_CONFIG)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Multicore rendering compatibility config failed verification")
