from __future__ import annotations

from pathlib import Path
import re
import sys


class SteamDetectionError(RuntimeError):
    pass


TOKEN_RE = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')


def parse_vdf(text: str) -> dict[str, object]:
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text):
        if match.group(2):
            tokens.append(match.group(2))
        else:
            value = match.group(1).replace(r"\\", "\\").replace(r'\"', '"')
            tokens.append(value)
    cursor = 0

    def parse_object(expect_close: bool) -> dict[str, object]:
        nonlocal cursor
        result: dict[str, object] = {}
        while cursor < len(tokens):
            if tokens[cursor] == "}":
                if not expect_close:
                    raise SteamDetectionError("Unexpected closing brace in VDF")
                cursor += 1
                return result
            key = tokens[cursor]
            cursor += 1
            if cursor >= len(tokens):
                raise SteamDetectionError("VDF key has no value")
            if tokens[cursor] == "{":
                cursor += 1
                value: object = parse_object(True)
            else:
                value = tokens[cursor]
                cursor += 1
            result[key] = value
        if expect_close:
            raise SteamDetectionError("Unclosed VDF object")
        return result

    return parse_object(False)


def steam_roots() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, subkey in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        for value_name in ("SteamPath", "InstallPath"):
                            try:
                                candidates.append(Path(winreg.QueryValueEx(key, value_name)[0]))
                            except FileNotFoundError:
                                pass
                except FileNotFoundError:
                    pass
        except OSError:
            pass
    candidates.extend((Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen and candidate.is_dir():
            seen.add(key)
            unique.append(candidate)
    return unique


def steam_libraries() -> list[Path]:
    libraries: list[Path] = []
    for root in steam_roots():
        libraries.append(root)
        config = root / "steamapps" / "libraryfolders.vdf"
        if not config.is_file():
            continue
        try:
            parsed = parse_vdf(config.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SteamDetectionError):
            continue
        folder_data = parsed.get("libraryfolders", parsed)
        if isinstance(folder_data, dict):
            for key, value in folder_data.items():
                if not str(key).isdigit():
                    continue
                path_value = value.get("path") if isinstance(value, dict) else value
                if isinstance(path_value, str):
                    libraries.append(Path(path_value))
    unique: list[Path] = []
    seen: set[str] = set()
    for library in libraries:
        key = str(library).casefold()
        if key not in seen and library.is_dir():
            seen.add(key)
            unique.append(library)
    return unique


def validate_hl2(path: Path) -> Path:
    path = path.expanduser().resolve()
    hl2 = path / "hl2"
    if not hl2.is_dir():
        raise SteamDetectionError("The selected folder has no hl2 directory")
    indexes = list(hl2.glob("*_dir.vpk"))
    if not indexes:
        raise SteamDetectionError("The selected Half-Life 2 folder has no VPK indexes")
    return path


def detect_half_life_2() -> Path | None:
    for library in steam_libraries():
        manifest = library / "steamapps" / "appmanifest_220.acf"
        game = library / "steamapps" / "common" / "Half-Life 2"
        if manifest.is_file() and game.is_dir():
            try:
                return validate_hl2(game)
            except SteamDetectionError:
                continue
    return None


def validate_portal_2(path: Path) -> Path:
    path = path.expanduser().resolve()
    editor = path / "platform" / "materials" / "Editor"
    required = ("wireframe.vmt", "flat.vmt", "logic_coop_manager.vmt")
    if not (path / "portal2").is_dir() or not editor.is_dir():
        raise SteamDetectionError("The selected folder is not a Portal 2 installation")
    if any(not (editor / name).is_file() for name in required):
        raise SteamDetectionError("The selected Portal 2 installation has incomplete Hammer resources")
    return path


def detect_portal_2() -> Path | None:
    for library in steam_libraries():
        manifest = library / "steamapps" / "appmanifest_620.acf"
        game = library / "steamapps" / "common" / "Portal 2"
        if manifest.is_file() and game.is_dir():
            try:
                return validate_portal_2(game)
            except SteamDetectionError:
                continue
    return None


def relevant_hl2_vpks(hl2_root: Path) -> list[Path]:
    folder = validate_hl2(hl2_root) / "hl2"
    required = (
        "hl2_misc_dir.vpk",
        "hl2_textures_dir.vpk",
        "hl2_sound_misc_dir.vpk",
    )
    found = [folder / name for name in required if (folder / name).is_file()]
    if not (folder / "hl2_misc_dir.vpk").is_file() and (folder / "hl2_pak_dir.vpk").is_file():
        found.insert(0, folder / "hl2_pak_dir.vpk")
    missing = [name for name in required[1:] if not (folder / name).is_file()]
    if not found or missing:
        detail = ", ".join(missing or required)
        raise SteamDetectionError(f"Required base Half-Life 2 VPK archives are missing: {detail}")
    return found
