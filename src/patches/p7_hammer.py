"""Patch 7: Repair and configure the Hammer and HLMV tools in build 852_0."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file


ORIGINAL_TIER0_SHA256 = "ef0da9d93ba7cac265db82ebff189c6568a121a366ce28d256772d4ab9579cf1"
PATCHED_TIER0_SHA256 = "a5fe7685d7b8fc68d1ee320d0d29da6d25cf3bb1b706d127ecd4fc56c0db3e81"
OLD_TABLE_ADDRESS = 0x10041AA0
EXPECTED_REFERENCE_OFFSETS = [0xB0A2, 0xB0ED, 0xB153]
ALLOCATOR_OLD = bytes.fromhex("83 FE 20 7C EE")
ALLOCATOR_NEW = bytes.fromhex("83 FE 80 72 EE")
JUNCTION_NAMES = ("bin", "hl2", "platform", "portal", "portal2", "portal2_tempcontent")
EDITOR_FILE_COUNT = 205


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def p16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def p32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def align(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def patch_tier0(original: bytes) -> bytes:
    data = bytearray(original)
    pe = u32(data, 0x3C)
    if data[pe : pe + 4] != b"PE\0\0":
        raise PatchError("tier0.dll has an invalid PE signature")

    coff = pe + 4
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    if u16(data, optional) != 0x10B or section_count != 5:
        raise PatchError("tier0.dll is not the expected 32-bit 852_0 image")

    image_base = u32(data, optional + 28)
    section_alignment = u32(data, optional + 32)
    file_alignment = u32(data, optional + 36)
    size_of_headers = u32(data, optional + 60)
    section_table = optional + optional_size
    new_header = section_table + section_count * 40
    if new_header + 40 > size_of_headers:
        raise PatchError("tier0.dll has no room for the thread-table section")

    last_virtual_end = 0
    last_raw_end = 0
    for index in range(section_count):
        header = section_table + index * 40
        virtual_size = u32(data, header + 8)
        virtual_address = u32(data, header + 12)
        raw_size = u32(data, header + 16)
        raw_pointer = u32(data, header + 20)
        last_virtual_end = max(last_virtual_end, virtual_address + max(virtual_size, raw_size))
        last_raw_end = max(last_raw_end, raw_pointer + raw_size)
    if last_raw_end != len(data):
        raise PatchError("tier0.dll has an unexpected section layout")

    allocator_offset = data.find(ALLOCATOR_OLD)
    if allocator_offset < 0 or data.find(ALLOCATOR_OLD, allocator_offset + 1) >= 0:
        raise PatchError("tier0.dll allocator signature was not found exactly once")
    data[allocator_offset : allocator_offset + len(ALLOCATOR_NEW)] = ALLOCATOR_NEW

    old_address = struct.pack("<I", OLD_TABLE_ADDRESS)
    references = []
    offset = data.find(old_address)
    while offset >= 0:
        references.append(offset)
        offset = data.find(old_address, offset + 1)
    if references != EXPECTED_REFERENCE_OFFSETS:
        raise PatchError("tier0.dll has unexpected thread-table references")

    table_size = 0x80
    new_virtual_address = align(last_virtual_end, section_alignment)
    new_raw_pointer = align(last_raw_end, file_alignment)
    new_raw_size = align(table_size, file_alignment)
    new_absolute_address = image_base + new_virtual_address
    for reference in references:
        p32(data, reference, new_absolute_address)

    p16(data, coff + 2, section_count + 1)
    p32(data, optional + 8, u32(data, optional + 8) + new_raw_size)
    p32(data, optional + 56, align(new_virtual_address + table_size, section_alignment))
    data[new_header : new_header + 40] = b"\0" * 40
    data[new_header : new_header + 4] = b".tid"
    p32(data, new_header + 8, table_size)
    p32(data, new_header + 12, new_virtual_address)
    p32(data, new_header + 16, new_raw_size)
    p32(data, new_header + 20, new_raw_pointer)
    p32(data, new_header + 36, 0xC0000040)
    if len(data) < new_raw_pointer:
        data.extend(b"\0" * (new_raw_pointer - len(data)))
    data.extend(b"\0" * new_raw_size)
    return bytes(data)


def game_config(root: Path) -> bytes:
    base = str(root)
    text = f'''"Configs"
{{
    "Games"
    {{
        "Portal 2"
        {{
            "GameDir" "{base}\\game\\portal2"
            "Hammer"
            {{
                "TextureFormat" "5"
                "MapFormat" "4"
                "DefaultTextureScale" "0.250000"
                "DefaultLightmapScale" "16"
                "DefaultSolidEntity" "func_detail"
                "DefaultPointEntity" "info_player_start"
                "GameExeDir" "{base}"
                "MapDir" "{base}\\content\\portal2\\mapsrc"
                "GameExe" "{base}\\hl2.exe"
                "BSP" "{base}\\bin\\vbsp.exe"
                "Vis" "{base}\\bin\\vvis.exe"
                "Light" "{base}\\bin\\vrad.exe"
                "BSPDir" "{base}\\game\\portal2\\maps"
                "PrefabDir" "{base}\\bin\\Prefabs"
                "GameData0" "{base}\\bin\\portal2.fgd"
                "CordonTexture" "tools\\toolsskybox"
                "MaterialExcludeCount" "0"
            }}
        }}
    }}
    "SDKVersion" "3"
}}
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def hammer_launcher(root: Path) -> bytes:
    base = str(root)
    text = f'''@echo off
setlocal
set "VPROJECT={base}\\game\\portal2"
set "VCONTENT={base}\\content\\portal2"
set "GAMEROOT={base}\\game"
set "CONTENTROOT={base}\\content"

cd /d "{base}\\bin"
start "Portal 2 Hammer" hammer.exe -nop4 -threads 4 -game "%VPROJECT%"
endlocal
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def hlmv_launcher(root: Path) -> bytes:
    base = str(root)
    text = f'''@echo off
setlocal
set "VPROJECT={base}\\game\\portal2"

cd /d "{base}\\bin"
start "Half-Life Model Viewer" hlmv.exe -nop4 -game "%VPROJECT%" %*
endlocal
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def normalized_path(path: str | Path) -> str:
    value = os.path.normpath(str(path))
    for prefix in ("\\\\?\\", "\\??\\"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return os.path.normcase(value)


def ensure_junction(link: Path, target: Path) -> None:
    if os.path.lexists(link):
        if not link.is_junction():
            raise PatchError(f"Refusing to replace non-junction path: {link}")
        if normalized_path(os.readlink(link)) != normalized_path(target):
            raise PatchError(f"Junction points to an unexpected target: {link}")
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(target)]
    result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise PatchError(f"Could not create junction {link.name}: {detail}")


def repair_moved_tools(root: Path) -> None:
    """Rewrite p7's location-dependent files after its output folder is moved."""
    root = root.expanduser().resolve()
    required_files = (
        root / "bin" / "hammer.exe",
        root / "bin" / "hlmv.exe",
        root / "bin" / "tier0.dll",
        root / "platform" / "materials" / "Editor" / "wireframe.vmt",
    )
    if any(not path.is_file() for path in required_files):
        raise PatchError("This folder does not contain an installed Hammer and HLMV fix")
    if sha256((root / "bin" / "tier0.dll").read_bytes()) != PATCHED_TIER0_SHA256:
        raise PatchError("This folder does not contain p7's patched tier0.dll")

    links = [(root / "game" / name, root / name) for name in JUNCTION_NAMES]
    for link, _target in links:
        if os.path.lexists(link) and not link.is_junction():
            raise PatchError(f"Refusing to replace non-junction path: {link}")

    for link, target in links:
        if link.is_junction() and normalized_path(os.readlink(link)) != normalized_path(target):
            os.rmdir(link)
        ensure_junction(link, target)

    atomic_write(root / "bin" / "GameConfig.txt", game_config(root))
    atomic_write(root / "Launch Hammer.cmd", hammer_launcher(root))
    atomic_write(root / "Launch HLMV.cmd", hlmv_launcher(root))


class HammerPatch:
    id = "p7"
    display_name = "Hammer and HLMV tools"
    description = "Repair Hammer and HLMV using retail Portal 2 editor materials, tier0 thread fix, correct layout, and launchers."

    def _final_root(self, context: PatchContext) -> Path:
        return context.final_root or context.root

    def check(self, context: PatchContext) -> bool:
        try:
            self.verify(context)
        except Exception:
            return True
        return False

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.portal2_source is None:
            raise PatchError("A retail Portal 2 installation is required for the Hammer and HLMV fix")
        final_root = self._final_root(context)
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")

        mapsrc = context.root / "content" / "portal2" / "mapsrc"
        mapsrc.mkdir(parents=True, exist_ok=True)
        (context.root / "game").mkdir(parents=True, exist_ok=True)
        for name in JUNCTION_NAMES:
            ensure_junction(context.root / "game" / name, final_root / name)

        config_path = context.root / "bin" / "GameConfig.txt"
        if config_path.exists():
            backup_file(config_path, "GameConfig.original.bak", context)
        atomic_write(config_path, game_config(final_root))

        source = context.portal2_source / "platform" / "materials" / "Editor"
        files = sorted(path for path in source.rglob("*") if path.is_file())
        if len(files) != EDITOR_FILE_COUNT:
            raise PatchError(f"Expected {EDITOR_FILE_COUNT} Hammer editor materials in retail Portal 2, found {len(files)}")
        destination = context.root / "platform" / "materials" / "Editor"
        for index, path in enumerate(files, start=1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if index == 1 or index == len(files) or index % 25 == 0:
                progress(ProgressEvent("p7", index, len(files), f"Hammer material: {path.name}"))

        tier0 = context.root / "bin" / "tier0.dll"
        current = tier0.read_bytes()
        current_hash = sha256(current)
        if current_hash == ORIGINAL_TIER0_SHA256:
            backup = tier0.with_name("tier0.original.bak")
            if backup.exists() and sha256(backup.read_bytes()) != ORIGINAL_TIER0_SHA256:
                raise PatchError(f"Refusing to replace unexpected backup: {backup}")
            if not backup.exists():
                shutil.copy2(tier0, backup)
                context.report.backups.append(str(backup.relative_to(context.root)))
            patched = patch_tier0(current)
            if sha256(patched) != PATCHED_TIER0_SHA256:
                raise PatchError("Internal tier0.dll verification failed")
            atomic_write(tier0, patched)
        elif current_hash != PATCHED_TIER0_SHA256:
            raise PatchError(f"Refusing to patch unknown tier0.dll ({current_hash})")

        atomic_write(context.root / "Launch Hammer.cmd", hammer_launcher(final_root))
        atomic_write(context.root / "Launch HLMV.cmd", hlmv_launcher(final_root))

    def verify(self, context: PatchContext) -> None:
        final_root = self._final_root(context)
        if (context.root / "bin" / "GameConfig.txt").read_bytes() != game_config(final_root):
            raise PatchError("Hammer GameConfig.txt is not configured")
        editor = context.root / "platform" / "materials" / "Editor"
        if len([path for path in editor.rglob("*") if path.is_file()]) != EDITOR_FILE_COUNT:
            raise PatchError("Hammer editor materials are incomplete")
        tier0 = context.root / "bin" / "tier0.dll"
        if sha256(tier0.read_bytes()) != PATCHED_TIER0_SHA256:
            raise PatchError("tier0.dll does not contain the Hammer thread fix")
        if (context.root / "Launch Hammer.cmd").read_bytes() != hammer_launcher(final_root):
            raise PatchError("Hammer launcher is missing or incorrect")
        if (context.root / "Launch HLMV.cmd").read_bytes() != hlmv_launcher(final_root):
            raise PatchError("HLMV launcher is missing or incorrect")
        for name in JUNCTION_NAMES:
            link = context.root / "game" / name
            if not link.is_junction() or normalized_path(os.readlink(link)) != normalized_path(final_root / name):
                raise PatchError(f"Hammer junction is missing or incorrect: game\\{name}")
