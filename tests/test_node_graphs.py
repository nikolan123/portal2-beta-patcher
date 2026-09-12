import struct
from threading import Event
from zipfile import ZipFile

import pytest

from models import BuildReport, PatchContext
from patches.registry import BY_ID, PROFILES
from patches.resources import resource_path


@pytest.mark.parametrize('patch_id,count', [('852_0.node_graphs', 54), ('841_0_prereset.node_graphs', 171)])
@pytest.mark.parametrize('layout', ['', 'game'])
def test_generated_graphs_install_and_skip_different_revisions(tmp_path, patch_id, count, layout):
    definition = BY_ID[patch_id]
    patch = definition.implementation
    maps = tmp_path / layout / 'portal2' / 'maps'
    maps.mkdir(parents=True)
    with ZipFile(resource_path(definition.resources[0])) as archive:
        entries = [(name, archive.read(name)) for name in archive.namelist()]
    assert len(entries) == count
    for index, (name, data) in enumerate(entries):
        if index == 0:
            continue  # A missing BSP should not receive a graph.
        header = bytearray(1036)
        header[:4] = b'VBSP'
        revision = struct.unpack_from('<i', data, 4)[0]
        struct.pack_into('<i', header, 1032, revision + (index == 1))
        (maps / (name[:-4] + '.bsp')).write_bytes(header)
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    assert patch.check(context)
    patch.apply(context, lambda event: None)
    patch.verify(context)
    assert not patch.check(context)
    for index, (name, data) in enumerate(entries):
        path = maps / 'graphs' / name
        if index < 2:
            assert not path.exists()
        else:
            assert path.read_bytes() == data
    patch.apply(context, lambda event: None)
    assert context.report.backups == []


def test_graphs_only_optional_for_their_exact_profiles():
    for profile in PROFILES:
        for patch_id, profile_id in [('852_0.node_graphs', '852_0'),
                                     ('841_0_prereset.node_graphs', '841_0_prereset')]:
            assert (patch_id in profile.optional) == (profile.id == profile_id)
            assert patch_id not in profile.required
