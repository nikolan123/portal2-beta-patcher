import re
from threading import Event

from models import BuildReport, PatchContext
from patches import PATCHES, normalize_patch_ids
from patches.p1_hl2_assets import ASSET_MARKER, HL2_ASSET_ALLOWLIST, copy_selected_loose_assets
from patches.p2_search_paths import SearchPathsPatch
from patches.p5_thread_fix import ARCHIVE_SHA256 as THREAD_FIX_ARCHIVE_SHA256, DOWNLOAD_URL, FILES
from patches.p6_launchers import LAUNCHER
from patches.p7_hammer import PATCHED_TIER0_SHA256, game_config, hammer_launcher, hlmv_launcher
from patches.p8_prerelease_assets import (
    ASSET_HASHES,
    ARCHIVE_SHA256 as ASSET_ARCHIVE_SHA256,
    PrereleaseAssetsPatch,
    archive_path,
)


def test_patch_registry_is_explicitly_numbered():
    assert [patch.id for patch in PATCHES] == ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"]
    assert all(patch.description for patch in PATCHES)


def test_patch_dependencies_and_required_launcher():
    assert normalize_patch_ids(()) == ("p2", "p6")
    assert normalize_patch_ids(("p3",)) == ("p1", "p2", "p3", "p6")


def test_source_thread_fix_release_is_pinned():
    assert DOWNLOAD_URL == "https://dl.mikes.software/sourcethreadfix/threadfix-v1.3-win32.zip"
    assert len(THREAD_FIX_ARCHIVE_SHA256) == 64
    assert set(FILES) == {"hl2.wrap.exe", "LICENCE-threadfix"}


def test_launcher_uses_wrapper_with_normal_executable_fallback():
    assert b'"%ROOT%hl2.wrap.exe"' in LAUNCHER
    assert b'set "GAME=hl2.exe"' in LAUNCHER
    assert b'if exist "%ROOT%hl2.wrap.exe"' in LAUNCHER


def test_hammer_and_hlmv_files_use_the_fixed_layout(tmp_path):
    config = game_config(tmp_path).decode("utf-8")
    hammer = hammer_launcher(tmp_path).decode("utf-8")
    hlmv = hlmv_launcher(tmp_path).decode("utf-8")

    assert f'"GameDir" "{tmp_path}\\game\\portal2"' in config
    assert "-nop4 -threads 4" in hammer
    assert "hammer.exe" in hammer
    assert "hlmv.exe -nop4" in hlmv
    assert f'VPROJECT={tmp_path}\\game\\portal2' in hlmv
    assert len(PATCHED_TIER0_SHA256) == 64


def test_hl2_assets_use_curated_compatibility_allowlist():
    assert ASSET_MARKER == "p1-curated-v2\n"
    assert len(HL2_ASSET_ALLOWLIST) == 312
    assert "sound/weapons/physcannon/physcannon_pickup.wav" in HL2_ASSET_ALLOWLIST
    assert "sound/vo/novaprospekt/al_pickherup.wav" not in HL2_ASSET_ALLOWLIST
    assert not any(path.startswith("media/") for path in HL2_ASSET_ALLOWLIST)


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
