"""Repair and configure the Hammer and HLMV tools in build 852_0."""
from __future__ import annotations

from pathlib import Path
import shutil

from patches.definitions import PatchDefinition
from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file
from patches.helpers.tier0 import patch_tier0 as _patch_tier0, sha256
from patches.helpers.retail_assets import copy_selected_vpk_assets
from vpk import VPKArchive, VPKError


ORIGINAL_TIER0_SHA256 = "ef0da9d93ba7cac265db82ebff189c6568a121a366ce28d256772d4ab9579cf1"
PATCHED_TIER0_SHA256 = "a5fe7685d7b8fc68d1ee320d0d29da6d25cf3bb1b706d127ecd4fc56c0db3e81"
OLD_TABLE_ADDRESS = 0x10041AA0
EXPECTED_REFERENCE_OFFSETS = [0xB0A2, 0xB0ED, 0xB153]
RUNTIME_DIRECTORIES = ("bin", "hl2", "platform", "portal", "portal2", "portal2_tempcontent")
RUNTIME_FILES = ("hl2.exe", "hl2.wrap.exe", "steam_appid.txt")
EDITOR_REQUIRED_FILES = ("wireframe.vmt", "flat.vmt", "logic_coop_manager.vmt")
TOOL_CONTENT_FOLDERS = ("portal2", "portal2_tempcontent", "platform", "portal", "hl2")
TOOL_REQUIRED_FILES = ("materials/tools/toolsblocklight.vmt", "materials/tools/toolsblocklight.vtf")


def retail_tool_materials(source: Path):
    index = source / "portal2" / "pak01_dir.vpk"
    try:
        archive = VPKArchive(index)
    except (OSError, VPKError) as error:
        raise PatchError(f"Cannot read retail Portal 2 tool materials: {error}") from error
    entries = [entry for entry in archive.entries
               if entry.path.casefold().startswith("materials/tools/")
               and Path(entry.path).suffix.casefold() in {".vmt", ".vtf"}]
    if not set(TOOL_REQUIRED_FILES) <= {entry.path.casefold() for entry in entries}:
        raise PatchError("Retail Portal 2 is missing the blocklight material or texture")
    return archive, entries


def has_tool_material(runtime: Path, relative: str) -> bool:
    return any((runtime / folder / relative).is_file() for folder in TOOL_CONTENT_FOLDERS)


def patch_tier0(original: bytes) -> bytes:
    return _patch_tier0(original, old_table_address=OLD_TABLE_ADDRESS, expected_reference_offsets=EXPECTED_REFERENCE_OFFSETS, expected_build="852_0")


def game_config(root: Path) -> bytes:
    base = str(root)
    game = f"{base}\\game"
    text = f'''"Configs"
{{
    "Games"
    {{
        "Portal 2"
        {{
            "GameDir" "{game}\\portal2"
            "Hammer"
            {{
                "TextureFormat" "5"
                "MapFormat" "4"
                "DefaultTextureScale" "0.250000"
                "DefaultLightmapScale" "16"
                "DefaultSolidEntity" "func_detail"
                "DefaultPointEntity" "info_player_start"
                "GameExeDir" "{game}"
                "MapDir" "{base}\\content\\portal2\\mapsrc"
                "GameExe" "{game}\\hl2.exe"
                "BSP" "{game}\\bin\\vbsp.exe"
                "Vis" "{game}\\bin\\vvis.exe"
                "Light" "{game}\\bin\\vrad.exe"
                "BSPDir" "{game}\\portal2\\maps"
                "PrefabDir" "{game}\\bin\\Prefabs"
                "GameData0" "{game}\\bin\\portal2.fgd"
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
    text = '''@echo off
set "ROOT=%~dp0"
set "VPROJECT=%ROOT%game\\portal2"
set "VCONTENT=%ROOT%content\\portal2"
set "GAMEROOT=%ROOT%game"
set "CONTENTROOT=%ROOT%content"

cd /d "%ROOT%game\\bin"
start "Portal 2 Hammer" hammer.exe -nop4 -threads 4 -game "%VPROJECT%"
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def hlmv_launcher(root: Path) -> bytes:
    text = '''@echo off
set "ROOT=%~dp0"
set "VPROJECT=%ROOT%game\\portal2"

cd /d "%ROOT%game\\bin"
start "Half-Life Model Viewer" hlmv.exe -nop4 -game "%VPROJECT%" %*
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def move_runtime_into_game(root: Path) -> None:
    game = root / "game"
    # Full TF2 content may have been installed before adding the Hammer layout.
    directories = RUNTIME_DIRECTORIES + (("tf",) if (root / "tf").exists() or (game / "tf").exists() else ())
    # Existing builds may already have this layout without the Hammer fixes.
    if (game / "portal2").is_dir():
        for name in directories:
            if not (game / name).is_dir():
                raise PatchError(f"Hammer runtime folder is missing: game\\{name}")
        for name in (*directories, *RUNTIME_FILES):
            if (root / name).exists():
                raise PatchError(f"Hammer runtime was left duplicated outside game: {name}")
        return

    # Check every source and destination before moving anything.
    for name in directories:
        source = root / name
        destination = game / name
        if not source.is_dir():
            raise PatchError(f"Cannot create the Hammer layout because {name} is missing")
        if destination.exists():
            raise PatchError(f"Cannot create the Hammer layout because game\\{name} already exists")
    for name in RUNTIME_FILES:
        source = root / name
        if not source.exists():
            continue
        destination = game / name
        if destination.exists():
            raise PatchError(f"Cannot create the Hammer layout because game\\{name} already exists")
    game.mkdir(parents=True, exist_ok=True)
    for name in (*directories, *RUNTIME_FILES):
        source = root / name
        if source.exists():
            source.replace(game / name)


def repair_moved_tools(root: Path) -> None:
    """Rewrite 852_0.hammer's location-dependent files after its output folder is moved."""
    root = root.expanduser().resolve()
    required_files = (
        root / "game" / "bin" / "hammer.exe",
        root / "game" / "bin" / "hlmv.exe",
        root / "game" / "bin" / "tier0.dll",
        root / "game" / "platform" / "materials" / "Editor" / "wireframe.vmt",
    )
    if any(not path.is_file() for path in required_files):
        raise PatchError("This folder does not contain an installed Hammer and HLMV fix")
    if sha256((root / "game" / "bin" / "tier0.dll").read_bytes()) != PATCHED_TIER0_SHA256:
        raise PatchError("This folder does not contain 852_0.hammer's patched tier0.dll")

    atomic_write(root / "game" / "bin" / "GameConfig.txt", game_config(root))
    atomic_write(root / "Launch Hammer.cmd", hammer_launcher(root))
    atomic_write(root / "Launch HLMV.cmd", hlmv_launcher(root))


class HammerPatch:
    id = "852_0.hammer"
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

        tool_archive, tool_entries = retail_tool_materials(context.portal2_source)
        move_runtime_into_game(context.root)
        mapsrc = context.root / "content" / "portal2" / "mapsrc"
        mapsrc.mkdir(parents=True, exist_ok=True)

        config_path = context.root / "game" / "bin" / "GameConfig.txt"
        if config_path.exists():
            backup_file(config_path, "GameConfig.original.bak", context)

        source = context.portal2_source / "platform" / "materials" / "Editor"
        files = sorted(path for path in source.rglob("*") if path.is_file())
        destination = context.root / "game" / "platform" / "materials" / "Editor"
        for index, path in enumerate(files, start=1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if index == 1 or index == len(files) or index % 25 == 0:
                progress(ProgressEvent("852_0.hammer", index, len(files), f"Hammer material: {path.name}"))

        runtime = context.root / "game"
        missing_tools = [(tool_archive.directory_file, tool_archive, entry) for entry in tool_entries
                         if not has_tool_material(runtime, entry.path)]
        copy_selected_vpk_assets(missing_tools, runtime / "portal2", context.cancel_event, progress, self.id)

        tier0 = context.root / "game" / "bin" / "tier0.dll"
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

        atomic_write(config_path, game_config(final_root))
        atomic_write(context.root / "Launch Hammer.cmd", hammer_launcher(final_root))
        atomic_write(context.root / "Launch HLMV.cmd", hlmv_launcher(final_root))

    def verify(self, context: PatchContext) -> None:
        final_root = self._final_root(context)
        if (context.root / "game" / "bin" / "GameConfig.txt").read_bytes() != game_config(final_root):
            raise PatchError("Hammer GameConfig.txt is not configured")
        editor = context.root / "game" / "platform" / "materials" / "Editor"
        if any(not (editor / name).is_file() for name in EDITOR_REQUIRED_FILES):
            raise PatchError("Hammer editor materials are incomplete")
        required_tools = TOOL_REQUIRED_FILES
        if context.portal2_source is not None:
            _, entries = retail_tool_materials(context.portal2_source)
            required_tools = tuple(entry.path for entry in entries)
        missing_tools = [path for path in required_tools if not has_tool_material(context.root / "game", path)]
        if missing_tools:
            raise PatchError("Hammer tool materials are missing: " + ", ".join(missing_tools))
        tier0 = context.root / "game" / "bin" / "tier0.dll"
        if sha256(tier0.read_bytes()) != PATCHED_TIER0_SHA256:
            raise PatchError("tier0.dll does not contain the Hammer thread fix")
        if (context.root / "Launch Hammer.cmd").read_bytes() != hammer_launcher(final_root):
            raise PatchError("Hammer launcher is missing or incorrect")
        if (context.root / "Launch HLMV.cmd").read_bytes() != hlmv_launcher(final_root):
            raise PatchError("HLMV launcher is missing or incorrect")
        for name in RUNTIME_DIRECTORIES:
            if not (context.root / "game" / name).is_dir():
                raise PatchError(f"Hammer runtime folder is missing: game\\{name}")
            if (context.root / name).exists():
                raise PatchError(f"Hammer runtime folder was left duplicated: {name}")



DEFINITION = PatchDefinition(HammerPatch(), after=frozenset({"launchers"}), requirements=frozenset({"portal2"}))
