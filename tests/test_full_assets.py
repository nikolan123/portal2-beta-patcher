from pathlib import Path
import struct
from threading import Event
from unittest.mock import Mock
import zlib

import pytest

from existing_build import patch_existing_build
from models import BuildCancelled, BuildInputs, BuildReport, ExistingBuildInputs, PatchContext
from patches.base import PatchError
from patches.generic.full_assets import HL2_DEFINITION, TF2_DEFINITION, mount_content
from patches.registry import PROFILES
from patches.selection import resolve_selection, unavailable_reason
from steam import detect_team_fortress_2


@pytest.mark.parametrize('definition', [HL2_DEFINITION, TF2_DEFINITION])
@pytest.mark.parametrize('moved', [False, True])
@pytest.mark.parametrize('search_paths_key', [b'SearchPaths', b'"SearchPaths"'])
def test_full_copy_in_existing_build_unpacks_all_archives_and_keeps_beta(tmp_path, write_vpk, definition, moved, search_paths_key):
    patch = definition.implementation
    retail = tmp_path / 'retail'
    source = retail / patch.folder
    source.mkdir(parents=True)
    write_vpk(source / 'pak_dir.vpk', {
        'materials/keep.vmt': b'retail material',
        'materials/loosewins.vmt': b'packed material',
        'models/everything.mdl': b'model',
        'scripts/all.txt': b'script',
    }, split=True)
    write_vpk(source / 'sound_vo_english_dir.vpk', {'sound/vo/everything.wav': b'voice'})
    write_vpk(source / 'standalone.vpk', {'materials/standalone.vtf': b'texture'})
    (source / 'materials').mkdir()
    (source / 'materials/loosewins.vmt').write_bytes(b'loose override')
    (source / 'maps').mkdir()
    (source / 'maps/full.bsp').write_bytes(b'loose map')
    (source / 'gameinfo.txt').write_bytes(b'donor configuration')
    root = tmp_path / 'output'
    runtime = root / 'game' if moved else root
    (runtime / 'portal2').mkdir(parents=True)
    original = b'"GameInfo"\r\n{\r\n SearchPaths\r\n {\r\n  Game |gameinfo_path|.\r\n }\r\n}\r\n'
    original = original.replace(b'SearchPaths', search_paths_key)
    gameinfo = runtime / 'portal2/GameInfo.txt'
    gameinfo.write_bytes(original)
    destination = runtime / patch.folder
    (destination / 'materials').mkdir(parents=True)
    (destination / 'materials/keep.vmt').write_bytes(b'beta material')
    for folder in patch.folders[1:]:
        write_vpk(retail / folder / 'pak_dir.vpk', {'materials/episode.vmt': folder.encode()}, split=True)
        (retail / folder / 'maps').mkdir()
        (retail / folder / 'maps/episode.bsp').write_bytes(b'episode map')
        (runtime / folder / 'materials').mkdir(parents=True)
        (runtime / folder / 'materials/episode.vmt').write_bytes(b'existing episode material')
    source_argument = {'hl2_path' if patch.folder == 'hl2' else 'tf2_path': retail}
    inputs = ExistingBuildInputs(root, 852, 0, selected_patch_ids=(patch.id,), **source_argument)

    patch_existing_build(inputs, Mock(), Event())

    assert (destination / 'materials/keep.vmt').read_bytes() == b'beta material'
    assert (destination / 'materials/loosewins.vmt').read_bytes() == b'loose override'
    assert (destination / 'models/everything.mdl').read_bytes() == b'model'
    assert (destination / 'scripts/all.txt').read_bytes() == b'script'
    assert (destination / 'sound/vo/everything.wav').read_bytes() == b'voice'
    assert (destination / 'materials/standalone.vtf').read_bytes() == b'texture'
    assert (destination / 'maps/full.bsp').read_bytes() == b'loose map'
    assert (destination / 'gameinfo.txt').read_bytes() == b'donor configuration'
    assert not list(destination.glob('*.vpk'))
    assert gameinfo.read_bytes().index(b'|gameinfo_path|.') < gameinfo.read_bytes().index(patch.folder.encode())
    assert gameinfo.with_name(f'GameInfo.before-full-{patch.folder}.bak').read_bytes() == original
    for folder in patch.folders[1:]:
        assert (runtime / folder / 'maps/episode.bsp').read_bytes() == b'episode map'
        assert (runtime / folder / 'materials/episode.vmt').read_bytes() == b'existing episode material'
        assert mount_content(gameinfo.read_bytes(), folder) == gameinfo.read_bytes()
    # Reapplying fills missing files, without changing existing content or mounts.
    mounted = gameinfo.read_bytes()
    (destination / 'sound/vo/everything.wav').unlink()
    patch_existing_build(inputs, Mock(), Event())
    assert gameinfo.read_bytes() == mounted
    assert (destination / 'sound/vo/everything.wav').read_bytes() == b'voice'


@pytest.mark.parametrize('moved', [False, True])
def test_hl2_copy_adds_newly_installed_episodes_and_keeps_original_backup(tmp_path, write_vpk, moved):
    retail = tmp_path / 'retail'
    write_vpk(retail / 'hl2/pak_dir.vpk', {'materials/base.vmt': b'base'})
    root = tmp_path / 'output'
    runtime = root / 'game' if moved else root
    (runtime / 'portal2').mkdir(parents=True)
    original = b'GameInfo\n{\nSearchPaths\n{\nGame |gameinfo_path|.\n}\n}'
    gameinfo = runtime / 'portal2/GameInfo.txt'
    gameinfo.write_bytes(original)
    inputs = ExistingBuildInputs(root, 852, 0, selected_patch_ids=('full_hl2_assets',), hl2_path=retail)

    patch_existing_build(inputs, Mock(), Event())
    assert b'episodic' not in gameinfo.read_bytes()
    assert b'ep2' not in gameinfo.read_bytes()
    for folder in ('episodic', 'ep2'):
        write_vpk(retail / folder / 'episode_dir.vpk', {'sound/episode.wav': folder.encode()}, split=True)
        patch_existing_build(inputs, Mock(), Event())
        assert (runtime / folder / 'sound/episode.wav').read_bytes() == folder.encode()
        assert mount_content(gameinfo.read_bytes(), folder) == gameinfo.read_bytes()
    assert gameinfo.with_name('GameInfo.before-full-hl2.bak').read_bytes() == original


@pytest.mark.parametrize('definition', [HL2_DEFINITION, TF2_DEFINITION])
def test_full_copy_accepts_stale_retail_crc_metadata(tmp_path, write_vpk, definition):
    patch = definition.implementation
    retail = tmp_path / 'retail'
    archive = retail / patch.folder / 'voice_dir.vpk'
    payload = b'retail voice bytes'
    write_vpk(archive, {'sound/voice.wav': payload}, split=True)
    checksum = struct.pack('<I', zlib.crc32(payload))
    archive.write_bytes(archive.read_bytes().replace(checksum, b'\0' * 4, 1))
    root = tmp_path / 'output'
    (root / 'portal2').mkdir(parents=True)
    (root / 'portal2/GameInfo.txt').write_bytes(b'GameInfo\n{\nSearchPaths\n{\nGame |gameinfo_path|.\n}\n}')
    context = PatchContext(root, None, BuildReport(), Event())
    setattr(context, patch.source_attribute, retail)

    patch.apply(context, Mock())
    patch.verify(context)

    assert (root / patch.folder / 'sound/voice.wav').read_bytes() == payload


def test_full_copy_cancel_and_missing_vpk_segment_do_not_mount_or_copy(tmp_path, write_vpk):
    retail = tmp_path / 'retail'
    source = retail / 'hl2'
    write_vpk(source / 'pak_dir.vpk', {'materials/sample.vmt': b'material'}, split=True)
    root = tmp_path / 'output'
    (root / 'portal2').mkdir(parents=True)
    original = b'GameInfo\n{\nSearchPaths\n{\nGame |gameinfo_path|.\n}\n}'
    gameinfo = root / 'portal2/GameInfo.txt'
    gameinfo.write_bytes(original)
    cancel = Event()
    context = PatchContext(root, retail, BuildReport(), cancel)
    patch = HL2_DEFINITION.implementation
    cancel.set()
    with pytest.raises(BuildCancelled):
        patch.apply(context, Mock())
    cancel.clear()
    (source / 'pak_000.vpk').unlink()
    with pytest.raises(PatchError, match='Missing VPK segment'):
        patch.apply(context, Mock())
    assert gameinfo.read_bytes() == original
    assert not (root / 'hl2').exists()


def test_full_copies_are_optional_for_every_profile_and_ordered_after_hammer():
    for profile in PROFILES:
        for definition in (HL2_DEFINITION, TF2_DEFINITION):
            assert definition.id in profile.optional
            assert not definition.default_selected
        selection = resolve_selection(profile.all, profile)
        if '852_0.hammer' in selection.ids:
            assert selection.ids.index('852_0.hammer') < selection.ids.index(HL2_DEFINITION.id)
    assert 'Team Fortress 2' in unavailable_reason((TF2_DEFINITION.id,), set())
    assert not unavailable_reason((TF2_DEFINITION.id,), {'tf2'})


@pytest.mark.parametrize('data', [b'GameInfo\n{\nSearchPaths\n{\nGame hl2\n}\n}',
                                b'GameInfo\n{\nSearchPaths\n{\n"Game" "|gameinfo_path|..\\hl2"\n}\n}'])
def test_existing_mount_is_preserved(data):
    assert mount_content(data, 'hl2') == data


def test_tf2_detection_uses_steam_installation(tmp_path, monkeypatch):
    import steam
    retail = tmp_path / 'steamapps/common/Team Fortress 2'
    (retail / 'tf').mkdir(parents=True)
    (retail / 'tf/tf2_misc_dir.vpk').touch()
    (tmp_path / 'steamapps/appmanifest_440.acf').touch()
    monkeypatch.setattr(steam, 'steam_libraries', lambda: [tmp_path])
    assert detect_team_fortress_2() == retail


def test_full_tf2_copy_runs_through_normal_build_pipeline(tmp_path, write_vpk, monkeypatch):
    from hashlib import sha256
    import pipeline
    blob, dat = tmp_path / 'input.blob', tmp_path / 'input.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')
    monkeypatch.setattr(pipeline, 'BLOB_SHA256', sha256(b'blob').hexdigest())
    monkeypatch.setattr(pipeline, 'DAT_SHA256', sha256(b'dat').hexdigest())
    retail = tmp_path / 'TF2'
    write_vpk(retail / 'tf/tf2_misc_dir.vpk', {'models/test.mdl': b'model'})

    def extract(blob, dat, staging, emit, cancel):
        (staging / 'portal2').mkdir(parents=True)
        (staging / 'portal2/GameInfo.txt').write_bytes(b'GameInfo\n{\nSearchPaths\n{\nGame |gameinfo_path|.\n}\n}')
        (staging / 'hl2.exe').write_bytes(b'game')
        return {}

    monkeypatch.setattr(pipeline, 'extract_depot', extract)
    output = tmp_path / 'output'
    inputs = BuildInputs(blob, dat, None, output, (TF2_DEFINITION.id,), tf2_path=retail)
    pipeline.BuildPipeline(Mock(), Event()).run(inputs)
    assert (output / 'tf/models/test.mdl').read_bytes() == b'model'
    assert b'|gameinfo_path|..\\tf' in (output / 'portal2/GameInfo.txt').read_bytes()


def test_omitted_selection_does_not_enable_full_copies(tmp_path, monkeypatch):
    import pipeline
    from models import RevisionInput
    from patches.registry import BY_ID
    monkeypatch.setattr(pipeline, 'DEFINITIONS', (BY_ID['multicore'], HL2_DEFINITION, TF2_DEFINITION))
    blob, dat = tmp_path / 'input.blob', tmp_path / 'input.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')

    def extract(chain, staging, *args):
        staging.mkdir()
        (staging / 'hl2.exe').write_bytes(b'game')
        (staging / 'portal2').mkdir()
        (staging / 'portal2/GameInfo.txt').write_bytes(b'GameInfo {}')
        return {}

    monkeypatch.setattr(pipeline, 'extract_revision_chain', extract)
    output = tmp_path / 'output'
    revision = RevisionInput(999, 0, 123, blob, dat)
    inputs = BuildInputs(blob, dat, None, output, mode='generic', depot_id=999, depot_version=0,
                         revision_chain=(revision,))
    pipeline.BuildPipeline(Mock(), Event()).run(inputs)
    assert (output / 'portal2/cfg/patcher_multicore.cfg').is_file()
    assert not (output / 'hl2').exists()
    assert not (output / 'tf').exists()
