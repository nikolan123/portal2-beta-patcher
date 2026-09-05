"""Patch 11: Enable paint for older maps that don't have the paintinmap key."""
from __future__ import annotations

from hashlib import sha256

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file


ORIGINAL_ENGINE_SHA256 = "055334bb8f29cf39ec09b927e4262399816493dcbd1072ea5e45e71e8cb1cd4a"
PATCHED_ENGINE_SHA256 = "e8f9410df0ae6b4d71b5c688963935ed6a3992f69377f160967d041d9d2bd172"
PATCH_OFFSET = 0x1CCB7
ORIGINAL_BYTES = bytes.fromhex("32 C9")
PATCHED_BYTES = bytes.fromhex("FE C1")


def patch_engine(original: bytes) -> bytes:
    end = PATCH_OFFSET + len(ORIGINAL_BYTES)
    if len(original) < end or original[PATCH_OFFSET:end] != ORIGINAL_BYTES:
        raise PatchError("engine.dll does not contain the expected paintinmap instruction")
    patched = bytearray(original)
    patched[PATCH_OFFSET:end] = PATCHED_BYTES
    return bytes(patched)


class LegacyPaintPatch:
    id = "p11"
    display_name = "Fix Paint Maps"
    description = "Enable paint by default in maps that predate the required paintinmap setting."

    def _path(self, context: PatchContext):
        return context.root / "bin" / "engine.dll"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        if not path.is_file():
            raise PatchError("852_1 engine.dll is missing")
        current_hash = sha256_file(path)
        if current_hash == PATCHED_ENGINE_SHA256:
            return False
        if current_hash != ORIGINAL_ENGINE_SHA256:
            raise PatchError(f"Refusing to patch unknown engine.dll ({current_hash})")
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        path = self._path(context)
        original = path.read_bytes()
        if sha256(original).hexdigest() != ORIGINAL_ENGINE_SHA256:
            raise PatchError("engine.dll changed before it could be patched")
        progress(ProgressEvent(self.id, 0, 1, "Patching the legacy paint-map default"))
        backup_file(path, "engine.original.bak", context)
        patched = patch_engine(original)
        if sha256(patched).hexdigest() != PATCHED_ENGINE_SHA256:
            raise PatchError("Internal engine.dll verification failed")
        atomic_write(path, patched)
        progress(ProgressEvent(self.id, 1, 1, "Enabled legacy paint maps"))

    def verify(self, context: PatchContext) -> None:
        path = self._path(context)
        if not path.is_file() or sha256_file(path) != PATCHED_ENGINE_SHA256:
            raise PatchError("Legacy paint-map engine patch failed verification")
