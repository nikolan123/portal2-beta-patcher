from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest
from models import BuildCancelled, BuildReport, PatchContext
from patches.base import PatchError
from patches.build_841_0_prereset.water import patch as water
from patches import compatible_patch_ids


def test_water_changes_only_two_bytes():
    original = bytearray(0x188221)
    for offset, before, _ in water.CHANGES:
        original[offset] = before
    result = water.patch_client(bytes(original))
    assert [i for i, (a, b) in enumerate(zip(original, result)) if a != b] == [0x1881E6, 0x188220]
    with pytest.raises(PatchError):
        water.patch_client(b'unknown')


@pytest.mark.parametrize('moved', [False, True])
def test_water_apply_backup_verify_and_idempotence(tmp_path, monkeypatch, moved):
    root = tmp_path / 'game' if moved else tmp_path
    client = root / 'portal2/bin/client.dll'
    material = root / 'portal2/materials/nature/toxicslime002a.vmt'
    client.parent.mkdir(parents=True)
    material.parent.mkdir(parents=True)
    original = bytearray(0x188221)
    for offset, before, _ in water.CHANGES:
        original[offset] = before
    original = bytes(original)
    patched = water.patch_client(original)
    monkeypatch.setattr(water, 'ORIGINAL_CLIENT_SHA256', sha256(original).hexdigest())
    monkeypatch.setattr(water, 'PATCHED_CLIENT_SHA256', sha256(patched).hexdigest())
    client.write_bytes(original)
    stock_material = b'"Water"\n{\n\t"$normalmap" "liquids/water_river_normal_sharp"\n\t$flowmap "liquids/c3m2_hflowmap_a"\n}\n'
    material.write_bytes(stock_material)
    context = PatchContext(tmp_path, None, BuildReport(), Event())
    patch = water.Water8410Patch()
    assert patch.check(context)
    patch.apply(context, lambda _: None)
    patch.verify(context)
    assert client.read_bytes() == patched
    assert client.with_name('client.original.bak').read_bytes() == original
    assert material.with_name('toxicslime002a.original.bak').read_bytes() == stock_material
    assert material.read_bytes() == water.patch_material(stock_material)
    assert not patch.check(context)
    patch.apply(context, lambda _: None)
    context.cancel_event.set()
    with pytest.raises(BuildCancelled):
        patch.apply(context, lambda _: None)


def test_water_rejects_unknown_dll(tmp_path):
    client = tmp_path / 'portal2/bin/client.dll'
    client.parent.mkdir(parents=True)
    client.write_bytes(b'unknown')
    with pytest.raises(PatchError, match='unknown client.dll'):
        water.Water8410Patch().check(PatchContext(tmp_path, None, BuildReport(), Event()))


def test_water_target_and_real_dll():
    assert water.Water8410Patch.id in compatible_patch_ids('generic', 841, 0, 0x83CED978)
    assert water.Water8410Patch.id not in compatible_patch_ids('generic', 852, 0)
    source = Path(r'C:\Users\Niko\Downloads\841_0_fixed\portal2\bin\client.dll.before-water-test.bak')
    if source.is_file():
        original = source.read_bytes()
        assert sha256(original).hexdigest() == water.ORIGINAL_CLIENT_SHA256
        assert sha256(water.patch_client(original)).hexdigest() == water.PATCHED_CLIENT_SHA256


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_material_edits_preserve_unrelated_text_and_line_endings(newline):
    stock = newline.join([b'// keep comment', b'"Water"', b'{', b'\t"$normalmap" "old"', b'\t$flowmap "old_flow"', b'\t$refractamount 0.25', b'\t"$unrelated" "keep"', b'}', b''])
    result = water.patch_material(stock)
    assert b'// keep comment' in result
    assert b'"$unrelated" "keep"' in result
    assert b'$flowmap' not in result
    assert b'$refractamount' not in result
    assert b'"$normalmap" "Nature/slime_normal"' in result
    assert water.patch_material(result) == result
    assert not water.DEFINITION.resources
    if newline == b'\r\n':
        assert b'\n' not in result.replace(b'\r\n', b'')


def test_material_rejects_unsupported_nested_overrides():
    with pytest.raises(PatchError):
        water.patch_material(b'"Water" { "Proxies" { "Other" {} } }')


def test_stock_material_edits_match_working_repack_settings_when_available():
    original = Path(r'C:\Users\Niko\Downloads\841_0_fixed\portal2\materials\nature\toxicslime002a.vmt.before-water-test.bak')
    repack = Path(r'C:\Users\Niko\Downloads\_portal2_4107_compare\Portal_2\game\portal2_tempcontent\materials\nature\toxicslime002a.vmt')
    if not original.is_file() or not repack.is_file():
        pytest.skip('Local materials not available')
    import re
    def settings(data):
        text = re.sub(r'//[^\n]*', '', data.decode()).replace('\r', '')
        return dict(re.findall(r'^\s*"([\$%][\w]+)"\s+("[^"\n]*"|[^\s]+)', text, re.M))
    actual = settings(water.patch_material(original.read_bytes()))
    expected = settings(repack.read_bytes())
    assert {key: value.strip('"') for key, value in actual.items()} == {key: value.strip('"') for key, value in expected.items()}
