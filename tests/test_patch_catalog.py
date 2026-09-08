from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from models import RevisionInput
from patches import BY_ID, DEFINITIONS, PROFILES, normalize_patch_ids, patch_set_for_target
from patches.definitions import BuildProfile, PatchDefinition, Resource, SourceRequirement
from patches.resources import packaging_data, resource_path
from patches.selection import (
    capabilities_for, choices_for, ordered_definitions, resolve_selection,
    resolve_source_chains, unavailable_reason, validate_registry, validate_source_chains,
)


def definition(name, **kwargs):
    return PatchDefinition(SimpleNamespace(id=name, display_name=name, description=name), **kwargs)


def test_registry_rejects_invalid_references_and_cycles():
    a = definition('a')
    with pytest.raises(ValueError, match='Duplicate patch'):
        validate_registry((a, a), ())
    with pytest.raises(ValueError, match='Unknown patch references'):
        validate_registry((replace(a, after=frozenset({'missing'})),), ())
    with pytest.raises(ValueError, match='cycle'):
        validate_registry((replace(a, after=frozenset({'b'})), definition('b', after=frozenset({'a'}))), ())
    with pytest.raises(ValueError, match='Unknown patches'):
        validate_registry((a,), (BuildProfile('test', (1, 1), frozenset({'missing'}), frozenset()),))
    with pytest.raises(ValueError, match='Incompatible dependencies'):
        validate_registry((a, definition('b', dependencies=frozenset({'a'}))),
                          (BuildProfile('test', (1, 1), frozenset({'b'}), frozenset()),))


def test_ordering_is_stable_and_does_not_select_optional_predecessors():
    definitions = (definition('b', after=frozenset({'a'})), definition('c'), definition('a'))
    assert tuple(item.id for item in ordered_definitions(definitions)) == ('c', 'a', 'b')
    profile = BuildProfile('test', (1, 1), frozenset({'a', 'b', 'c'}), frozenset())
    assert resolve_selection(('b',), profile, definitions=definitions).ids == ('b',)


def test_subtitle_dependency_is_included_and_ordered_with_reversed_registry():
    profile = patch_set_for_target('852_0', None, None, None)
    selection = resolve_selection(('852_0.subtitles',), profile,
                                  definitions=tuple(reversed(DEFINITIONS)))
    assert '852_0.dialogue' in selection.ids
    assert selection.ids.index('852_0.dialogue') < selection.ids.index('852_0.subtitles')
    assert BY_ID['852_0.subtitles'].after == frozenset({'852_0.dialogue'})
    omitted = tuple(item for item in selection.ids if item != '852_0.dialogue')
    assert '852_0.dialogue' in resolve_selection(omitted, profile).ids


def test_shared_patch_support_is_explicit():
    shared = definition('subtitles')
    definitions = DEFINITIONS + (shared,)
    profiles = tuple(replace(profile, optional=profile.optional | {'subtitles'})
                     if profile.id in {'852_0', '852_1'} else profile for profile in PROFILES)
    validate_registry(definitions, profiles)
    for profile in profiles:
        selection = resolve_selection(('subtitles',), profile, runnable=False, definitions=definitions)
        assert ('subtitles' in selection.ids) == (profile.id in {'852_0', '852_1'})


def test_crc_fallback_and_old_id_rejection():
    assert patch_set_for_target('generic', 841, 0, 0x83CED978).id == '841_0_prereset'
    assert patch_set_for_target('generic', 841, 0, 123).id == 'generic'
    assert patch_set_for_target('generic', 841, 0, None).id == 'generic'
    for number in range(1, 19):
        with pytest.raises(ValueError, match='Unknown patch IDs'):
            normalize_patch_ids('p' + str(number) for _ in range(1))


def test_choices_defaults_requirements_and_selected_capabilities():
    profile = patch_set_for_target('852_0', None, None, None)
    group = choices_for(profile)[0]
    assert group.patch_ids == ('852_0.hl2_assets', '852_0.sound_manifest')
    assert unavailable_reason(group.patch_ids, ())
    assert not unavailable_reason(group.patch_ids, {'hl2'})
    assert not BY_ID['goldberg'].default_selected
    assert all(item.default_selected for item in DEFINITIONS if item.id != 'goldberg')
    assert 'provides_hl2_exe' not in capabilities_for(())
    assert 'provides_hl2_exe' in capabilities_for(('841_0_prereset.missing_launcher',))


def test_source_resolution_and_independent_hash_validation(tmp_path, monkeypatch):
    blob, dat = tmp_path / 'source.blob', tmp_path / 'source.dat'
    blob.write_bytes(b'blob')
    dat.write_bytes(b'dat')
    requirement = SourceRequirement(852, 0, sha256(b'blob').hexdigest(), sha256(b'dat').hexdigest(), 'selected_chain', 'test source')
    patch = definition('test_source', sources=(requirement,))
    monkeypatch.setitem(BY_ID, patch.id, patch)
    revision = RevisionInput(852, 0, 1, blob, dat, requirement.blob_sha256, requirement.dat_sha256)
    chain = (revision,)
    assert resolve_source_chains((patch.id,), chain, ()) == (chain,)
    validate_source_chains((patch.id,), (chain,))
    with pytest.raises(ValueError, match='Exactly one'):
        resolve_source_chains((patch.id,), (), ())
    monkeypatch.setitem(BY_ID, patch.id, replace(patch, sources=(replace(requirement, origin='catalog'),)))
    assert resolve_source_chains((patch.id,), (), (SimpleNamespace(ready=True, chain=chain),)) == (chain,)
    duplicate = replace(revision, blob_path=tmp_path / 'another.blob')
    with pytest.raises(ValueError, match='Exactly one'):
        resolve_source_chains((patch.id,), (), (SimpleNamespace(ready=True, chain=chain), SimpleNamespace(ready=True, chain=(duplicate,))))
    dat.write_bytes(b'damaged')
    with pytest.raises(ValueError, match='SHA-256'):
        validate_source_chains((patch.id,), (chain,))


def test_resources_are_independent_of_cwd_and_support_packaging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resource_path(Resource('build_852_0/hl2_assets', 'assets.txt')).is_file()
    resource = Resource('build_test/feature', 'native.dll', native=True)
    package_root = tmp_path / 'bundle' / 'patches'
    native = tmp_path / 'build/native/build_test/feature/native.dll'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'native')
    assert resource_path(resource, package_root=package_root, repository_root=tmp_path) == native
    bundled = package_root / resource.package / resource.name
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b'bundled')
    assert resource_path(resource, package_root=package_root, repository_root=tmp_path) == bundled
    with pytest.raises(FileNotFoundError, match='Missing required'):
        packaging_data((definition('missing', resources=(Resource('missing', 'missing.bin'),)),))


def test_launcher_configuration_comes_from_profile():
    from patches.generic.launchers import launcher
    assert b'snd_rebuildaudiocache' in launcher(True)
    assert b'snd_rebuildaudiocache' not in launcher(False)
