"""Patch 15: Increase the tier0 thread id table in 852_1."""
from __future__ import annotations

from hashlib import sha256

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.p7_hammer import patch_tier0


ORIGINAL_TIER0_SHA256 = "e4780fe1f296aa4c38118c73a74feedd33841c5985c08044c864215a082cfd4c"
PATCHED_TIER0_SHA256 = "c8b7409f17ffa56ce350601b5d0d0308c25c6eaa734b9c4cd07e4e0c7d16f9d9"
OLD_TABLE_ADDRESS = 0x10057468
EXPECTED_REFERENCE_OFFSETS = [0xEDC2, 0xEE0D, 0xEE73]


def patch_852_1_tier0(original: bytes) -> bytes:
    return patch_tier0(
        original,
        old_table_address=OLD_TABLE_ADDRESS,
        expected_reference_offsets=EXPECTED_REFERENCE_OFFSETS,
        expected_build="852_1",
    )


class Tier0ThreadLimit8521Patch:
    id = "p15"
    display_name = "Tier0 Thread Limit"
    description = "Increase this build's tier0.dll thread limit. Fixes Hammer on some CPUs."

    def _path(self, context: PatchContext):
        return context.root / "bin" / "tier0.dll"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        if not path.is_file():
            raise PatchError("852_1 tier0.dll is missing")
        current_hash = sha256_file(path)
        if current_hash == PATCHED_TIER0_SHA256:
            return False
        if current_hash != ORIGINAL_TIER0_SHA256:
            raise PatchError(f"Refusing to patch unknown tier0.dll ({current_hash})")
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        path = self._path(context)
        original = path.read_bytes()
        if sha256(original).hexdigest() != ORIGINAL_TIER0_SHA256:
            raise PatchError("tier0.dll changed before it could be patched")
        progress(ProgressEvent(self.id, 0, 1, "Increasing the tier0 thread-ID limit"))
        backup_file(path, "tier0.original.bak", context)
        patched = patch_852_1_tier0(original)
        if sha256(patched).hexdigest() != PATCHED_TIER0_SHA256:
            raise PatchError("Internal tier0.dll verification failed")
        atomic_write(path, patched)
        progress(ProgressEvent(self.id, 1, 1, "Increased the tier0 thread-ID limit"))

    def verify(self, context: PatchContext) -> None:
        path = self._path(context)
        if not path.is_file() or sha256_file(path) != PATCHED_TIER0_SHA256:
            raise PatchError("tier0.dll thread-ID patch failed verification")
