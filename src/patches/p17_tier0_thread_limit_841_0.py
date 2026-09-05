"""Patch 17: Increase the tier0 thread-ID table in pre-reset 841_0."""
from __future__ import annotations

from hashlib import sha256

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.p7_hammer import patch_tier0


TARGET_CRC = 0x83CED978
ORIGINAL_TIER0_SHA256 = "0ad3b905b9ba17c94d2536cb8d0871fd92ffdeea7d243e5e9aceb16ab52a13af"
PATCHED_TIER0_SHA256 = "b74f131b7c64a2bfaa8aa5beed50ede5c6e6a74483477c3956fe8af5ca939100"
OLD_TABLE_ADDRESS = 0x10057468
EXPECTED_REFERENCE_OFFSETS = [0xED62, 0xEDAD, 0xEE13]


def patch_841_0_tier0(original: bytes) -> bytes:
    return patch_tier0(
        original,
        old_table_address=OLD_TABLE_ADDRESS,
        expected_reference_offsets=EXPECTED_REFERENCE_OFFSETS,
        expected_build="pre-reset 841_0",
    )


class Tier0ThreadLimit8410Patch:
    id = "p17"
    display_name = "Tier0 Thread Limit"
    description = "Increase this build's tier0.dll thread-ID table from 32 slots to 128."

    def _path(self, context: PatchContext):
        return context.root / "bin" / "tier0.dll"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        if not path.is_file():
            raise PatchError("Pre-reset 841_0 tier0.dll is missing")
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
        patched = patch_841_0_tier0(original)
        if sha256(patched).hexdigest() != PATCHED_TIER0_SHA256:
            raise PatchError("Internal tier0.dll verification failed")
        atomic_write(path, patched)
        progress(ProgressEvent(self.id, 1, 1, "Increased the tier0 thread-ID limit"))

    def verify(self, context: PatchContext) -> None:
        path = self._path(context)
        if not path.is_file() or sha256_file(path) != PATCHED_TIER0_SHA256:
            raise PatchError("tier0.dll thread-ID patch failed verification")
