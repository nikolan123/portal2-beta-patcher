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
ORIGINAL_CLIENT_SHA256 = "329b788ff0c5e744403086eea7e455c2c113344371f072a0829dbd4f731a3d4b"
INTERMEDIATE_CLIENT_SHA256 = "ce1528360530eab7d0bce87154aa1b5eb124ed680529d9f093492a4892eab56d"
PATCHED_CLIENT_SHA256 = "29cbd597499eb70b07cdf82231f16438371673613af0ce19361abf060f674e17"

SERVER_ENTRY_RVA = 0xBBAA6
SERVER_CONTINUE_RVA = 0xBBAAC
SERVER_RETURN_RVA = 0xBBACC
SERVER_CODE_CAVE_RVA = 0x415E10
ORIGINAL_SERVER_TEXT_SIZE = 0x414E0A
PATCHED_SERVER_TEXT_SIZE = 0x414E30
ORIGINAL_SERVER_ENTRY = bytes.fromhex("89 86 84 03 00 00")

CLIENT_ENTRY_RVA = 0x2981C0
CLIENT_CONTINUE_RVA = 0x2981D1
CLIENT_ZERO_RVA = 0x2981C8
CLIENT_CODE_CAVE_RVA = 0x36E100
CLIENT_SECTION_ENTRY_RVA = 0x151568
CLIENT_SECTION_CONTINUE_RVA = 0x15156D
CLIENT_SECTION_CODE_CAVE_RVA = 0x36E120
ORIGINAL_CLIENT_TEXT_SIZE = 0x36D0EA
PATCHED_CLIENT_TEXT_SIZE = 0x36D150
ORIGINAL_CLIENT_ENTRY = bytes.fromhex("8B 44 24 08 85 C0")
ORIGINAL_CLIENT_SECTION_ENTRY = bytes.fromhex("8B 3B 8B C7 99")


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
    if virtual_size != ORIGINAL_SERVER_TEXT_SIZE:
        raise PatchError("Server.dll does not contain the expected .text section")

    entry_offset = _raw_offset(SERVER_ENTRY_RVA, virtual_address, raw_size, raw_offset)
    cave_offset = _raw_offset(SERVER_CODE_CAVE_RVA, virtual_address, raw_size, raw_offset)
    if original[entry_offset:entry_offset + len(ORIGINAL_SERVER_ENTRY)] != ORIGINAL_SERVER_ENTRY:
        raise PatchError("Server.dll does not contain the expected VScript scope instruction")

    cave = (
        b"\x85\xC0"  # test eax, eax
        + b"\x0F\x84" + _relative_32(SERVER_CODE_CAVE_RVA + 8, SERVER_RETURN_RVA)
        + ORIGINAL_SERVER_ENTRY
        + b"\xE9" + _relative_32(SERVER_CODE_CAVE_RVA + 19, SERVER_CONTINUE_RVA)
    )
    if original[cave_offset:cave_offset + len(cave)] != bytes(len(cave)):
        raise PatchError("Server.dll VScript patch area is not empty")

    patched = bytearray(original)
    patched[entry_offset:entry_offset + len(ORIGINAL_SERVER_ENTRY)] = (
        b"\xE9" + _relative_32(SERVER_ENTRY_RVA + 5, SERVER_CODE_CAVE_RVA) + b"\x90"
    )
    patched[cave_offset:cave_offset + len(cave)] = cave
    struct.pack_into("<I", patched, header + 8, PATCHED_SERVER_TEXT_SIZE)
    return bytes(patched)


def patch_client(original: bytes) -> bytes:
    header, virtual_size, virtual_address, raw_size, raw_offset = _section(original, b".text")
    if virtual_size != ORIGINAL_CLIENT_TEXT_SIZE:
        raise PatchError("Client.dll does not contain the expected .text section")

    entry_offset = _raw_offset(CLIENT_ENTRY_RVA, virtual_address, raw_size, raw_offset)
    cave_offset = _raw_offset(CLIENT_CODE_CAVE_RVA, virtual_address, raw_size, raw_offset)
    section_entry_offset = _raw_offset(CLIENT_SECTION_ENTRY_RVA, virtual_address, raw_size, raw_offset)
    section_cave_offset = _raw_offset(CLIENT_SECTION_CODE_CAVE_RVA, virtual_address, raw_size, raw_offset)
    if original[entry_offset:entry_offset + len(ORIGINAL_CLIENT_ENTRY)] != ORIGINAL_CLIENT_ENTRY:
        raise PatchError("Client.dll does not contain the expected animation decoder instructions")
    if original[section_entry_offset:section_entry_offset + len(ORIGINAL_CLIENT_SECTION_ENTRY)] != ORIGINAL_CLIENT_SECTION_ENTRY:
        raise PatchError("Client.dll does not contain the expected animation section instructions")

    cave = (
        ORIGINAL_CLIENT_ENTRY
        + b"\x0F\x84" + _relative_32(CLIENT_CODE_CAVE_RVA + 12, CLIENT_ZERO_RVA)
        + b"\x83\x7C\x24\x04\x00"  # cmp dword ptr [esp+4], 0
        + b"\x0F\x8C" + _relative_32(CLIENT_CODE_CAVE_RVA + 23, CLIENT_ZERO_RVA)
        + b"\xE9" + _relative_32(CLIENT_CODE_CAVE_RVA + 28, CLIENT_CONTINUE_RVA)
    )
    if original[cave_offset:cave_offset + len(cave)] != bytes(len(cave)):
        raise PatchError("Client.dll animation patch area is not empty")

    section_cave = (
        b"\x8B\x3B"  # mov edi, dword ptr [ebx]
        + b"\x85\xFF"  # test edi, edi
        + b"\x7D\x04"  # jge use_frame
        + b"\x33\xFF"  # xor edi, edi
        + b"\x89\x3B"  # mov dword ptr [ebx], edi
        + b"\x8B\xC7\x99"  # mov eax, edi; cdq
        + b"\xE9" + _relative_32(CLIENT_SECTION_CODE_CAVE_RVA + 18, CLIENT_SECTION_CONTINUE_RVA)
    )
    if original[section_cave_offset:section_cave_offset + len(section_cave)] != bytes(len(section_cave)):
        raise PatchError("Client.dll animation section patch area is not empty")

    patched = bytearray(original)
    patched[entry_offset:entry_offset + len(ORIGINAL_CLIENT_ENTRY)] = (
        b"\xE9" + _relative_32(CLIENT_ENTRY_RVA + 5, CLIENT_CODE_CAVE_RVA) + b"\x90"
    )
    patched[section_entry_offset:section_entry_offset + len(ORIGINAL_CLIENT_SECTION_ENTRY)] = (
        b"\xE9" + _relative_32(CLIENT_SECTION_ENTRY_RVA + 5, CLIENT_SECTION_CODE_CAVE_RVA)
    )
    patched[cave_offset:cave_offset + len(cave)] = cave
    patched[section_cave_offset:section_cave_offset + len(section_cave)] = section_cave
    struct.pack_into("<I", patched, header + 8, PATCHED_CLIENT_TEXT_SIZE)
    return bytes(patched)


def _binary_path(root: Path, filename: str) -> Path:
    candidates = (
        root / "portal2" / "bin" / filename,
        root / "game" / "portal2" / "bin" / filename,
    )
    existing = tuple(path for path in candidates if path.is_file())
    if not existing:
        raise PatchError(f"852_0 {filename} is missing")
    if len(existing) != 1:
        raise PatchError(f"Found more than one 852_0 {filename}")
    return existing[0]


def server_path(root: Path) -> Path:
    return _binary_path(root, "Server.dll")


def client_path(root: Path) -> Path:
    return _binary_path(root, "Client.dll")


class VScriptScopeFixPatch:
    id = "852_0.vscript_scope_fix"
    display_name = "Mixup turret crash fix"
    description = "Prevent p2_lab_mixup turret crashes caused by failed VScript scopes and invalid animation frames."

    def check(self, context: PatchContext) -> bool:
        server_hash = sha256_file(server_path(context.root))
        client_hash = sha256_file(client_path(context.root))
        if server_hash not in {ORIGINAL_SERVER_SHA256, PATCHED_SERVER_SHA256}:
            raise PatchError(f"Refusing to patch unknown Server.dll ({server_hash})")
        if client_hash not in {ORIGINAL_CLIENT_SHA256, INTERMEDIATE_CLIENT_SHA256, PATCHED_CLIENT_SHA256}:
            raise PatchError(f"Refusing to patch unknown Client.dll ({client_hash})")
        return server_hash != PATCHED_SERVER_SHA256 or client_hash != PATCHED_CLIENT_SHA256

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        server = server_path(context.root)
        client = client_path(context.root)
        server_hash = sha256_file(server)
        client_hash = sha256_file(client)
        if server_hash not in {ORIGINAL_SERVER_SHA256, PATCHED_SERVER_SHA256}:
            raise PatchError("Server.dll changed before it could be patched")
        if client_hash not in {ORIGINAL_CLIENT_SHA256, INTERMEDIATE_CLIENT_SHA256, PATCHED_CLIENT_SHA256}:
            raise PatchError("Client.dll changed before it could be patched")

        progress(ProgressEvent(self.id, 0, 2, "Adding the VScript scope guard"))
        if server_hash == ORIGINAL_SERVER_SHA256:
            backup_file(server, "server.original.bak", context)
            patched_server = patch_server(server.read_bytes())
            if sha256(patched_server).hexdigest() != PATCHED_SERVER_SHA256:
                raise PatchError("Internal Server.dll verification failed")
            atomic_write(server, patched_server)

        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        progress(ProgressEvent(self.id, 1, 2, "Guarding invalid animation frames"))
        if client_hash != PATCHED_CLIENT_SHA256:
            if client_hash == ORIGINAL_CLIENT_SHA256:
                original_client = client.read_bytes()
                backup_file(client, "client.original.bak", context)
            else:
                backup = client.with_name("client.original.bak")
                if not backup.is_file() or sha256_file(backup) != ORIGINAL_CLIENT_SHA256:
                    raise PatchError("Cannot upgrade the earlier Client.dll fix without its verified backup")
                original_client = backup.read_bytes()
            patched_client = patch_client(original_client)
            if sha256(patched_client).hexdigest() != PATCHED_CLIENT_SHA256:
                raise PatchError("Internal Client.dll verification failed")
            atomic_write(client, patched_client)
        progress(ProgressEvent(self.id, 2, 2, "Installed the Mixup turret crash fix"))

    def verify(self, context: PatchContext) -> None:
        if sha256_file(server_path(context.root)) != PATCHED_SERVER_SHA256:
            raise PatchError("Mixup turret Server.dll fix failed verification")
        if sha256_file(client_path(context.root)) != PATCHED_CLIENT_SHA256:
            raise PatchError("Mixup turret Client.dll fix failed verification")


DEFINITION = PatchDefinition(VScriptScopeFixPatch())
