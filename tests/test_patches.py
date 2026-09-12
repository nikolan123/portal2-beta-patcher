from hashlib import sha256
import re
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event
from types import SimpleNamespace
import pytest

from models import BuildReport, PatchContext
from patches import (
    PATCHES,
    PATCH_COMPATIBILITY,
    compatible_patch_ids,
    normalize_patch_ids,
)
from patches.base import PatchError, sha256_file
from patches.build_852_0.hl2_assets.patch import HL2_ASSET_ALLOWLIST, Hl2AssetsPatch
from patches.helpers.retail_assets import CuratedHl2AssetsPatch, copy_selected_loose_assets
from patches.build_852_0.search_paths import SearchPathsPatch
from patches.build_852_0.sound_manifest import HL2_SOUND_SCRIPTS
from patches.build_852_0.dialogue import DialogueFixPatch, ORIGINAL_SCENE_CANCEL, PATCHED_SCENE_CANCEL, SCRIPT as DIALOGUE_MAPSPAWN, mapspawn_has_dialogue_fix, patch_glados_script
from patches.build_852_0.subtitles.patch import (
    FILES as SUBTITLE_FILES,
    Subtitles8520Patch,
    bundled_path as subtitle_bundled_path,
    mapspawn_has_subtitle_fixes,
)
from patches.build_852_0.continuous_campaign.patch import (
    LMP_HASHES as CAMPAIGN_LMP_HASHES,
    ContinuousCampaignPatch,
    bundled_path as campaign_bundled_path,
    validate_lmp,
)
from patches.build_852_0.vscript_scope_fix import (
    CLIENT_CODE_CAVE_RVA,
    CLIENT_ENTRY_RVA,
    CLIENT_SECTION_CODE_CAVE_RVA,
    ORIGINAL_CLIENT_ENTRY,
    ORIGINAL_CLIENT_SHA256,
    ORIGINAL_SERVER_SHA256,
    PATCHED_CLIENT_SHA256,
    PATCHED_SERVER_SHA256,
    PATCHED_CLIENT_TEXT_SIZE,
    SERVER_CODE_CAVE_RVA,
    SERVER_ENTRY_RVA,
    ORIGINAL_SERVER_ENTRY,
    PATCHED_SERVER_TEXT_SIZE,
    VScriptScopeFixPatch,
    patch_client,
    patch_server,
)
from patches.build_852_0.smooth_jazz import (
    CUES as SMOOTH_JAZZ_CUES,
    SmoothJazzPatch,
    trim_smooth_jazz,
)
from patches.generic.thread_fix.patch import (
    FILES,
    ThreadFixPatch,
    bundled_path,
    destination_path,
)
from patches.generic.launchers import LAUNCHER, LaunchersPatch
from patches.build_852_0.hammer import (
    PATCHED_TIER0_SHA256,
    RUNTIME_DIRECTORIES,
    game_config,
    hammer_launcher,
    hlmv_launcher,
    move_runtime_into_game,
)
from patches.build_852_0.extra_assets.patch import (
    ASSET_HASHES,
    ARCHIVE_SHA256 as ASSET_ARCHIVE_SHA256,
    PrereleaseAssetsPatch,
    archive_path,
)
from patches.generic.multicore import MULTICORE_CONFIG, MulticorePatch
from patches.generic.goldberg import ARCHIVE_SHA256 as GOLDBERG_ARCHIVE_SHA256, GoldbergPatch
from patches.build_852_1.legacy_paint import ORIGINAL_BYTES, PATCHED_BYTES, PATCH_OFFSET, patch_engine
from patches.build_852_1.extra_assets.from_july_2010 import July2010AssetsPatch
from patches.build_852_1.extra_assets.from_july_2009 import July2009AssetsPatch, overlay_tree
from patches.build_852_1.extra_assets.bundled import ARCHIVE_SHA256 as MARCH_ASSET_ARCHIVE_SHA256, MarchAssetsPatch, read_bundle
from patches.build_852_1.hammer import (
    EXPECTED_REFERENCE_OFFSETS as REFERENCE_OFFSETS_852_1,
    ORIGINAL_TIER0_SHA256 as ORIGINAL_852_1_TIER0_SHA256,
    PATCHED_TIER0_SHA256 as PATCHED_852_1_TIER0_SHA256,
    Hammer8521Patch,
    patch_852_1_tier0,
)
from patches.build_852_1 import hammer as hammer_852_1
from patches.build_841_0_prereset.missing_launcher.patch import (
    LAUNCHER_SHA256,
    Hl2LauncherPatch,
    launcher_path,
)
from patches.build_841_0_prereset.hl2_assets.patch import (
    HL2_ASSET_ALLOWLIST as MISSING_841_0_ASSETS,
    Hl2Assets8410Patch,
)
from patches.build_841_0_prereset.tier0_thread_limit import (
    EXPECTED_REFERENCE_OFFSETS as REFERENCE_OFFSETS_841_0,
    ORIGINAL_TIER0_SHA256 as ORIGINAL_841_0_TIER0_SHA256,
    PATCHED_TIER0_SHA256 as PATCHED_841_0_TIER0_SHA256,
    Tier0ThreadLimit8410Patch,
    patch_841_0_tier0,
)
from patches.build_841_0_prereset.progression_fixes.patch import (
    LMP_HASHES as PROGRESSION_LMP_HASHES,
    ProgressionFixes8410Patch,
    bundled_path as progression_bundled_path,
    patch_transition_script,
    transition_script_is_patched,
    validate_lmp as validate_progression_lmp,
)
from patches.build_852_0.multiplayer.patch import (
    BUNDLED_FILES as MULTIPLAYER_BUNDLED_FILES,
    Multiplayer8520Patch,
    SUPPORTED_SERVER_SHA256S,
    bundled_path as multiplayer_bundled_path,
)
from patches.build_852_2 import hammer as hammer_852_2
from patches.build_852_2.hammer import Hammer8522Patch
from patches import repair


def test_patch_registry_has_descriptive_ids_and_stable_order():
    assert [patch.id for patch in PATCHES] == ["852_0.hl2_assets", "852_0.search_paths", "852_0.sound_manifest", "852_0.dialogue", "852_0.subtitles", "852_0.continuous_campaign", "852_0.vscript_scope_fix", "852_0.smooth_jazz", "841_0_prereset.hl2_assets", "thread_fix", "launchers", "852_0.hammer", "852_0.extra_assets", "multicore", "goldberg", "852_1.legacy_paint", "852_1.extra_assets.from_july_2010", "852_1.extra_assets.from_july_2009", "852_1.extra_assets.bundled", "852_1.hammer", "841_0_prereset.missing_launcher", "841_0_prereset.tier0_thread_limit", "852_0.multiplayer", "852_2.hammer", "852_0.node_graphs", "841_0_prereset.node_graphs", "841_0_prereset.progression_fixes"]
    assert all(patch.description for patch in PATCHES)
    assert set(PATCH_COMPATIBILITY) == {"generic", (841, 0, 0x83CED978), (852, 0), (852, 1), (852, 2)}
    assert PATCH_COMPATIBILITY["generic"].required == {"launchers"}
    assert PATCH_COMPATIBILITY[(852, 0)].required == {"852_0.search_paths", "launchers"}
    assert PATCH_COMPATIBILITY[(852, 1)].required == {"launchers"}
    assert PATCH_COMPATIBILITY[(852, 1)].first_run_audio
    assert "852_2.hammer" in PATCH_COMPATIBILITY[(852, 2)].optional
    assert "852_1.extra_assets.from_july_2010" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "852_1.extra_assets.from_july_2009" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "852_1.extra_assets.bundled" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert "852_1.hammer" in PATCH_COMPATIBILITY[(852, 1)].optional
    assert PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].required == {"launchers"}
    assert "841_0_prereset.missing_launcher" in PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].optional
    assert "841_0_prereset.tier0_thread_limit" in PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].optional
    assert "841_0_prereset.progression_fixes" in PATCH_COMPATIBILITY[(841, 0, 0x83CED978)].optional


def test_841_0_progression_fixes_install_lmps_and_patch_transition_script(tmp_path):
    script = tmp_path / "portal2/scripts/vscripts/transitions/sp_transition_list.nut"
    script.parent.mkdir(parents=True)
    original = b"before\r\n\t\t\t// hook up the exit elevator\r\nafter\r\n"
    script.write_bytes(original)
    context = PatchContext(tmp_path, None, BuildReport(), Event(), mode="generic")
    patch = ProgressionFixes8410Patch()

    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert not patch.check(context)
    assert script.with_name("sp_transition_list.original.bak").read_bytes() == original

    patched = script.read_bytes()
    assert patch_transition_script(patched) == patched
    for expected in (
        b'sp_paint_stick_goo', b'entry_door_1', b'@hallway_entry',
        b'sp_paint_speed_intro', b'speed_intro_entry_door', b'crusher_room_exit_door',
        b'sp_paint_jump_artillery', b'artillery_entry_door', b'artillery_exit_door',
    ):
        assert expected in patched

    for name, expected_hash in PROGRESSION_LMP_HASHES.items():
        bundled = progression_bundled_path(name)
        installed = tmp_path / "portal2/maps" / name
        assert sha256_file(bundled) == expected_hash
        assert installed.read_bytes() == bundled.read_bytes()
        validate_progression_lmp(name, installed.read_bytes())


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_progression_script_preserves_line_endings_and_is_idempotent(newline):
    original = newline.join([b"before", b"\t\t\t// hook up the exit elevator", b"after", b""])
    patched = patch_transition_script(original)
    assert transition_script_is_patched(patched)
    assert patch_transition_script(patched) == patched
    assert patched.startswith(b"before" + newline)
    assert patched.endswith(b"after" + newline)
    if newline == b"\r\n":
        assert b"\n" not in patched.replace(b"\r\n", b"")


@pytest.mark.parametrize("damage", ["comment", "missing", "moved", "brace"])
def test_progression_script_rejects_incomplete_block(damage):
    patched = patch_transition_script(b"\t\t\t// hook up the exit elevator\n")
    line = b'\t\t\t\tEntFire( "artillery_exit_door", "SetPartner", "@hallway_exit", 0.0 )\n'
    if damage == "comment":
        broken = patched.replace(line, b"//" + line)
    elif damage == "missing":
        broken = patched.replace(line, b"")
    elif damage == "moved":
        broken = patched.replace(line, b"") + line
    else:
        broken = patched.replace(b"\t\t\t}\n", b"", 1)
    assert not transition_script_is_patched(broken)
    with pytest.raises(PatchError, match="incomplete"):
        patch_transition_script(broken)


def test_progression_lmps_contain_the_intended_entity_fixes():
    def entity(name, identifier):
        payload = progression_bundled_path(name).read_bytes()[20:]
        matches = [block for block in re.findall(rb"\{\n(.*?)\n\}", payload, re.DOTALL)
                   if identifier in block.split(b"\n")]
        assert len(matches) == 1
        return matches[0].split(b"\n")

    catapult = entity("sp_stop_the_box_l_0.lmp", b'"targetname" "flingroom_1_circular_catapult_2"')
    assert b'"classname" "trigger_catapult"' in catapult
    assert b'"spawnflags" "4105"' in catapult
    scene = entity("sp_glados_01_l_0.lmp", b'"hammerid" "2045731"')
    assert b'"classname" "logic_choreographed_scene"' in scene
    assert [line for line in scene if line.startswith(b'"OnCompletion"')] == [
        b'"OnCompletion" "exit_fade\x1bFade\x1b\x1b24\x1b-1"',
        b'"OnCompletion" "exit_teleport\x1bTeleport\x1b\x1b25\x1b-1"',
    ]


def test_patch_dependencies_and_required_launcher():
    assert normalize_patch_ids(()) == ("852_0.search_paths", "launchers")
    assert normalize_patch_ids(("852_0.sound_manifest",)) == ("852_0.hl2_assets", "852_0.search_paths", "852_0.sound_manifest", "launchers")
    assert normalize_patch_ids(("852_0.subtitles",)) == ("852_0.search_paths", "852_0.dialogue", "852_0.subtitles", "launchers")
    assert "multicore" not in normalize_patch_ids(("multicore",), "852_0")
    assert normalize_patch_ids(("852_0.hl2_assets", "852_0.dialogue", "thread_fix", "multicore"), "generic", depot_id=852, depot_version=2) == ("thread_fix", "launchers", "multicore")
    assert normalize_patch_ids(("goldberg",), "852_0") == ("852_0.search_paths", "launchers", "goldberg")
    assert normalize_patch_ids(("thread_fix",), "generic", runnable=False, depot_id=843, depot_version=1) == ("thread_fix",)
    assert normalize_patch_ids(("852_1.legacy_paint",), "generic", depot_id=852, depot_version=1) == ("launchers", "852_1.legacy_paint")
    assert normalize_patch_ids(("852_1.legacy_paint",), "generic", depot_id=852, depot_version=2) == ("launchers",)
    assert normalize_patch_ids(("852_1.legacy_paint",), "generic", depot_id=841, depot_version=1) == ("launchers",)
    assert normalize_patch_ids(("852_1.extra_assets.from_july_2010",), "generic", depot_id=852, depot_version=1) == ("launchers", "852_1.extra_assets.from_july_2010")
    assert normalize_patch_ids(("852_1.extra_assets.from_july_2010",), "generic", depot_id=852, depot_version=2) == ("launchers",)
    assert normalize_patch_ids(("852_1.extra_assets.from_july_2009",), "generic", depot_id=852, depot_version=1) == ("launchers", "852_1.extra_assets.from_july_2009")
    assert normalize_patch_ids(("852_1.extra_assets.from_july_2009",), "generic", depot_id=852, depot_version=2) == ("launchers",)
    assert normalize_patch_ids(("852_1.extra_assets.bundled",), "generic", depot_id=852, depot_version=1) == ("launchers", "852_1.extra_assets.bundled")
    assert normalize_patch_ids(("852_1.extra_assets.bundled",), "generic", depot_id=852, depot_version=2) == ("launchers",)
    assert normalize_patch_ids(("852_1.hammer",), "generic", depot_id=852, depot_version=1) == ("launchers", "852_1.hammer")
    assert normalize_patch_ids(("852_1.hammer",), "generic", depot_id=852, depot_version=2) == ("launchers",)
    assert compatible_patch_ids("852_0") == ("852_0.hl2_assets", "852_0.search_paths", "852_0.sound_manifest", "852_0.dialogue", "852_0.subtitles", "852_0.continuous_campaign", "852_0.vscript_scope_fix", "852_0.smooth_jazz", "thread_fix", "launchers", "852_0.hammer", "852_0.extra_assets", "goldberg", "852_0.multiplayer", "852_0.node_graphs")
    assert compatible_patch_ids("generic", 852, 1) == ("thread_fix", "launchers", "goldberg", "852_1.legacy_paint", "852_1.extra_assets.from_july_2010", "852_1.extra_assets.from_july_2009", "852_1.extra_assets.bundled", "852_1.hammer")
    assert compatible_patch_ids("generic", 852, 2) == ("thread_fix", "launchers", "multicore", "goldberg", "852_2.hammer")
    assert normalize_patch_ids((), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ()
    assert normalize_patch_ids((), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("launchers",)
    assert normalize_patch_ids(("841_0_prereset.missing_launcher",), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("841_0_prereset.missing_launcher",)
    assert normalize_patch_ids(("841_0_prereset.missing_launcher",), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("launchers", "841_0_prereset.missing_launcher")
    assert normalize_patch_ids(("841_0_prereset.tier0_thread_limit",), "generic", runnable=False, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("841_0_prereset.tier0_thread_limit",)
    assert normalize_patch_ids(("841_0_prereset.tier0_thread_limit",), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("launchers", "841_0_prereset.tier0_thread_limit")
    assert normalize_patch_ids(("841_0_prereset.progression_fixes",), "generic", runnable=True, depot_id=841, depot_version=0, depot_crc=0x83CED978) == ("launchers", "841_0_prereset.progression_fixes")


def test_841_0_pre_reset_launcher_patch_installs_the_binary(tmp_path):
    assert sha256_file(launcher_path()) == LAUNCHER_SHA256
    patch = Hl2LauncherPatch()
    context = PatchContext(tmp_path, None, BuildReport(), Event(), mode="generic")
    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert sha256_file(tmp_path / "hl2.exe") == LAUNCHER_SHA256


@pytest.mark.parametrize("patch_class", [Hl2AssetsPatch, Hl2Assets8410Patch])
def test_hl2_asset_builds_share_copy_behavior(tmp_path, monkeypatch, patch_class):
    relative = "sound/weapons/test.wav"
    payload = b"retail HL2 sound"
    from patches.helpers import retail_assets as hl2_assets
    patch = patch_class()
    assert isinstance(patch, CuratedHl2AssetsPatch)
    patch.allowlist = frozenset({relative, "materials/test.vmt"})
    monkeypatch.setattr(patch, "_source_archives", lambda _root: [tmp_path / "test_dir.vpk"])
    archive = SimpleNamespace(
        entries=[SimpleNamespace(path=relative), SimpleNamespace(path="sound/unrelated.wav")],
        read_entry=lambda _entry: payload,
    )
    monkeypatch.setattr(hl2_assets, "VPKArchive", lambda _path: archive)
    loose = tmp_path / "retail-hl2/hl2/materials/test.vmt"
    loose.parent.mkdir(parents=True)
    loose.write_bytes(b"loose material")
    context = PatchContext(tmp_path, tmp_path / "retail-hl2", BuildReport(), Event(), mode="generic")

    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert not patch.check(context)
    output = patch._asset_folder(context)
    assert (output / Path(relative)).read_bytes() == payload
    assert (output / "materials/test.vmt").read_bytes() == b"loose material"
    assert not (output / "sound/unrelated.wav").exists()
    destination = output / Path(relative)
    destination.write_bytes(b"existing user asset")
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert destination.read_bytes() == b"existing user asset"
    assert not destination.with_name(destination.name + ".original.bak").exists()


def test_hl2_assets_missing_from_source_are_not_marked_complete(tmp_path, monkeypatch):
    patch = Hl2Assets8410Patch()
    patch.allowlist = frozenset({"materials/effects/huntertracer.vmt"})
    monkeypatch.setattr(patch, "_source_archives", lambda _source: [])
    context = PatchContext(tmp_path / "output", tmp_path / "source", BuildReport(), Event())
    with pytest.raises(PatchError, match="materials/effects/huntertracer.vmt"):
        patch.apply(context, lambda _event: None)
    assert not patch._marker(context).exists()
    assert patch.check(context)


def test_hl2_asset_verification_uses_files_not_current_report(tmp_path):
    patch = Hl2Assets8410Patch()
    patch.allowlist = frozenset({"sound/test.wav"})
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    asset = patch._asset_folder(context) / "sound/test.wav"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"existing asset")
    patch._marker(context).write_text(patch.asset_marker, encoding="ascii")
    patch.verify(context)
    assert not patch.check(context)
    asset.unlink()
    assert patch.check(context)
    with pytest.raises(PatchError, match="sound/test.wav"):
        patch.verify(context)


def test_852_0_silently_skips_unavailable_assets(tmp_path, monkeypatch):
    patch = Hl2AssetsPatch()
    patch.allowlist = frozenset({"sound/available.wav", "sound/missing.wav"})
    monkeypatch.setattr(patch, "_source_archives", lambda _source: [])
    source = tmp_path / "source"
    available = source / "hl2/sound/available.wav"
    available.parent.mkdir(parents=True)
    available.write_bytes(b"sound")
    context = PatchContext(tmp_path / "output", source, BuildReport(), Event())
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert (context.root / "hl2/sound/available.wav").read_bytes() == b"sound"
    assert not (context.root / "hl2/sound/missing.wav").exists()
    assert context.report.warnings == []
    assert not patch.check(context)


def test_841_0_missing_runtime_asset_manifest_is_the_verified_retail_set():
    assert len(MISSING_841_0_ASSETS) == 25
    assert sum(path.startswith("materials/") for path in MISSING_841_0_ASSETS) == 5
    assert sum(path.startswith("sound/") for path in MISSING_841_0_ASSETS) == 20
    assert {
        "sound/ambient/materials/metal4.wav",
        "sound/doors/default_stop.wav",
        "sound/doors/handle_pushbar_open1.wav",
        "sound/doors/vent_open2.wav",
        "sound/doors/vent_open3.wav",
        "sound/ui/buttonclickrelease.wav",
        "sound/ui/buttonrollover.wav",
        "sound/weapons/fx/nearmiss/bulletltor03.wav",
        "sound/weapons/fx/nearmiss/bulletltor10.wav",
    } <= MISSING_841_0_ASSETS


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
    assert Tier0ThreadLimit8410Patch.id == "841_0_prereset.tier0_thread_limit"


def test_legacy_paint_patch_changes_only_the_missing_key_default():
    original = bytearray(PATCH_OFFSET + len(ORIGINAL_BYTES))
    original[PATCH_OFFSET:] = ORIGINAL_BYTES
    patched = patch_engine(bytes(original))
    assert patched[PATCH_OFFSET:] == PATCHED_BYTES
    assert patched[:PATCH_OFFSET] == original[:PATCH_OFFSET]


def test_mixup_turret_fix_matches_the_verified_852_0_dlls_when_available(tmp_path):
    server_source = Path(r"C:\Users\Niko\Documents\p2betas\852_0\portal2\bin\Server.dll.p2bp-turret-crash-backup")
    client_source = Path(r"C:\Users\Niko\Documents\p2betas\852_0\portal2\bin\Client.dll")
    if (
        not server_source.is_file()
        or sha256_file(server_source) != ORIGINAL_SERVER_SHA256
        or not client_source.is_file()
        or sha256_file(client_source) != ORIGINAL_CLIENT_SHA256
    ):
        return
    original_server = server_source.read_bytes()
    original_client = client_source.read_bytes()
    patched_server = patch_server(original_server)
    patched_client = patch_client(original_client)
    assert sha256(patched_server).hexdigest() == PATCHED_SERVER_SHA256
    assert sha256(patched_client).hexdigest() == PATCHED_CLIENT_SHA256
    assert patched_server[SERVER_ENTRY_RVA:SERVER_ENTRY_RVA + len(ORIGINAL_SERVER_ENTRY)] != ORIGINAL_SERVER_ENTRY
    assert patched_server[SERVER_CODE_CAVE_RVA:SERVER_CODE_CAVE_RVA + 2] == b"\x85\xC0"
    assert PATCHED_SERVER_TEXT_SIZE.to_bytes(4, "little") in patched_server[:0x1000]
    assert patched_client[CLIENT_ENTRY_RVA:CLIENT_ENTRY_RVA + len(ORIGINAL_CLIENT_ENTRY)] != ORIGINAL_CLIENT_ENTRY
    assert patched_client[CLIENT_CODE_CAVE_RVA:CLIENT_CODE_CAVE_RVA + 6] == ORIGINAL_CLIENT_ENTRY
    assert patched_client[CLIENT_SECTION_CODE_CAVE_RVA:CLIENT_SECTION_CODE_CAVE_RVA + 6] == bytes.fromhex("8B 3B 85 FF 7D 04")
    assert PATCHED_CLIENT_TEXT_SIZE.to_bytes(4, "little") in patched_client[:0x1000]
    assert VScriptScopeFixPatch.id == "852_0.vscript_scope_fix"
    assert {ORIGINAL_SERVER_SHA256, PATCHED_SERVER_SHA256} <= SUPPORTED_SERVER_SHA256S

    server_destination = tmp_path / "portal2" / "bin" / "Server.dll"
    client_destination = tmp_path / "portal2" / "bin" / "Client.dll"
    server_destination.parent.mkdir(parents=True)
    server_destination.write_bytes(original_server)
    client_destination.write_bytes(original_client)
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = VScriptScopeFixPatch()
    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert not patch.check(context)
    assert sha256_file(server_destination.with_name("server.original.bak")) == ORIGINAL_SERVER_SHA256
    assert sha256_file(client_destination.with_name("client.original.bak")) == ORIGINAL_CLIENT_SHA256


def test_smooth_jazz_patch_keeps_only_the_dialogue_in_both_cues_when_available(tmp_path):
    source_root = Path(r"C:\Users\Niko\Documents\p2betas\852_0\portal2_tempcontent\sound\vo\glados")
    sources = tuple(source_root / cue.filename for cue in SMOOTH_JAZZ_CUES)
    if any(not source.is_file() for source in sources):
        return
    if any(sha256_file(source) != cue.original_sha256 for source, cue in zip(sources, SMOOTH_JAZZ_CUES)):
        return
    destination_root = tmp_path / "portal2_tempcontent" / "sound" / "vo" / "glados"
    destination_root.mkdir(parents=True)
    for source, cue in zip(sources, SMOOTH_JAZZ_CUES):
        original = source.read_bytes()
        patched = trim_smooth_jazz(original, cue.cut_seconds)
        kept_data_size = cue.cut_seconds * 88200
        assert sha256(patched).hexdigest() == cue.patched_sha256
        assert len(patched) == 44 + kept_data_size
        assert int.from_bytes(patched[4:8], "little") == len(patched) - 8
        assert int.from_bytes(patched[40:44], "little") == kept_data_size
        assert patched[8:40] == original[8:40]
        assert patched[44:] == original[44:44 + kept_data_size]
        (destination_root / cue.filename).write_bytes(original)

    destination_music = tmp_path / "portal2_tempcontent" / "sound" / "music" / "smooth_jazz.mp3"
    destination_music.parent.mkdir(parents=True)
    destination_music.write_bytes(b"any credits music")

    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = SmoothJazzPatch()
    assert patch.check(context)
    patch.apply(context, lambda _event: None)
    patch.verify(context)
    assert not patch.check(context)
    for cue in SMOOTH_JAZZ_CUES:
        backup = destination_root / f"{Path(cue.filename).stem}.original.bak"
        assert sha256_file(backup) == cue.original_sha256
    assert not destination_music.exists()


def test_dialogue_patch_replaces_single_player_scene_cancellation():
    original = b"before\n" + ORIGINAL_SCENE_CANCEL + b"after\n"
    patched = patch_glados_script(original)
    assert ORIGINAL_SCENE_CANCEL not in patched
    assert PATCHED_SCENE_CANCEL in patched
    assert patch_glados_script(patched) == patched


def test_subtitle_patch_installs_dictionary_and_map_fixes(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = Subtitles8520Patch()

    patch.apply(context, lambda _event: None)
    patch.verify(context)

    for name, relative in SUBTITLE_FILES.items():
        assert (tmp_path / relative).read_bytes() == subtitle_bundled_path(name).read_bytes()
    sphere_sounds = subtitle_bundled_path("game_sounds_spheres_auto_generated.txt").read_bytes().replace(b"\r\n", b"\n")
    for event in (b"NOTHELD", b"HELD", b"PAIN"):
        prefix = b'"sphere02.' + event + b'"\n{\n\t"channel"\t"CHAN_AUTO"\n\t"volume"\t"0"'
        assert prefix in sphere_sounds
    assert b'"sphere02.AQUARIUM01"\n{\n\t"channel"\t"CHAN_VOICE"' in sphere_sounds
    mapspawn = tmp_path / "portal2" / "scripts" / "vscripts" / "mapspawn.nut"
    assert mapspawn_has_subtitle_fixes(mapspawn.read_bytes())
    assert b'GetMapName() == "p2_lab_hub_2"' in mapspawn.read_bytes()
    assert (tmp_path / "portal2" / "cfg" / "patcher_subtitles.cfg").read_bytes().splitlines() == [b"scene_maxcaptionradius 0"]


def test_continuous_campaign_patch_installs_verified_lmps(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = ContinuousCampaignPatch()

    patch.apply(context, lambda _event: None)
    patch.verify(context)

    for name, expected_hash in CAMPAIGN_LMP_HASHES.items():
        source = campaign_bundled_path(name)
        destination = tmp_path / "portal2" / "maps" / name
        assert sha256_file(source) == expected_hash
        assert destination.read_bytes() == source.read_bytes()
        validate_lmp(name, destination.read_bytes())

    catapult = (tmp_path / "portal2" / "maps" / "p2_lab_catapult_l_0.lmp").read_bytes()
    assert b'slowtime_enable_on_catapult\x1bTurnOff\x1b\x1b0\x1b1' in catapult
    hub_1 = (tmp_path / "portal2" / "maps" / "p2_lab_hub_1_l_0.lmp").read_bytes()
    assert b'changelevel p2_lab_slowfield_1' in hub_1
    assert b'\x1bmap p2_lab_slowfield_1\x1b' not in hub_1
    hub_6 = (tmp_path / "portal2" / "maps" / "p2_lab_hub_6_l_0.lmp").read_bytes()
    assert b'campaign_incomplete_meow' in hub_6
    hub_6_entities = re.findall(rb"\{.*?\}", hub_6[20:], flags=re.DOTALL)
    assert b'"targetname" "campaign_incomplete_meow"' in hub_6_entities[1]


def test_subtitle_patch_does_not_touch_autoexec(tmp_path):
    autoexec = tmp_path / "portal2" / "cfg" / "autoexec.cfg"
    autoexec.parent.mkdir(parents=True)
    original = b"echo mine\r\n"
    autoexec.write_bytes(original)
    context = PatchContext(tmp_path, None, BuildReport(), Event())

    Subtitles8520Patch().apply(context, lambda _event: None)

    assert autoexec.read_bytes() == original


def test_dialogue_verification_accepts_subtitle_setup_appended_after_it(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    mapspawn = tmp_path / "portal2" / "scripts" / "vscripts" / "mapspawn.nut"
    glados = tmp_path / "portal2" / "scripts" / "vscripts" / "choreo" / "glados.nut"
    mapspawn.parent.mkdir(parents=True)
    glados.parent.mkdir(parents=True)
    mapspawn.write_bytes(DIALOGUE_MAPSPAWN)
    glados.write_bytes(b"before\n" + PATCHED_SCENE_CANCEL + b"after\n")

    Subtitles8520Patch().apply(context, lambda _event: None)

    assert mapspawn_has_dialogue_fix(mapspawn.read_bytes())
    DialogueFixPatch().verify(context)


def test_multiplayer_patch_bundles_32_bit_source_built_asi_and_pinned_loader():
    for destination, expected_hash in MULTIPLAYER_BUNDLED_FILES.items():
        name = {
            "d3d9.dll": "asi_d3d9.dll",
            "dxwrapper.dll": "asi_dxwrapper.dll",
            "dxwrapper.ini": "asi_dxwrapper.ini",
            "scripts/p2beta_multiplayer_852_0.asi": "multiplayer.asi",
        }[destination]
        source = multiplayer_bundled_path(name)
        assert source.is_file()
        if expected_hash is not None:
            assert sha256_file(source) == expected_hash

    asi = multiplayer_bundled_path("multiplayer.asi").read_bytes()
    pe_offset = int.from_bytes(asi[0x3C:0x40], "little")
    assert asi[:2] == b"MZ"
    assert asi[pe_offset:pe_offset + 4] == b"PE\0\0"
    assert int.from_bytes(asi[pe_offset + 4:pe_offset + 6], "little") == 0x14C


def test_multiplayer_patch_installs_runtime_files_without_changing_game_dlls(tmp_path, monkeypatch):
    engine = tmp_path / "bin" / "engine.dll"
    server = tmp_path / "portal2" / "bin" / "server.dll"
    engine.parent.mkdir(parents=True)
    server.parent.mkdir(parents=True)
    engine.write_bytes(b"engine")
    server.write_bytes(b"server")
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = Multiplayer8520Patch()
    monkeypatch.setattr(Multiplayer8520Patch, "_validate_build", lambda self, context: None)

    patch.apply(context, lambda _event: None)
    patch.verify(context)

    assert engine.read_bytes() == b"engine"
    assert server.read_bytes() == b"server"
    assert (tmp_path / "bin" / "scripts" / "p2beta_multiplayer_852_0.asi").is_file()
    assert (tmp_path / ".p2patcher" / "LICENCE-dxwrapper.txt").is_file()


def test_852_1_hammer_tier0_patch_matches_the_known_dll_when_available():
    source = Path(r"C:\Users\Niko\Documents\p2betas\852_1\bin\tier0.dll")
    if not source.is_file() or sha256_file(source) != ORIGINAL_852_1_TIER0_SHA256:
        return
    patched = patch_852_1_tier0(source.read_bytes())
    assert sha256(patched).hexdigest() == PATCHED_852_1_TIER0_SHA256
    assert Hammer8521Patch.id == "852_1.hammer"


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


def test_source_thread_fix_wrapper_is_pinned_and_license_is_bundled():
    assert set(FILES) == {"hl2.wrap.exe", "LICENCE-threadfix"}
    assert sha256_file(bundled_path("hl2.wrap.exe")) == FILES["hl2.wrap.exe"]
    assert FILES["LICENCE-threadfix"] is None
    assert bundled_path("LICENCE-threadfix").read_bytes()


def test_source_thread_fix_keeps_its_license_in_metadata_folder(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    assert destination_path(context, "hl2.wrap.exe") == tmp_path / "hl2.wrap.exe"
    assert destination_path(context, "LICENCE-threadfix") == tmp_path / ".p2patcher" / "LICENCE-threadfix"


def test_source_thread_fix_installs_bundled_wrapper_and_license(tmp_path):
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = ThreadFixPatch()

    patch.apply(context, lambda _event: None)
    patch.verify(context)

    assert (tmp_path / "hl2.wrap.exe").read_bytes() == bundled_path("hl2.wrap.exe").read_bytes()
    assert (tmp_path / ".p2patcher" / "LICENCE-threadfix").read_bytes() == bundled_path("LICENCE-threadfix").read_bytes()


def test_launcher_uses_wrapper_with_normal_executable_fallback():
    assert b'if exist "%ROOT%game\\hl2.exe" set "GAMEROOT=%ROOT%game\\"' in LAUNCHER
    assert b'if exist "%ROOT%game\\portal2.exe" set "GAMEROOT=%ROOT%game\\"' in LAUNCHER
    assert b'"%GAMEROOT%hl2.wrap.exe"' in LAUNCHER
    assert b'set "GAME=hl2.exe"' in LAUNCHER
    assert b'if not exist "%GAMEROOT%hl2.exe" if exist "%GAMEROOT%portal2.exe" set "GAME=portal2.exe"' in LAUNCHER
    assert b'if exist "%GAMEROOT%hl2.exe" if exist "%GAMEROOT%hl2.wrap.exe"' in LAUNCHER
    assert b'if exist "%GAMEROOT%portal2\\cfg\\patcher_multicore.cfg"' in LAUNCHER
    assert b'if exist "%GAMEROOT%portal2\\cfg\\patcher_subtitles.cfg"' in LAUNCHER
    assert b'%MULTICORE% %SUBTITLES% %*' in LAUNCHER


def test_first_launch_audio_setup_retries_and_then_skips(tmp_path):
    if os.name != "nt":
        import pytest
        pytest.skip("Exercises the Windows launcher")
    root = tmp_path / "game folder"
    root.mkdir()
    context = PatchContext(root, None, BuildReport(), Event(), profile=PATCH_COMPATIBILITY[(852, 0)])
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
    monkeypatch.setattr("patches.generic.goldberg.read_goldberg_archive", lambda path: payloads)
    monkeypatch.setattr("patches.generic.goldberg.generate_interfaces", lambda generator, original: b"generated interfaces\n")
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


def test_852_1_hammer_config_and_gameinfo_patch(tmp_path):
    config = hammer_852_1.game_config(tmp_path).decode("utf-8")
    launcher = hammer_852_1.hammer_launcher().decode("ascii")
    gameinfo = (
        b'"GameInfo"\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n'
        b'\t\t\tGame\t\t\t\tportal2_tempcontent\n'
        b'\t\t\tGame\t\t\t\tportal\n\t\t}\n\t}\n}\n'
    )

    patched = hammer_852_1.patch_gameinfo(gameinfo)

    assert f'"GameDir" "{tmp_path}\\portal2"' in config
    assert f'"MapDir" "{tmp_path}\\content\\portal2\\mapsrc"' in config
    assert '-nop4 -threads 4' in launcher
    assert b'|gameinfo_path|..\\platform' in patched
    assert hammer_852_1.patch_gameinfo(patched) == patched


def test_852_1_moved_build_rewrites_absolute_hammer_paths(tmp_path, monkeypatch):
    for path in (
        tmp_path / "bin" / "hammer.exe",
        tmp_path / "bin" / "portal2.fgd",
        tmp_path / "bin" / "tier0.dll",
        tmp_path / "platform" / "materials" / "Editor" / "wireframe.vmt",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    gameinfo = tmp_path / "portal2" / "GameInfo.txt"
    gameinfo.parent.mkdir(parents=True)
    gameinfo.write_bytes(
        b'"GameInfo"\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n'
        b'\t\t\tGame\t\t\t\tportal2_tempcontent\n'
        b'\t\t\tGame\t\t\t\t|gameinfo_path|..\\platform\n\t\t}\n\t}\n}\n'
    )
    monkeypatch.setattr(hammer_852_1, "sha256_file", lambda _path: hammer_852_1.PATCHED_TIER0_SHA256)

    hammer_852_1.repair_moved_tools(tmp_path)

    config = (tmp_path / "bin" / "GameConfig.txt").read_text(encoding="utf-8")
    assert f'"GameDir" "{tmp_path.resolve()}\\portal2"' in config
    assert (tmp_path / "content" / "portal2" / "mapsrc").is_dir()
    assert (tmp_path / "Launch Hammer.cmd").read_bytes() == hammer_852_1.hammer_launcher()


def test_852_2_moved_build_rewrites_absolute_hammer_paths(tmp_path, monkeypatch):
    for path in (
        tmp_path / "bin" / "hammer.exe",
        tmp_path / "bin" / "portal2.fgd",
        tmp_path / "bin" / "tier0.dll",
        tmp_path / "platform" / "materials" / "Editor" / "wireframe.vmt",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    gameinfo = tmp_path / "portal2" / "GameInfo.txt"
    gameinfo.parent.mkdir(parents=True)
    gameinfo.write_bytes(
        b'"GameInfo"\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n'
        b'\t\t\tGame\t\t\t\tportal2_tempcontent\n'
        b'\t\t\tGame\t\t\t\t|gameinfo_path|..\\platform\n\t\t}\n\t}\n}\n'
    )
    monkeypatch.setattr(hammer_852_2, "sha256_file", lambda _path: hammer_852_2.PATCHED_TIER0_SHA256)

    hammer_852_2.repair_moved_tools(tmp_path)

    config = (tmp_path / "bin" / "GameConfig.txt").read_text(encoding="utf-8")
    assert f'"GameDir" "{tmp_path.resolve()}\\portal2"' in config
    assert (tmp_path / "content" / "portal2" / "mapsrc").is_dir()
    assert (tmp_path / "Launch Hammer.cmd").read_bytes() == hammer_852_2.hammer_launcher()


def test_moved_build_repair_detects_supported_layouts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(repair, "repair_852_0_tools", lambda root: calls.append(("852_0", root)))
    monkeypatch.setattr(repair, "repair_852_1_tools", lambda root: calls.append(("852_1", root)))
    monkeypatch.setattr(repair, "repair_852_2_tools", lambda root: calls.append(("852_2", root)))

    old_layout = tmp_path / "old"
    (old_layout / "game" / "bin").mkdir(parents=True)
    (old_layout / "game" / "bin" / "hammer.exe").write_bytes(b"")
    assert repair.repair_moved_build(old_layout) == "852_0"

    build_852_1 = tmp_path / "852_1"
    (build_852_1 / "bin").mkdir(parents=True)
    (build_852_1 / "bin" / "hammer.exe").write_bytes(b"")
    (build_852_1 / "bin" / "tier0.dll").write_bytes(b"852_1")
    build_852_2 = tmp_path / "852_2"
    (build_852_2 / "bin").mkdir(parents=True)
    (build_852_2 / "bin" / "hammer.exe").write_bytes(b"")
    (build_852_2 / "bin" / "tier0.dll").write_bytes(b"852_2")
    monkeypatch.setattr(
        repair,
        "sha256_file",
        lambda path: (
            repair.PATCHED_852_1_TIER0_SHA256
            if path.parent.parent.name == "852_1"
            else repair.PATCHED_852_2_TIER0_SHA256
        ),
    )

    assert repair.repair_moved_build(build_852_1) == "852_1"
    assert repair.repair_moved_build(build_852_2) == "852_2"
    assert [build for build, _root in calls] == ["852_0", "852_1", "852_2"]


def test_hl2_assets_use_curated_compatibility_allowlist():
    assert Hl2AssetsPatch.asset_marker == "hl2-assets-curated-v2\n"
    assert Hl2Assets8410Patch.asset_marker == "841_0-hl2-assets-complete\n"
    assert len(HL2_ASSET_ALLOWLIST) == 312
    assert "models/brokenglass_piece.dx90.vtx" in HL2_ASSET_ALLOWLIST
    assert "models/brokenglass_piece.vtx" in HL2_ASSET_ALLOWLIST
    assert "materials/skybox/sky_urb01bk.vmt" in HL2_ASSET_ALLOWLIST
    for extension in ("vmt", "vtf"):
        relative = f"materials/particle/particle_ring_wave_12.{extension}"
        assert relative in HL2_ASSET_ALLOWLIST
        assert "portal2/" + relative in ASSET_HASHES
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
        "852_0.hl2_assets",
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
    assert archive_path().stat().st_size < 120_000
    assert len(ASSET_ARCHIVE_SHA256) == 64
    assert set(ASSET_HASHES) == {
        "portal/materials/props_animsign/signage_num00_frame.vmt",
        "portal/materials/props_animsign/signage_num00_frame.vtf",
        "portal2/materials/effects/huntertracer.vmt",
        "portal2/materials/effects/huntertracer.vtf",
        "portal2/particles/achievement.pcf",
        "portal2/materials/particle/particle_ring_wave_12.vmt",
        "portal2/materials/particle/particle_ring_wave_12.vtf",
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
