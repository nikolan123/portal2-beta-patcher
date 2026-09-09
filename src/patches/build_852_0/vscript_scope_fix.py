"""Guard 852_0 against a null VScript scope returned during entity setup. Fixes crash in mixup"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import struct

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition


ORIGINAL_SERVER_SHA256 = "1dc9c9ac0e12511b21beac4c183462df53b504920421e52e66e96e926659c948"
PATCHED_SERVER_SHA256 = "6df23190b2bf132f68ad1f57c39d0c1b798f3adc60e5994d8cfcb9758f11dd6a"

ENTRY_RVA = 0xBBAA6
CONTINUE_RVA = 0xBBAAC
RETURN_RVA = 0xBBACC
CODE_CAVE_RVA = 0x415E10
ORIGINAL_TEXT_SIZE = 0x414E0A
PATCHED_TEXT_SIZE = 0x414E30
ORIGINAL_ENTRY = bytes.fromhex("89 86 84 03 00 00")


def _relative_32(source_end_rva: int, target_rva: int) -> bytes:
    return struct.pack("<i", target_rva - source_end_rva)


def _section(original: bytes, name: bytes) -> tuple[int, int, int, int, int]:
    if len(original) < 0x40:
        raise PatchError("Server.dll is too small to contain a PE header")
    pe_offset = struct.unpack_from("<I", original, 0x3C)[0]
    if original[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise PatchError("Server.dll does not contain a valid PE header")
    section_count = struct.unpack_from("<H", original, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", original, pe_offset + 20)[0]
    section_table = pe_offset + 24 + optional_size
    for index in range(section_count):
        header = section_table + index * 40
        if original[header:header + 8].rstrip(b"\0") == name:
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", original, header + 8
            )
            return header, virtual_size, virtual_address, raw_size, raw_offset
    raise PatchError(f"Server.dll does not contain the {name.decode()} section")


def _raw_offset(rva: int, virtual_address: int, raw_size: int, raw_offset: int) -> int:
    section_offset = rva - virtual_address
    if section_offset < 0 or section_offset >= raw_size:
        raise PatchError("Server.dll patch address is outside the .text section")
    return raw_offset + section_offset


def patch_server(original: bytes) -> bytes:
    header, virtual_size, virtual_address, raw_size, raw_offset = _section(original, b".text")
    if virtual_size != ORIGINAL_TEXT_SIZE:
        raise PatchError("Server.dll does not contain the expected .text section")

    entry_offset = _raw_offset(ENTRY_RVA, virtual_address, raw_size, raw_offset)
    cave_offset = _raw_offset(CODE_CAVE_RVA, virtual_address, raw_size, raw_offset)
    if original[entry_offset:entry_offset + len(ORIGINAL_ENTRY)] != ORIGINAL_ENTRY:
        raise PatchError("Server.dll does not contain the expected VScript scope instruction")

    cave = (
        b"\x85\xC0"  # test eax, eax
        + b"\x0F\x84" + _relative_32(CODE_CAVE_RVA + 8, RETURN_RVA)  # je return
        + ORIGINAL_ENTRY
        + b"\xE9" + _relative_32(CODE_CAVE_RVA + 19, CONTINUE_RVA)  # jmp continuation
    )
    if original[cave_offset:cave_offset + len(cave)] != bytes(len(cave)):
        raise PatchError("Server.dll VScript patch area is not empty")

    patched = bytearray(original)
    patched[entry_offset:entry_offset + len(ORIGINAL_ENTRY)] = (
        b"\xE9" + _relative_32(ENTRY_RVA + 5, CODE_CAVE_RVA) + b"\x90"
    )
    patched[cave_offset:cave_offset + len(cave)] = cave
    struct.pack_into("<I", patched, header + 8, PATCHED_TEXT_SIZE)
    return bytes(patched)


def server_path(root: Path) -> Path:
    candidates = (
        root / "portal2" / "bin" / "Server.dll",
        root / "game" / "portal2" / "bin" / "Server.dll",
    )
    existing = tuple(path for path in candidates if path.is_file())
    if not existing:
        raise PatchError("852_0 Server.dll is missing")
    if len(existing) != 1:
        raise PatchError("Found more than one 852_0 Server.dll")
    return existing[0]


class VScriptScopeFixPatch:
    id = "852_0.vscript_scope_fix"
    display_name = "Mixup turret crash fix"
    description = "Prevent the p2_lab_mixup turret crash and similar crashes when an entity script scope cannot be created."

    def check(self, context: PatchContext) -> bool:
        path = server_path(context.root)
        current_hash = sha256_file(path)
        if current_hash == PATCHED_SERVER_SHA256:
            return False
        if current_hash != ORIGINAL_SERVER_SHA256:
            raise PatchError(f"Refusing to patch unknown Server.dll ({current_hash})")
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        path = server_path(context.root)
        original = path.read_bytes()
        if sha256(original).hexdigest() != ORIGINAL_SERVER_SHA256:
            raise PatchError("Server.dll changed before it could be patched")

        progress(ProgressEvent(self.id, 0, 1, "Adding the VScript scope guard"))
        backup_file(path, "server.original.bak", context)
        patched = patch_server(original)
        if sha256(patched).hexdigest() != PATCHED_SERVER_SHA256:
            raise PatchError("Internal Server.dll verification failed")
        atomic_write(path, patched)
        progress(ProgressEvent(self.id, 1, 1, "Installed the VScript crash fix"))

    def verify(self, context: PatchContext) -> None:
        if sha256_file(server_path(context.root)) != PATCHED_SERVER_SHA256:
            raise PatchError("VScript crash fix failed verification")


DEFINITION = PatchDefinition(VScriptScopeFixPatch())
