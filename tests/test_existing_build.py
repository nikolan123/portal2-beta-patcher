from dataclasses import replace
import json
from threading import Event
from unittest.mock import Mock

import pytest

from existing_build import existing_profile, patch_existing_build, runtime_root
from models import BuildCancelled, ExistingBuildInputs
from patches import resolve_selection
from patches.registry import BY_ID


def build(tmp_path, nested=False):
    runtime = tmp_path / 'game' if nested else tmp_path
    (runtime / 'portal2').mkdir(parents=True)
    (runtime / 'portal2' / 'GameInfo.txt').write_text('original')
    return runtime


@pytest.mark.parametrize('nested', [False, True])
def test_only_explicit_patch_changes_existing_runtime(tmp_path, nested):
    runtime = build(tmp_path, nested)
    inputs = ExistingBuildInputs(tmp_path, 852, 2, selected_patch_ids=('multicore',))
    assert patch_existing_build(inputs, Mock(), Event()) == tmp_path.resolve()
    assert (runtime / 'portal2/cfg/patcher_multicore.cfg').read_bytes() == b'mat_queue_mode 0\r\n'
    assert (runtime / 'portal2/GameInfo.txt').read_text() == 'original'
    assert not (tmp_path / 'Launch Portal 2.cmd').exists()
    reports = list((tmp_path / '.p2patcher').glob('existing-build-report-*.json'))
    assert [p['id'] for p in json.loads(reports[0].read_text())['patches']] == ['multicore']
    patch_existing_build(inputs, Mock(), Event())
    assert len(list((tmp_path / '.p2patcher').glob('existing-build-report-*.json'))) == 2


@pytest.mark.parametrize('selected', [(), ('goldberg',), ('852_1.extra_assets.from_july_2010',), ('852_0.dialogue',), ('unknown',)])
def test_invalid_or_archive_selection_does_not_modify_build(tmp_path, selected):
    build(tmp_path)
    before = set(tmp_path.rglob('*'))
    with pytest.raises(ValueError):
        patch_existing_build(ExistingBuildInputs(tmp_path, 852, 1, selected_patch_ids=selected), Mock(), Event())
    assert set(tmp_path.rglob('*')) == before


def test_dependencies_run_without_profile_defaults(tmp_path, monkeypatch):
    build(tmp_path, True)
    ids = ('852_0.dialogue', '852_0.subtitles')
    applied = []
    for patch_id in ids:
        patch = BY_ID[patch_id].implementation
        monkeypatch.setattr(patch, 'check', lambda context: True)
        monkeypatch.setattr(patch, 'apply', lambda context, emit, id=patch_id: applied.append((id, context.root)))
        monkeypatch.setattr(patch, 'verify', lambda context: None)
    patch_existing_build(ExistingBuildInputs(tmp_path, 852, 0, selected_patch_ids=(ids[1],)), Mock(), Event())
    assert applied == [(id, tmp_path / 'game') for id in ids]
    assert not (tmp_path / 'Launch Portal 2.cmd').exists()


def test_goldberg_archive_reaches_patch(tmp_path, monkeypatch):
    build(tmp_path)
    archive = tmp_path / 'goldberg.zip'
    archive.write_bytes(b'test archive')
    patch = BY_ID['goldberg'].implementation
    contexts = []
    monkeypatch.setattr(patch, 'check', lambda context: True)
    monkeypatch.setattr(patch, 'apply', lambda context, emit: contexts.append(context))
    monkeypatch.setattr(patch, 'verify', lambda context: None)
    patch_existing_build(ExistingBuildInputs(tmp_path, 852, 1, selected_patch_ids=('goldberg',),
                         goldberg_archive_path=archive), Mock(), Event())
    assert contexts[0].goldberg_archive == archive


def test_no_implicit_required_patches():
    profile = existing_profile(852, 0)
    assert resolve_selection((), profile).ids == ()
    assert 'launchers' in profile.optional
    assert '852_0.search_paths' in profile.optional


def test_cancel_keeps_existing_files(tmp_path):
    build(tmp_path)
    cancel = Event()
    cancel.set()
    with pytest.raises(BuildCancelled):
        patch_existing_build(ExistingBuildInputs(tmp_path, 852, 2, selected_patch_ids=('multicore',)), Mock(), cancel)
    assert (tmp_path / 'portal2/GameInfo.txt').read_text() == 'original'
    assert not (tmp_path / '.p2patcher').exists()


def test_invalid_and_ambiguous_layout(tmp_path):
    with pytest.raises(ValueError):
        runtime_root(tmp_path)
    build(tmp_path)
    build(tmp_path, True)
    with pytest.raises(ValueError):
        runtime_root(tmp_path)


def test_source_archives_are_resolved_and_passed_to_patch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from models import RevisionInput
    from existing_build import resolve_existing_sources
    import extractor
    import patches.selection
    build(tmp_path)
    patch_id = '852_1.extra_assets.from_july_2010'
    definition = BY_ID[patch_id]
    source = definition.sources[0]
    revision = RevisionInput(source.depot_id, source.version, 0, tmp_path / 'source.blob',
                             tmp_path / 'source.dat', source.blob_sha256, source.dat_sha256)
    chain = (revision,)
    monkeypatch.setattr(extractor, 'scan_archive_catalog', lambda folder: [SimpleNamespace(ready=True, chain=chain)])
    selection = resolve_selection((patch_id,), existing_profile(852, 1), runnable=False)
    assert resolve_existing_sources(selection, tmp_path) == (chain,)
    validate = Mock()
    monkeypatch.setattr(patches.selection, 'validate_source_chains', validate)
    contexts = []
    patch = definition.implementation
    monkeypatch.setattr(patch, 'check', lambda context: True)
    monkeypatch.setattr(patch, 'apply', lambda context, emit: contexts.append(context))
    monkeypatch.setattr(patch, 'verify', lambda context: None)
    patch_existing_build(ExistingBuildInputs(tmp_path, 852, 1, selected_patch_ids=(patch_id,),
                         archive_folder=tmp_path), Mock(), Event())
    validate.assert_called_once_with((patch_id,), (chain,))
    assert contexts[0].supplemental_revision_chains == (chain,)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('tier0_already_patched', [False, True])
def test_hammer_repairs_existing_layout(tmp_path, monkeypatch, nested, tier0_already_patched):
    from hashlib import sha256
    from patches.build_852_0 import hammer
    root = tmp_path / 'build'
    runtime = build(root, nested)
    for name in hammer.RUNTIME_DIRECTORIES:
        (runtime / name).mkdir(exist_ok=True)
        (runtime / name / 'kept.txt').write_text(name)
    (runtime / 'hl2.exe').write_bytes(b'launcher')
    original, patched = b'original tier0', b'patched tier0'
    (runtime / 'bin/tier0.dll').write_bytes(patched if tier0_already_patched else original)
    monkeypatch.setattr(hammer, 'ORIGINAL_TIER0_SHA256', sha256(original).hexdigest())
    monkeypatch.setattr(hammer, 'PATCHED_TIER0_SHA256', sha256(patched).hexdigest())
    monkeypatch.setattr(hammer, 'patch_tier0', lambda data: patched)
    retail = tmp_path / 'retail'
    (retail / 'portal2').mkdir(parents=True)
    editor = retail / 'platform/materials/Editor'
    editor.mkdir(parents=True)
    for name in hammer.EDITOR_REQUIRED_FILES:
        (editor / name).write_text(name)
    inputs = ExistingBuildInputs(root, 852, 0, selected_patch_ids=('852_0.hammer',), portal2_path=retail)

    patch_existing_build(inputs, Mock(), Event())

    assert (root / 'game/bin/GameConfig.txt').read_bytes() == hammer.game_config(root)
    assert (root / 'Launch Hammer.cmd').read_bytes() == hammer.hammer_launcher(root)
    assert (root / 'Launch HLMV.cmd').read_bytes() == hammer.hlmv_launcher(root)
    assert (root / 'game/bin/tier0.dll').read_bytes() == patched
    assert (root / 'game/hl2.exe').read_bytes() == b'launcher'
    for name in hammer.RUNTIME_DIRECTORIES:
        assert (root / 'game' / name / 'kept.txt').read_text() == name
        assert not (root / name).exists()
    assert not (root / 'game/game').exists()
    assert not (root / 'Launch Portal 2.cmd').exists()
    # A completed nested build remains safe to run through the patch again.
    patch_existing_build(inputs, Mock(), Event())
    reports = [json.loads(path.read_text()) for path in (root / '.p2patcher').glob('existing-build-report-*.json')]
    assert sorted(report['patches'][0]['status'] for report in reports) == ['already_applied', 'applied']


@pytest.mark.parametrize('invalid', ['missing_nested', 'duplicate', 'missing_flat'])
def test_hammer_rejects_invalid_layout_before_moving_files(tmp_path, invalid):
    from patches.build_852_0.hammer import RUNTIME_DIRECTORIES, move_runtime_into_game
    from patches.base import PatchError
    runtime = tmp_path if invalid == 'missing_flat' else tmp_path / 'game'
    for name in RUNTIME_DIRECTORIES:
        (runtime / name).mkdir(parents=True)
        (runtime / name / 'kept.txt').write_text(name)
    if invalid == 'duplicate':
        (tmp_path / 'bin').mkdir()
    else:
        missing = runtime / RUNTIME_DIRECTORIES[-1]
        (missing / 'kept.txt').unlink()
        missing.rmdir()
    before = {p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None for p in tmp_path.rglob('*')}
    with pytest.raises(PatchError):
        move_runtime_into_game(tmp_path)
    assert {p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None for p in tmp_path.rglob('*')} == before
