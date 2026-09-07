"""Pure selection rules shared by the UI, pipeline, and catalog validation."""
from patches.definitions import ChoiceGroup, ResolvedSelection


def ordered_definitions(definitions):
    remaining = list(definitions)
    selected = {item.id for item in remaining}
    result = []
    done = set()
    while remaining:
        for index, item in enumerate(remaining):
            if ((item.dependencies | item.after) & selected) <= done:
                result.append(remaining.pop(index))
                done.add(item.id)
                break
        else:
            raise ValueError('Patch ordering cycle: ' + ', '.join(item.id for item in remaining))
    return tuple(result)


def validate_registry(definitions, profiles):
    by_id = {item.id: item for item in definitions}
    if len(by_id) != len(definitions):
        raise ValueError('Duplicate patch IDs')
    targets = set()
    profile_ids = set()
    for item in definitions:
        if item.requirements - {'hl2', 'portal2', 'goldberg_archive'}:
            raise ValueError(f'Unknown input requirement for {item.id}')
        if item.capabilities - {'provides_hl2_exe'}:
            raise ValueError(f'Unknown capability for {item.id}')
        if any(source.origin not in {'selected_chain', 'catalog'} for source in item.sources):
            raise ValueError(f'Unknown source origin for {item.id}')
        missing = (item.dependencies | item.after) - by_id.keys()
        if missing:
            raise ValueError(f'Unknown patch references for {item.id}: {sorted(missing)}')
    ordered_definitions(definitions)
    for profile in profiles:
        if profile.target in targets or profile.id in profile_ids:
            raise ValueError(f'Duplicate build profile: {profile.id}')
        targets.add(profile.target)
        profile_ids.add(profile.id)
        if profile.optional & profile.required:
            raise ValueError(f'Optional and required patches overlap: {profile.id}')
        if profile.all - by_id.keys():
            raise ValueError(f'Unknown patches in profile: {profile.id}')
        for patch_id in profile.all:
            if not by_id[patch_id].dependencies <= profile.all:
                raise ValueError(f'Incompatible dependencies: {profile.id}: {patch_id}')
        grouped = set()
        for group in profile.groups:
            if not group.patch_ids or not set(group.patch_ids) <= profile.optional:
                raise ValueError(f'Invalid choice group: {profile.id}')
            if grouped & set(group.patch_ids):
                raise ValueError(f'Duplicate choice group members: {profile.id}')
            grouped.update(group.patch_ids)


def resolve_selection(selected_ids, profile, *, runnable=True, definitions=None):
    if definitions is None:
        from patches.registry import DEFINITIONS
        definitions = DEFINITIONS
    by_id = {item.id: item for item in definitions}
    selected = set(selected_ids)
    if selected - by_id.keys():
        raise ValueError(f'Unknown patch IDs: {", ".join(sorted(selected - by_id.keys()))}')
    selected &= profile.all
    if runnable:
        selected.update(profile.required)
    pending = list(selected)
    while pending:
        patch_id = pending.pop()
        if patch_id not in by_id:
            raise ValueError(f'Unknown patch ID: {patch_id}')
        dependencies = by_id[patch_id].dependencies
        if not dependencies <= profile.all:
            raise ValueError(f'Incompatible dependencies for {patch_id} in {profile.id}')
        pending.extend(dependencies - selected)
        selected.update(dependencies)
    return ResolvedSelection(profile, ordered_definitions(tuple(item for item in definitions if item.id in selected)))


def compatible_patch_ids(mode, depot_id=None, depot_version=None, depot_crc=None):
    from patches.compatibility import patch_set_for_target
    from patches.registry import DEFINITIONS
    profile = patch_set_for_target(mode, depot_id, depot_version, depot_crc)
    return tuple(item.id for item in DEFINITIONS if item.id in profile.all)


def selectable_patch_ids(mode, depot_id=None, depot_version=None, depot_crc=None):
    from patches.compatibility import patch_set_for_target
    from patches.registry import DEFINITIONS
    profile = patch_set_for_target(mode, depot_id, depot_version, depot_crc)
    return tuple(item.id for item in DEFINITIONS if item.id in profile.optional)


def normalize_patch_ids(selected_ids, mode='852_0', runnable=True,
                        depot_id=None, depot_version=None, depot_crc=None):
    from patches.compatibility import patch_set_for_target
    return resolve_selection(selected_ids, patch_set_for_target(mode, depot_id, depot_version, depot_crc), runnable=runnable).ids


def selected_metadata(patch_ids):
    from patches.registry import BY_ID
    return tuple(BY_ID[patch_id] for patch_id in patch_ids)


def requirements_for(patch_ids):
    return frozenset(value for item in selected_metadata(patch_ids) for value in item.requirements)


def capabilities_for(patch_ids):
    return frozenset(value for item in selected_metadata(patch_ids) for value in item.capabilities)


def choices_for(profile):
    from patches.registry import DEFINITIONS
    groups = {patch_id: group for group in profile.groups for patch_id in group.patch_ids}
    seen = set()
    result = []
    for item in DEFINITIONS:
        if item.id not in profile.optional or item.id in seen:
            continue
        group = groups.get(item.id, ChoiceGroup((item.id,), item.title, item.description))
        seen.update(group.patch_ids)
        result.append(group)
    return tuple(result)


def unavailable_reason(patch_ids, available_inputs):
    labels = {'hl2': 'a Half-Life 2 folder', 'portal2': 'a retail Portal 2 folder'}
    missing = requirements_for(patch_ids) - set(available_inputs)
    # Archive controls remain enabled so the user can supply the required ZIP.
    return ' '.join(f'Unavailable because no {labels[value]} was selected.' for value in sorted(missing) if value in labels)


def resolve_source_chains(patch_ids, selected_chain, catalog_targets):
    requirements = tuple(dict.fromkeys(source for item in selected_metadata(patch_ids) for source in item.sources))
    result = []
    for requirement in requirements:
        candidates = (selected_chain,) if requirement.origin == 'selected_chain' else tuple(target.chain for target in catalog_targets if target.ready)
        matches = {}
        for chain in candidates:
            revisions = chain[:1] if requirement.origin == 'selected_chain' else chain[-1:]
            for index, revision in enumerate(revisions):
                if ((revision.depot_id, revision.version) == (requirement.depot_id, requirement.version)
                    and revision.blob_sha256 == requirement.blob_sha256
                    and revision.dat_sha256 == requirement.dat_sha256):
                    matched = chain[:index + 1] if requirement.origin == 'selected_chain' else chain
                    matches[tuple((entry.blob_path, entry.dat_path) for entry in matched)] = matched
        if len(matches) != 1:
            raise ValueError(f'Exactly one verified {requirement.label} archive chain is required. Supply its BLOB and DAT or disable the asset patch.')
        chain = next(iter(matches.values()))
        if chain not in result:
            result.append(chain)
    return tuple(result)


def validate_source_chains(patch_ids, chains):
    """Check supplied sources independently of the UI before extraction starts."""
    from patches.base import sha256_file
    for requirement in dict.fromkeys(source for item in selected_metadata(patch_ids) for source in item.sources):
        matches = {}
        for chain in chains:
            revisions = chain[:1] if requirement.origin == 'selected_chain' else chain[-1:]
            for revision in revisions:
                if ((revision.depot_id, revision.version) == (requirement.depot_id, requirement.version)
                    and revision.blob_sha256 == requirement.blob_sha256
                    and revision.dat_sha256 == requirement.dat_sha256):
                    matches[(revision.blob_path, revision.dat_path)] = revision
        if len(matches) != 1:
            raise ValueError(f'Exactly one verified {requirement.label} archive chain is required')
        revision = next(iter(matches.values()))
        if (sha256_file(revision.blob_path) != requirement.blob_sha256
            or sha256_file(revision.dat_path) != requirement.dat_sha256):
            raise ValueError(f'{requirement.label} archives failed SHA-256 verification')
