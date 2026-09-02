from threading import Event

from models import BuildReport, PatchContext
from patches import PATCHES
from patches.p1_hl2_assets import ASSET_MARKER, HL2_ASSET_ALLOWLIST, copy_loose_hl2_scripts
from patches.p2_search_paths import SearchPathsPatch
from patches.p5_thread_fix import ARCHIVE_SHA256, DOWNLOAD_URL, FILES
from patches.p6_launchers import LAUNCHER


def test_patch_registry_is_explicitly_numbered():
    assert [patch.id for patch in PATCHES] == ["p1", "p2", "p3", "p4", "p5", "p6"]


def test_source_thread_fix_release_is_pinned():
    assert DOWNLOAD_URL == "https://dl.mikes.software/sourcethreadfix/threadfix-v1.3-win32.zip"
    assert len(ARCHIVE_SHA256) == 64
    assert set(FILES) == {"hl2.wrap.exe", "LICENCE-threadfix"}


def test_launcher_uses_source_thread_fix_wrapper():
    assert b'"%ROOT%hl2.wrap.exe"' in LAUNCHER


def test_hl2_assets_use_curated_compatibility_allowlist():
    assert ASSET_MARKER == "p1-curated-v2\n"
    assert len(HL2_ASSET_ALLOWLIST) == 312
    assert "sound/weapons/physcannon/physcannon_pickup.wav" in HL2_ASSET_ALLOWLIST
    assert "sound/vo/novaprospekt/al_pickherup.wav" not in HL2_ASSET_ALLOWLIST
    assert not any(path.startswith("media/") for path in HL2_ASSET_ALLOWLIST)


def test_loose_hl2_scripts_are_copied_without_overwriting(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "talker").mkdir(parents=True)
    destination.mkdir()
    (source / "game_sounds.txt").write_text("source sound", encoding="utf-8")
    (source / "talker" / "npc.txt").write_text("source npc", encoding="utf-8")
    (destination / "game_sounds.txt").write_text("existing sound", encoding="utf-8")

    written, skipped, byte_count, file_count = copy_loose_hl2_scripts(
        source,
        destination,
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
