import json
from pathlib import Path
from threading import Event

import pytest

from models import BuildInputs, RevisionInput
from pipeline import BuildPipeline


def test_pipeline_reports_descriptive_ids_and_uses_profile(tmp_path, monkeypatch):
    import pipeline
    blob, dat = tmp_path / 'input.blob', tmp_path / 'input.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')
    output = tmp_path / 'output'
    revision = RevisionInput(999, 1, 123, blob, dat)

    def extract(chain, staging, *args):
        staging.mkdir()
        (staging / 'hl2.exe').write_bytes(b'game')
        return {}

    monkeypatch.setattr(pipeline, 'extract_revision_chain', extract)
    monkeypatch.setattr(pipeline, 'has_runnable_layout', lambda root: True)
    events = []
    inputs = BuildInputs(blob, dat, None, output, ('multicore',), mode='generic',
                         depot_id=999, depot_version=1, depot_crc=123, revision_chain=(revision,))
    BuildPipeline(events.append, Event()).run(inputs)
    report = json.loads((output / '.p2patcher/patcher-report.json').read_text())
    assert [patch['id'] for patch in report['patches']] == ['launchers', 'multicore']
    assert b'snd_rebuildaudiocache' not in (output / 'Launch Portal 2.cmd').read_bytes()
    assert any(event.phase == 'patches' and 'multicore' in event.message for event in events)


def test_unselected_launcher_capability_does_not_enable_content_only_build(tmp_path, monkeypatch):
    import pipeline
    blob, dat = tmp_path / 'input.blob', tmp_path / 'input.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')
    revision = RevisionInput(841, 0, 0x83CED978, blob, dat)
    output = tmp_path / 'output'

    def extract(chain, staging, *args):
        staging.mkdir()
        return {}

    monkeypatch.setattr(pipeline, 'extract_revision_chain', extract)
    monkeypatch.setattr(pipeline, 'has_runnable_layout', lambda root: False)
    inputs = BuildInputs(blob, dat, None, output, (), mode='generic', depot_id=841,
                         depot_version=0, depot_crc=revision.crc, revision_chain=(revision,))
    BuildPipeline(lambda event: None, Event()).run(inputs)
    report = json.loads((output / '.p2patcher/patcher-report.json').read_text())
    assert report['patches'] == []
    assert not (output / 'Launch Portal 2.cmd').exists()


@pytest.mark.parametrize('with_hammer', [False, True])
def test_normal_8520_pipeline_preserves_layout_and_final_paths(tmp_path, monkeypatch, with_hammer):
    from hashlib import sha256
    import pipeline
    from patches.build_852_0 import hammer
    from patches.generic.launchers import launcher

    blob, dat = tmp_path / 'input.blob', tmp_path / 'input.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')
    monkeypatch.setattr(pipeline, 'BLOB_SHA256', sha256(b'blob').hexdigest())
    monkeypatch.setattr(pipeline, 'DAT_SHA256', sha256(b'dat').hexdigest())
    original, patched = b'original tier0', b'patched tier0'
    monkeypatch.setattr(hammer, 'ORIGINAL_TIER0_SHA256', sha256(original).hexdigest())
    monkeypatch.setattr(hammer, 'PATCHED_TIER0_SHA256', sha256(patched).hexdigest())
    monkeypatch.setattr(hammer, 'patch_tier0', lambda data: patched)
    gameinfo = '"GameInfo"\n{\nSearchPaths\n{\nGame |gameinfo_path|.\n}\n}\n'
    staging_paths = []

    def extract(blob, dat, staging, emit, cancel):
        staging_paths.append(staging)
        for name in hammer.RUNTIME_DIRECTORIES:
            (staging / name).mkdir(parents=True)
            (staging / name / 'kept.txt').write_text(name)
        for name in hammer.RUNTIME_FILES:
            (staging / name).write_bytes(name.encode())
        (staging / 'portal2/GameInfo.txt').write_text(gameinfo)
        (staging / 'bin/tier0.dll').write_bytes(original)
        return {'fixture': True}

    monkeypatch.setattr(pipeline, 'extract_depot', extract)
    retail = tmp_path / 'retail'
    (retail / 'portal2').mkdir(parents=True)
    editor = retail / 'platform/materials/Editor'
    editor.mkdir(parents=True)
    for name in hammer.EDITOR_REQUIRED_FILES:
        (editor / name).write_text(name)
    output = tmp_path / 'output'
    selected = ('852_0.hammer',) if with_hammer else ()
    inputs = BuildInputs(blob, dat, None, output, selected, portal2_path=retail)
    assert BuildPipeline(lambda event: None, Event()).run(inputs) == output

    runtime = output / 'game' if with_hammer else output
    for name in hammer.RUNTIME_DIRECTORIES:
        assert (runtime / name / 'kept.txt').read_text() == name
    for name in hammer.RUNTIME_FILES:
        assert (runtime / name).read_bytes() == name.encode()
    assert 'portal2_tempcontent' in (runtime / 'portal2/GameInfo.txt').read_text()
    assert (output / 'Launch Portal 2.cmd').read_bytes() == launcher(True)
    assert (output / 'Settings.bat').is_file()
    assert (output / '.p2patcher/settings.ps1').is_file()
    assert all(not staging.exists() for staging in staging_paths)
    report = json.loads((output / '.p2patcher/patcher-report.json').read_text())
    expected = ['852_0.search_paths', 'launchers'] + list(selected)
    assert [item['id'] for item in report['patches']] == expected
    if with_hammer:
        assert (output / 'game/bin/GameConfig.txt').read_bytes() == hammer.game_config(output)
        assert (output / 'Launch Hammer.cmd').read_bytes() == hammer.hammer_launcher(output)
        assert (output / 'Launch HLMV.cmd').read_bytes() == hammer.hlmv_launcher(output)
        assert (output / 'game/bin/tier0.original.bak').read_bytes() == original
        assert (output / 'game/bin/tier0.dll').read_bytes() == patched
        assert all(not (output / name).exists() for name in hammer.RUNTIME_DIRECTORIES)
        assert not (output / 'game/game').exists()
    else:
        assert not (output / 'game').exists()
        assert not (output / 'Launch Hammer.cmd').exists()
        assert (output / 'bin/tier0.dll').read_bytes() == original
