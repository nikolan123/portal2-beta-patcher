import json
from pathlib import Path
from threading import Event

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
