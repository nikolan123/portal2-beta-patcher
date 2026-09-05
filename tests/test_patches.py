from hashlib import sha256
import re
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event

from models import BuildReport, PatchContext
from patches import (
    PATCHES,
    PATCH_COMPATIBILITY,
    compatible_patch_ids,
    normalize_patch_ids,
)
from patches.base import sha256_file
from patches.p1_hl2_assets import ASSET_MARKER, HL2_ASSET_ALLOWLIST, copy_selected_loose_assets
from patches.p2_search_paths import SearchPathsPatch
from patches.p3_sound_manifest import HL2_SOUND_SCRIPTS
from patches.p5_thread_fix import (
    ARCHIVE_SHA256 as THREAD_FIX_ARCHIVE_SHA256,
    DOWNLOAD_URL,
    FILES,
    destination_path,
)
from patches.p6_launchers import LAUNCHER, LaunchersPatch
from patches.p7_hammer import (
    PATCHED_TIER0_SHA256,
    RUNTIME_DIRECTORIES,
    game_config,
    hammer_launcher,
    hlmv_launcher,
    move_runtime_into_game,
)
from patches.p8_prerelease_assets import (
    ASSET_HASHES,
    ARCHIVE_SHA256 as ASSET_ARCHIVE_SHA256,
    PrereleaseAssetsPatch,
    archive_path,
)
from patches.p9_multicore import MULTICORE_CONFIG, MulticorePatch
from patches.p10_goldberg import ARCHIVE_SHA256 as GOLDBERG_ARCHIVE_SHA256, GoldbergPatch
from patches.p11_legacy_paint import ORIGINAL_BYTES, PATCHED_BYTES, PATCH_OFFSET, patch_engine
from patches.p12_july_2010_assets import July2010AssetsPatch
from patches.p13_july_2009_assets import July2009AssetsPatch, overlay_tree
from patches.p14_march_assets import ARCHIVE_SHA256 as MARCH_ASSET_ARCHIVE_SHA256, MarchAssetsPatch, read_bundle
from patches.p15_tier0_thread_limit_852_1 import (
    EXPECTED_REFERENCE_OFFSETS as REFERENCE_OFFSETS_852_1,
    ORIGINAL_TIER0_SHA256 as ORIGINAL_852_1_TIER0_SHA256,
    PATCHED_TIER0_SHA256 as PATCHED_852_1_TIER0_SHA256,
    Tier0ThreadLimit8521Patch,
    patch_852_1_tier0,
)
from patches.p16_hl2_launcher import (
    LAUNCHER_SHA256,
    Hl2LauncherPatch,
    launcher_path,
)
from patches.p17_tier0_thread_limit_841_0 import (
    EXPECTED_REFERENCE_OFFSETS as REFERENCE_OFFSETS_841_0,
    ORIGINAL_TIER0_SHA256 as ORIGINAL_841_0_TIER0_SHA256,
    PATCHED_TIER0_SHA256 as PATCHED_841_0_TIER0_SHA256,
    Tier0ThreadLimit8410Patch,
    patch_841_0_tier0,
)


def test_patch_registry_is_explicitly_numbered():
    assert [patch.id for patch in PATCHES] == ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10", "p11", "p12", "p13", "p14", "p15", "p16", "p17"]
    assert all(patch.description for patch in PATCHES)
    assert set(PATCH_COMPATIBILITY) == {"generic", (841, 0, 0x83CED978), (852, 0), (852, 1)}
    assert PATCH_COMPATIBILITY["generic"].required == {"p6"}
    assert PATCH_COMPATIBILITY[(852, 0)].required == {"p2", "p6"}
    assert PATCH_COMPATIBILITY[(852, 1)].required == {"p6"}
    assert "p12" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "p13" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "p14" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "p15" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].required == {"p6"}
    assert "p16" in PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].optional
    assert "p17" in PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].optional


def test_patch_dependencies_and_required_launcher():
    assert normalize_patch_ids(()) == ("p2", "p6")
    assert normalize_patch_ids(("p3",)) == ("p1", "p2", "p3", "p6")
    assert "p9" not in normalize_patch_ids(("p9",), "852_0")
    assert normalize_patch_ids(("p1", "p4", "p5", "p9"), "generic", depot_id=852, depot_version=2) == ("p5", "p6", "p9")
    assert normalize_patch_ids(("p10",), "852_0") == ("p2", "p6", "p10")
    assert normalize_patch_ids(("p5",), "generic", runnable=False, depot_id=843, depot_version=1) == ("p5",)
    assert normalize_patch_ids(("p11",), "generic", depot_id=852, depot_version=1) == ("p6", "p11")
    assert normalize_patch_ids(("p11",), "generic", depot_id=852, depot_version=2) == ("p6",)
    assert normalize_patch_ids(("p11",), "generic", depot_id=841, depot_version=1) == ("p6",)
    assert normalize_patch_ids(("p12",), "generic", depot_id=852, depot_version=1) == ("p6", "p12")
    assert normalize_patch_ids(("p12",), "generic", depot_id=852, depot_version=2) == ("p6",)
    assert normalize_patch_ids(("p13",), "generic", depot_id=852, depot_version=1) == ("p6", "p13")
    assert normalize_patch_ids(("p13",), "generic", depot_id=852, depot_version=2) == ("p6",)
    assert normalize_patch_ids(("p14",), "generic", depot_id=852, depot_version=1) == ("p6", "p14")
    assert normalize_patch_ids(("p14",), "generic", depot_id=852, depot_version=2) == ("p6",)
    assert normalize_patch_ids(("p15",), "generic", depot_id=852, depot_version=1) == ("p6", "p15")
    assert normalize_patch_ids(("p15",), "generic", depot_id=852, depot_version=2) == ("p6",)
    assert compatible_patch_ids("852_0") == ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p10")
    assert compatible_patch_ids("generic", 852, 1) == ("p5", "p6", "p10", "p11", "p12", "p13", "p14", "p15")
    assert compatible_patch_ids("generic", 852, 2) == ("p5", "p6", "p9", "p10")
    assert normalize_patch_ids((), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ()
    assert normalize_patch_ids((), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("p6",)
    assert normalize_patch_ids(("p16",), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("p16",)
    assert normalize_patch_ids(("p16",), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("p6", "p16")
    assert normalize_patch_ids(("p17",), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("p17",)
    assert normalize_patch_ids(("p17",), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("p6", "p17")


def test_841_0_pre_reset_launcher_patch_installs_the_binary(tmp_path):
    assert sha256_file(launcher_path()) == LAUNCHER_SHA256
    patch = Hl2LauncherPatch()
    context = PatchContext(tmp_path, None, BuildReport(), Event(), mode="generic")
    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert sha256_file(tmp_path / "hl2.exe") == LAUNCHER_SHA256


def test_build_specific_tier0_patches_use_distinct_binaries_and_offsets():
    assert ORIGINAL_841_0_TIER0_SHA256 != ORIGINAL_852_1_TIER0_SHA256
    assert PATCHED_841_0_TIER0_SHA256 != PATCHED_852_1_TIER0_SHA256
    assert REFERENCE_OFFSETS_841_0 != REFERENCE_OFFSETS_852_1


def test_841_0_pre_reset_tier0_patch_matches_the_known_dll_when_available():
    source = Path(r"C:\Users\Niko\Downloads\841_0_extracted\bin\tier0.dll")
    if not source.is_file() or sha256_file(source) != ORIGINAL_841_0_TIER0_SHA256:
        return
    patched = patch_841_0_tier0(source.read_bytes())
    assert sha256(patched).hexdigest() == PATCHED_841_0_TIER0_SHA256
    assert Tier0ThreadLimit8410Patch.id == "p17"


def test_legacy_paint_patch_changes_only_the_missing_key_default():
    original = bytearray(PATCH_OFFSET + len(ORIGINAL_BYTES))
    original[PATCH_OFFSET:] = ORIGINAL_BYTES
    patched = patch_engine(bytes(original))
    assert patched[PATCH_OFFSET:] == PATCHED_BYTES
    assert patched[:PATCH_OFFSET] == original[:PATCH_OFFSET]


def test_852_1_tier0_patch_matches_the_known_dll_when_available():
    source = Path(r"C:\Users\Niko\Documents\p2betas\852_1\bin\tier0.dll")
    if not source.is_file() or sha256_file(source) != ORIGINAL_852_1_TIER0_SHA256:
        return
    patched = patch_852_1_tier0(source.read_bytes())
    assert sha256(patched).hexdigest() == PATCHED_852_1_TIER0_SHA256
    assert Tier0ThreadLimit8521Patch.id == "p15"


def test_july_2010_asset_patch_uses_requested_description():
    assert July2010AssetsPatch.description == "Copy extra assets from July 2010 852_2, including some dialogue."
    assert July2009AssetsPatch.description == (
        "Copy required assets from July 2009 852_0. Game will not launch without this."
    )


def test_july_2010_asset_merge_overlays_852_0_last(tmp_path):
    assets_8522 = tmp_path / "852_2"
    assets_8520 = tmp_path / "852_0"
    destination = tmp_path / "merged"
    assets_8522.mkdir()
    assets_8520.mkdir()
    destination.mkdir()
    (assets_8522 / "shared.txt").write_bytes(b"852_2")
    (assets_8522 / "only-852_2.txt").write_bytes(b"new")
    (assets_8520 / "shared.txt").write_bytes(b"852_0")
    (assets_8520 / "only-852_0.txt").write_bytes(b"old")
    shutil.copytree(assets_8522, destination, dirs_exist_ok=True)
    context = PatchContext(tmp_path, None, BuildReport(), Event())

    overlay_tree(assets_8520, destination, context, lambda _event: None)

    assert (destination / "shared.txt").read_bytes() == b"852_0"
    assert (destination / "only-852_2.txt").read_bytes() == b"new"
    assert (destination / "only-852_0.txt").read_bytes() == b"old"


def test_march_asset_bundle_is_pinned_and_uses_only_game_roots():
    assets = read_bundle()
    assert len(MARCH_ASSET_ARCHIVE_SHA256) == 64
    assert assets
    assert {path.split("/", 1)[0] for path in assets} == {"portal", "portal2", "portal2_tempcontent"}


def test_march_asset_patch_installs_the_bundle(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = MarchAssetsPatch()

    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)


def test_source_thread_fix_release_is_pinned():
    assert DOWNLOAD_URL == "https://dl.mikes.software/sourcethreadfix/threadfix-v1.3-win32.zip"
    assert len(THREAD_FIX_ARCHIVE_SHA256) == 64
    assert set(FILES) == {"hl2.wrap.exe", "LICENCE-threadfix"}


def test_source_thread_fix_keeps_its_license_in_metadata_folder(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    assert destination_path(context, "hl2.wrap.exe") == tmp_path / "hl2.wrap.exe"
    assert destination_path(context, "LICENCE-threadfix") == tmp_path / ".p2patcher" / "LICENCE-threadfix"


def test_launcher_uses_wrapper_with_normal_executable_fallback():
    assert b'if exist "%ROOT%game\\hl2.exe" set "GAMEROOT=%ROOT%game\\"' in LAUNCHER
    assert b'"%GAMEROOT%hl2.wrap.exe"' in LAUNCHER
    assert b'set "GAME=hl2.exe"' in LAUNCHER
    assert b'if exist "%GAMEROOT%hl2.wrap.exe"' in LAUNCHER
    assert b'if exist "%GAMEROOT%portal2\\cfg\\patcher_multicore.cfg"' in LAUNCHER


def test_first_launch_audio_setup_retries_and_then_skips(tmp_path):
    if os.name != "nt":
        import pytest
        pytest.skip("Exercises the Windows launcher")
    root = tmp_path / "game folder"
    root.mkdir()
    context = PatchContext(root, None, BuildReport(), Event())
    patch = LaunchersPatch()
    patch.apply(context, lambda *_args: None)
    patch.verify(context)
    script = root / "Launch Portal 2.cmd"
    # Replace process creation with a controllable stand-in; run the real batch control flow.
    content = script.read_text()
    lines = []
    for line in content.splitlines():
        if line.startswith('start "" /wait'):
            line = 'call "%ROOT%setup.cmd"'
        elif line.startswith('start "" /D'):
            line = 'echo launch>>"%ROOT%calls.txt"'
        elif line.strip() == "pause":
            line = "rem pause"
        lines.append(line)
    script.write_text("\n".join(lines))
    setup = root / "setup.cmd"
    setup.write_text('@echo setup>>"%ROOT%calls.txt"\n@exit /b 1\n')
    def run():
        return subprocess.run(["cmd.exe", "/d", "/c", str(script)], capture_output=True, timeout=10)
    assert run().returncode == 1
    marker = root / ".p2patcher" / "patcher-audiocache.done"
    assert not marker.exists()
    setup.write_text('@echo setup>>"%ROOT%calls.txt"\n@exit /b 0\n')
    assert run().returncode == 0
    assert marker.is_file()
    assert run().returncode == 0
    assert (root / "calls.txt").read_text().splitlines() == ["setup", "setup", "launch", "launch"]


def test_generic_launcher_has_no_audio_setup(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event(), mode="generic")
    patch = LaunchersPatch()
    patch.apply(context, lambda *_args: None)
    patch.verify(context)
    assert (tmp_path / "Launch Portal 2.cmd").read_bytes() == LAUNCHER


def test_multicore_compatibility_patch_does_not_touch_autoexec(tmp_path):
    cfg = tmp_path / "portal2" / "cfg"
    cfg.mkdir(parents=True)
    autoexec = cfg / "autoexec.cfg"
    autoexec.write_text("echo mine\n", encoding="utf-8")
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = MulticorePatch()

    patch.apply(context, lambda *_args: None)
    patch.verify(context)

    assert (cfg / "patcher_multicore.cfg").read_bytes() == MULTICORE_CONFIG
    assert autoexec.read_text(encoding="utf-8") == "echo mine\n"


def test_goldberg_patch_is_reversible_and_uses_user_zip(tmp_path, monkeypatch):
    root = tmp_path / "build"
    api = root / "bin" / "steam_api.dll"
    api.parent.mkdir(parents=True)
    api.write_bytes(b"original steam api")
    interface = api.parent / "steam_interfaces.txt"
    interface.write_bytes(b"original interfaces\n")
    archive = tmp_path / "goldberg.zip"
    archive.write_bytes(b"selected by user")
    payloads = {
        "steam_api.dll": b"goldberg steam api",
        "tools/generate_interfaces_file.exe": b"generator",
    }
    monkeypatch.setattr("patches.p10_goldberg.read_goldberg_archive", lambda path: payloads)
    monkeypatch.setattr("patches.p10_goldberg.generate_interfaces", lambda generator, original: b"generated interfaces\n")
    context = PatchContext(root, None, BuildReport(), Event(), goldberg_archive=archive)
    patch = GoldbergPatch()

    patch.apply(context, lambda *_args: None)
    patch.verify(context)

    assert api.read_bytes() == payloads["steam_api.dll"]
    assert api.with_name("steam_api.original.bak").read_bytes() == b"original steam api"
    assert interface.read_bytes() == b"generated interfaces\n"
    assert interface.with_name("steam_interfaces.original.bak").read_bytes() == b"original interfaces\n"
    assert not (root / "Restore original Steam API.cmd").exists()
    assert not (root / "goldberg-patch.json").exists()
    assert not (root / "Goldberg Readme.txt").exists()
    assert len(GOLDBERG_ARCHIVE_SHA256) == 64


def test_hammer_and_hlmv_files_use_the_fixed_layout(tmp_path):
    config = game_config(tmp_path).decode("utf-8")
    hammer = hammer_launcher(tmp_path).decode("utf-8")
    hlmv = hlmv_launcher(tmp_path).decode("utf-8")

    assert f'"GameDir" "{tmp_path}\\game\\portal2"' in config
    assert "-nop4 -threads 4" in hammer
    assert "hammer.exe" in hammer
    assert "hlmv.exe -nop4" in hlmv
    assert 'VPROJECT=%ROOT%game\\portal2' in hlmv
    assert 'cd /d "%ROOT%game\\bin"' in hammer
    assert f'"BSP" "{tmp_path}\\game\\bin\\vbsp.exe"' in config
    assert len(PATCHED_TIER0_SHA256) == 64


def test_hammer_layout_physically_moves_runtime_without_duplicates(tmp_path):
    for name in RUNTIME_DIRECTORIES:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "kept.txt").write_text(name, encoding="utf-8")
    (tmp_path / "hl2.exe").write_bytes(b"launcher")
    (tmp_path / "hl2.wrap.exe").write_bytes(b"wrapper")

    move_runtime_into_game(tmp_path)

    for name in RUNTIME_DIRECTORIES:
        assert (tmp_path / "game" / name / "kept.txt").read_text(encoding="utf-8") == name
        assert not (tmp_path / name).exists()
    assert (tmp_path / "game" / "hl2.exe").read_bytes() == b"launcher"
    assert (tmp_path / "game" / "hl2.wrap.exe").read_bytes() == b"wrapper"


def test_hl2_assets_use_curated_compatibility_allowlist():
    assert ASSET_MARKER == "p1-curated-v2\n"
    assert len(HL2_ASSET_ALLOWLIST) == 312
    assert "sound/weapons/physcannon/physcannon_pickup.wav" in HL2_ASSET_ALLOWLIST
    assert "sound/vo/novaprospekt/al_pickherup.wav" not in HL2_ASSET_ALLOWLIST
    assert not any(path.startswith("media/") for path in HL2_ASSET_ALLOWLIST)


def test_sound_manifest_registers_only_copied_hl2_scripts():
    copied_scripts = {
        path.removeprefix("scripts/")
        for path in HL2_ASSET_ALLOWLIST
        if path.startswith("scripts/")
    }
    assert set(HL2_SOUND_SCRIPTS) == copied_scripts
    assert "npc_sounds_alyx.txt" not in HL2_SOUND_SCRIPTS


def test_selected_loose_hl2_assets_are_copied_without_overwriting(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "talker").mkdir(parents=True)
    destination.mkdir()
    (source / "game_sounds.txt").write_text("source sound", encoding="utf-8")
    (source / "talker" / "npc.txt").write_text("source npc", encoding="utf-8")
    (destination / "game_sounds.txt").write_text("existing sound", encoding="utf-8")

    written, skipped, byte_count, file_count = copy_selected_loose_assets(
        source,
        destination,
        {"game_sounds.txt", "talker/npc.txt"},
        Event(),
        lambda *_args: None,
    )

    assert (destination / "game_sounds.txt").read_text(encoding="utf-8") == "existing sound"
    assert (destination / "talker" / "npc.txt").read_text(encoding="utf-8") == "source npc"
    assert (written, skipped, file_count) == (1, 1, 2)
    assert byte_count == len("source npc")


def test_search_paths_mount_beta_tempcontent_before_retail_hl2(tmp_path):
    game_dir = tmp_path / "portal2"
    game_dir.mkdir()
    game_info = game_dir / "GameInfo.txt"
    game_info.write_text(
        '"GameInfo"\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n'
        '\t\t\tGame |gameinfo_path|.\n\t\t\tGame portal\n\t\t\tGame hl2\n'
        '\t\t}\n\t}\n}\n',
        encoding="utf-8",
    )
    context = PatchContext(tmp_path, tmp_path / "retail", BuildReport(), Event())
    patch = SearchPathsPatch()

    assert patch.check(context)
    patch.apply(context, lambda *_args: None)
    patch.verify(context)

    result = game_info.read_text(encoding="utf-8")
    assert result.index("Game\t\t\t\tportal2_tempcontent") < result.index("Game hl2")


def test_search_paths_work_without_half_life_2(tmp_path):
    game_dir = tmp_path / "portal2"
    game_dir.mkdir()
    game_info = game_dir / "GameInfo.txt"
    game_info.write_text(
        '"GameInfo"\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n'
        '\t\t\tGame |gameinfo_path|.\n\t\t\tGame portal\n'
        '\t\t}\n\t}\n}\n',
        encoding="utf-8",
    )
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = SearchPathsPatch()

    patch.apply(context, lambda *_args: None)
    patch.verify(context)

    result = game_info.read_text(encoding="utf-8")
    assert "portal2_tempcontent" in result
    assert "|gameinfo_path|..\\platform" in result
    assert not re.search(r"\bGame\s+hl2\b", result, re.IGNORECASE)


def test_prerelease_asset_bundle_is_small_and_pinned():
    assert archive_path().stat().st_size < 100_000
    assert len(ASSET_ARCHIVE_SHA256) == 64
    assert set(ASSET_HASHES) == {
        "portal/materials/props_animsign/signage_num00_frame.vmt",
        "portal/materials/props_animsign/signage_num00_frame.vtf",
        "portal2/materials/effects/huntertracer.vmt",
        "portal2/materials/effects/huntertracer.vtf",
        "portal2/particles/achievement.pcf",
    }


def test_prerelease_assets_install_and_update_manifest(tmp_path):
    manifest = tmp_path / "portal2" / "particles" / "particles_manifest.txt"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        b'particles_manifest\r\n{\r\n\t// Portal 2 particles\r\n'
        b'\t"file"\t\t"particles/airvents.pcf"\r\n}\r\n'
    )
    conflicting = tmp_path / "portal2" / "particles" / "achievement.pcf"
    conflicting.write_bytes(b"existing")
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = PrereleaseAssetsPatch()

    assert patch.check(context)
    patch.apply(context, lambda *_args: None)
    patch.verify(context)

    assert (conflicting.with_name("achievement.pcf.original.bak")).read_bytes() == b"existing"
    assert manifest.read_text(encoding="utf-8").count("particles/achievement.pcf") == 1
