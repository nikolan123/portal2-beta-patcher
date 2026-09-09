"""Configure Hammer for build 852_2."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition
from patches.helpers.tier0 import patch_tier0


ORIGINAL_TIER0_SHA256 = "3bb521814cd9433da165650b1b68dc3cb678341f648bea27aa8f5ed953e788d3"
PATCHED_TIER0_SHA256 = "959f69b79e4e8b42c82549fcb5349c350d0f9f4c821dd4aec217ebbea463abdf"
OLD_TABLE_ADDRESS = 0x100573D8
EXPECTED_REFERENCE_OFFSETS = [0xEA02, 0xEA4D, 0xEAB3]


def patch_852_2_tier0(original: bytes) -> bytes:
    return patch_tier0(original, old_table_address=OLD_TABLE_ADDRESS,
                       expected_reference_offsets=EXPECTED_REFERENCE_OFFSETS,
                       expected_build="852_2")


def game_config(root: Path) -> bytes:
    base = str(root)
    text = f'''"Configs"
{{
    "Games"
    {{
        "Portal 2"
        {{
            "GameDir" "{base}\\portal2"
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
                "CordonTexture" "tools\\toolsskybox"
                "MaterialExcludeCount" "0"
                "GameExe" "{base}\\hl2.exe"
                "BSP" "{base}\\bin\\vbsp.exe"
                "Vis" "{base}\\bin\\vvis.exe"
                "Light" "{base}\\bin\\vrad.exe"
                "BSPDir" "{base}\\portal2\\maps"
                "GameData0" "{base}\\bin\\portal2.fgd"
            }}
        }}
    }}
    "SDKVersion" "3"
}}
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def hammer_launcher() -> bytes:
    text = '''@echo off
set "ROOT=%~dp0"
set "VPROJECT=%ROOT%portal2"
set "VCONTENT=%ROOT%content\\portal2"

cd /d "%ROOT%bin"
start "Portal 2 Hammer" hammer.exe -nop4 -threads 4 -game "%VPROJECT%"
'''
    return text.replace("\n", "\r\n").encode("ascii")


def patch_gameinfo(data: bytes) -> bytes:
    normalized = data.replace(b"\r\n", b"\n")
    platform = b"\t\t\tGame\t\t\t\t|gameinfo_path|..\\platform"
    if platform in normalized:
        return data
    anchor = b"\t\t\tGame\t\t\t\tportal2_tempcontent\n"
    if normalized.count(anchor) != 1:
        raise PatchError("portal2 GameInfo.txt does not contain the expected search paths")
    normalized = normalized.replace(anchor, anchor + platform + b"\n", 1)
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    return normalized.replace(b"\n", newline)


def repair_moved_tools(root: Path) -> None:
    """Rewrite 852_2.hammer's location-dependent configuration after a move."""
    root = root.expanduser().resolve()
    tier0 = root / "bin" / "tier0.dll"
    gameinfo = root / "portal2" / "GameInfo.txt"
    required_files = (
        root / "bin" / "hammer.exe",
        root / "bin" / "portal2.fgd",
        tier0,
        root / "platform" / "materials" / "Editor" / "wireframe.vmt",
        gameinfo,
    )
    if any(not path.is_file() for path in required_files):
        raise PatchError("This folder does not contain an installed 852_2 Hammer fix")
    if sha256_file(tier0) != PATCHED_TIER0_SHA256:
        raise PatchError("This folder does not contain 852_2.hammer's patched tier0.dll")
    if patch_gameinfo(gameinfo.read_bytes()) != gameinfo.read_bytes():
        raise PatchError("This folder does not contain 852_2.hammer's editor-material mount")

    (root / "content" / "portal2" / "mapsrc").mkdir(parents=True, exist_ok=True)
    atomic_write(root / "bin" / "GameConfig.txt", game_config(root))
    atomic_write(root / "Launch Hammer.cmd", hammer_launcher())


class Hammer8522Patch:
    id = "852_2.hammer"
    display_name = "Hammer"
    description = "Configure Hammer and patch thread limit"

    def _final_root(self, context: PatchContext) -> Path:
        return context.final_root or context.root

    def check(self, context: PatchContext) -> bool:
        try:
            self.verify(context)
        except Exception:
            return True
        return False

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        required = (context.root / "bin" / "hammer.exe", context.root / "bin" / "portal2.fgd",
                    context.root / "platform" / "materials" / "Editor" / "wireframe.vmt",
                    context.root / "portal2" / "GameInfo.txt")
        if any(not path.is_file() for path in required):
            raise PatchError("The extracted 852_2 build does not contain the required Hammer files")

        progress(ProgressEvent(self.id, 0, 3, "Mounting Hammer editor materials"))
        gameinfo = context.root / "portal2" / "GameInfo.txt"
        original_gameinfo = gameinfo.read_bytes()
        patched_gameinfo = patch_gameinfo(original_gameinfo)
        if patched_gameinfo != original_gameinfo:
            backup_file(gameinfo, "GameInfo.original.bak", context)
            atomic_write(gameinfo, patched_gameinfo)

        progress(ProgressEvent(self.id, 1, 3, "Increasing the tier0 thread-ID limit"))
        tier0 = context.root / "bin" / "tier0.dll"
        current_hash = sha256_file(tier0)
        if current_hash == ORIGINAL_TIER0_SHA256:
            original = tier0.read_bytes()
            backup_file(tier0, "tier0.original.bak", context)
            patched = patch_852_2_tier0(original)
            if sha256(patched).hexdigest() != PATCHED_TIER0_SHA256:
                raise PatchError("Internal 852_2 tier0.dll verification failed")
            atomic_write(tier0, patched)
        elif current_hash != PATCHED_TIER0_SHA256:
            raise PatchError(f"Refusing to patch unknown 852_2 tier0.dll ({current_hash})")

        progress(ProgressEvent(self.id, 2, 3, "Writing the Portal 2 Hammer configuration"))
        (context.root / "content" / "portal2" / "mapsrc").mkdir(parents=True, exist_ok=True)
        config = context.root / "bin" / "GameConfig.txt"
        expected_config = game_config(self._final_root(context))
        if config.exists() and config.read_bytes() != expected_config:
            backup_file(config, "GameConfig.original.bak", context)
        atomic_write(config, expected_config)
        atomic_write(context.root / "Launch Hammer.cmd", hammer_launcher())
        progress(ProgressEvent(self.id, 3, 3, "Hammer is configured"))

    def verify(self, context: PatchContext) -> None:
        final_root = self._final_root(context)
        tier0 = context.root / "bin" / "tier0.dll"
        if not tier0.is_file() or sha256_file(tier0) != PATCHED_TIER0_SHA256:
            raise PatchError("852_2 tier0.dll thread fix is missing")
        config = context.root / "bin" / "GameConfig.txt"
        if not config.is_file() or config.read_bytes() != game_config(final_root):
            raise PatchError("852_2 Hammer configuration is missing or incorrect")
        launcher = context.root / "Launch Hammer.cmd"
        if not launcher.is_file() or launcher.read_bytes() != hammer_launcher():
            raise PatchError("852_2 Hammer launcher is missing or incorrect")
        gameinfo = context.root / "portal2" / "GameInfo.txt"
        if not gameinfo.is_file() or patch_gameinfo(gameinfo.read_bytes()) != gameinfo.read_bytes():
            raise PatchError("852_2 editor materials are not mounted")
        if not (context.root / "content" / "portal2" / "mapsrc").is_dir():
            raise PatchError("852_2 mapsource folder is missing")


DEFINITION = PatchDefinition(Hammer8522Patch(), after=frozenset({"launchers"}))
