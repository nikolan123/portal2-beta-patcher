"""
Fix known campaign progression blockers in pre-reset 841_0.

Fixes:
- Make the catapult in sp_stop_the_box react to the player.
- Make the ending of sp_glados_01 fade and continue to the next map.
- Fix the entrance door in sp_paint_stick_goo.
- Fix the entrance and exit doors in sp_paint_speed_intro.
- Fix the entrance and exit doors in sp_paint_jump_artillery.
"""
from __future__ import annotations

import struct
from pathlib import Path

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition, Resource
from patches.resources import resource_path


PACKAGE = "build_841_0_prereset/progression_fixes"
LMP_HASHES = {
    "sp_stop_the_box_l_0.lmp": "2970b6c2fc450b7a681c7accf30f64fb6c0ae6baf9cdb57d867cca3d0b6e444e",
    "sp_glados_01_l_0.lmp": "eebdafd56978c18c7a68d528c6856deeeb30959b33c00d0cc0cc0aeb0359b4bc",
}
SCRIPT_RELATIVE_PATH = Path("portal2/scripts/vscripts/transitions/sp_transition_list.nut")
SCRIPT_MARKER = b"// Portal 2 Beta Patcher progression fixes"
SCRIPT_ANCHOR = b"\t\t\t// hook up the exit elevator"
SCRIPT_LINES = (
    b"\t\t\t// Portal 2 Beta Patcher progression fixes",
    b"\t\t\tif (GetMapName() == \"sp_paint_stick_goo\")",
    b"\t\t\t{",
    b"\t\t\t\tEntFire( \"entry_door_1\", \"SetPartner\", \"@hallway_entry\", 0.0 )",
    b"\t\t\t\tEntFire( \"@hallway_entry_teleport\", \"Teleport\", 0, 0 )",
    b"\t\t\t}",
    b"",
    b"\t\t\tif (GetMapName() == \"sp_paint_speed_intro\")",
    b"\t\t\t{",
    b"\t\t\t\tEntFire( \"speed_intro_entry_door\", \"SetPartner\", \"@elevator_entry\", 0.0 )",
    b"\t\t\t\tEntFire( \"crusher_room_exit_door\", \"SetPartner\", \"@elevator_exit\", 0.0 )",
    b"\t\t\t\tEntFire( \"@elevator_entry_teleport\", \"Teleport\", 0, 0 )",
    b"\t\t\t}",
    b"",
    b"\t\t\tif (GetMapName() == \"sp_paint_jump_artillery\")",
    b"\t\t\t{",
    b"\t\t\t\tEntFire( \"artillery_entry_door\", \"SetPartner\", \"@elevator_entry\", 0.0 )",
    b"\t\t\t\tEntFire( \"artillery_exit_door\", \"SetPartner\", \"@hallway_exit\", 0.0 )",
    b"\t\t\t\tEntFire( \"@elevator_entry_teleport\", \"Teleport\", 0, 0 )",
    b"\t\t\t}",
    b"",
)


def bundled_path(name: str) -> Path:
    return resource_path(Resource(PACKAGE, name))


def transition_script_is_patched(data: bytes) -> bool:
    return all(line in data for line in SCRIPT_LINES if line)


def patch_transition_script(original: bytes) -> bytes:
    if SCRIPT_MARKER in original:
        if not transition_script_is_patched(original):
            raise PatchError("The progression-fix marker exists, but the transition fix is incomplete")
        return original
    if original.count(SCRIPT_ANCHOR) != 1:
        raise PatchError("Could not locate the transition-script insertion point")
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    insertion = newline.join(SCRIPT_LINES)
    return original.replace(SCRIPT_ANCHOR, insertion + SCRIPT_ANCHOR, 1)


def validate_lmp(name: str, data: bytes) -> None:
    if len(data) < 21:
        raise PatchError(f"Bundled progression LMP is truncated: {name}")
    offset, lump_id, version, declared_length, map_revision = struct.unpack_from("<5i", data)
    if (offset, lump_id, version, map_revision) != (20, 0, 0, 9):
        raise PatchError(f"Bundled progression LMP has an unexpected header: {name}")
    if declared_length != len(data) - offset or data[-1] != 0:
        raise PatchError(f"Bundled progression LMP has an invalid entity payload: {name}")


def read_bundled_lmp(name: str) -> bytes:
    source = bundled_path(name)
    if not source.is_file() or sha256_file(source) != LMP_HASHES[name]:
        raise PatchError(f"Bundled progression LMP is missing or damaged: {name}")
    data = source.read_bytes()
    validate_lmp(name, data)
    return data


class ProgressionFixes8410Patch:
    id = "841_0_prereset.progression_fixes"
    display_name = "Progression Fixes"
    description = "Fix several bugs that block campaign progression."

    def _script_path(self, context: PatchContext) -> Path:
        return context.root / SCRIPT_RELATIVE_PATH

    def _lmp_path(self, context: PatchContext, name: str) -> Path:
        return context.root / "portal2" / "maps" / name

    def check(self, context: PatchContext) -> bool:
        script = self._script_path(context)
        if not script.is_file():
            raise PatchError("Pre-reset 841_0 transition script is missing")
        if not transition_script_is_patched(script.read_bytes()):
            return True
        return any(
            not self._lmp_path(context, name).is_file()
            or sha256_file(self._lmp_path(context, name)) != expected_hash
            for name, expected_hash in LMP_HASHES.items()
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        script = self._script_path(context)
        if not script.is_file():
            raise PatchError("Pre-reset 841_0 transition script is missing")
        original = script.read_bytes()
        patched = patch_transition_script(original)
        if patched != original:
            backup_file(script, "sp_transition_list.original.bak", context)
            atomic_write(script, patched)
        progress(ProgressEvent(self.id, 1, 3, "Fixing paint-map transitions"))

        for index, name in enumerate(LMP_HASHES, start=2):
            data = read_bundled_lmp(name)
            destination = self._lmp_path(context, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.read_bytes() != data:
                backup_file(destination, name + ".before-progression-fixes.bak", context)
            if not destination.is_file() or destination.read_bytes() != data:
                atomic_write(destination, data)
            progress(ProgressEvent(self.id, index, 3, f"Installing {name}"))

    def verify(self, context: PatchContext) -> None:
        script = self._script_path(context)
        if not script.is_file() or not transition_script_is_patched(script.read_bytes()):
            raise PatchError("Paint-map transition fixes failed verification")
        for name, expected_hash in LMP_HASHES.items():
            destination = self._lmp_path(context, name)
            if not destination.is_file() or sha256_file(destination) != expected_hash:
                raise PatchError(f"Progression LMP failed verification: {name}")
            validate_lmp(name, destination.read_bytes())


DEFINITION = PatchDefinition(
    ProgressionFixes8410Patch(),
    resources=tuple(Resource(PACKAGE, name) for name in LMP_HASHES),
)
