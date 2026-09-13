"""Experimental, explicit-only patching of an installed build."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from models import BuildCancelled, BuildReport, PatchContext, ProgressEvent
from patches import patch_set_for_target, resolve_selection
from steam import validate_hl2, validate_portal_2


def existing_profile(depot_id, version, crc=None):
    profile = patch_set_for_target('generic', depot_id, version, crc)
    return replace(profile, optional=profile.all, required=frozenset(), groups=())


def resolve_existing_sources(selection, folder):
    from extractor import scan_archive_catalog
    if not selection.sources:
        return ()
    if folder is None:
        raise ValueError('Select the source archive folder for the checked asset fixes.')
    targets = scan_archive_catalog(folder.expanduser().resolve())
    result = []
    for source in selection.sources:
        matches = {}
        for target in targets:
            if not target.ready:
                continue
            chain = target.chain[:1] if source.origin == 'selected_chain' else target.chain
            if not chain:
                continue
            revision = chain[-1]
            if ((revision.depot_id, revision.version, revision.blob_sha256, revision.dat_sha256)
                == (source.depot_id, source.version, source.blob_sha256, source.dat_sha256)):
                matches[tuple((r.blob_path, r.dat_path) for r in chain)] = chain
        if len(matches) != 1:
            raise ValueError(f'Exactly one verified {source.label} archive chain is required in the source archive folder.')
        chain = next(iter(matches.values()))
        if chain not in result:
            result.append(chain)
    return tuple(result)


def runtime_root(folder: Path) -> Path:
    root = folder.expanduser().resolve()
    candidates = [root, root / 'game']
    valid = [candidate for candidate in candidates
             if (candidate / 'portal2' / 'gameinfo.txt').is_file()]
    if len(valid) != 1:
        raise ValueError('Select a build folder containing portal2/GameInfo.txt or game/portal2/GameInfo.txt (one layout only).')
    return valid[0]


def patch_existing_build(inputs, emit, cancel_event):
    root = inputs.output_path.expanduser().resolve()
    runtime_root(root)
    profile = existing_profile(inputs.depot_id, inputs.depot_version, inputs.depot_crc)
    if set(inputs.selected_patch_ids) - profile.all:
        raise ValueError('Selected patches are incompatible with this build version.')
    selection = resolve_selection(inputs.selected_patch_ids, profile, runnable=False)
    if not selection.ids:
        raise ValueError('Select at least one fix. Nothing is selected automatically.')
    from patches.selection import validate_source_chains
    chains = (resolve_existing_sources(selection, inputs.archive_folder)
              if inputs.archive_folder is not None else inputs.supplemental_revision_chains)
    validate_source_chains(selection.ids, chains)
    goldberg = None
    if 'goldberg_archive' in selection.requirements:
        if inputs.goldberg_archive_path is None:
            raise ValueError('Select the Goldberg ZIP to use.')
        goldberg = inputs.goldberg_archive_path.expanduser().resolve()
        if not goldberg.is_file():
            raise ValueError(f'Goldberg ZIP does not exist: {goldberg}')
    sources = {}
    for requirement, path, validate in (
        ('hl2', inputs.hl2_path, validate_hl2),
        ('portal2', inputs.portal2_path, validate_portal_2),
    ):
        if requirement in selection.requirements:
            if path is None:
                raise ValueError(f'A {requirement} installation folder is required.')
            sources[requirement] = validate(path)
    report = BuildReport(warnings=['Experimental: may not work. Changes were made in place.'])
    # Runtime patches expect portal2 directly below their root. Layout management
    # and the main launcher operate on the enclosing build instead.
    for index, item in enumerate(selection.definitions):
        if cancel_event.is_set():
            raise BuildCancelled('Patching cancelled; earlier changes remain in place.')
        patch_root = root if item.id in {'launchers', '852_0.hammer'} else runtime_root(root)
        context = PatchContext(patch_root, sources.get('hl2'), report, cancel_event,
                               sources.get('portal2'), patch_root, goldberg,
                               supplemental_revision_chains=chains,
                               mode='852_0' if profile.id == '852_0' else 'generic', profile=profile)
        patch = item.implementation
        emit(ProgressEvent('patches', index, len(selection.ids), f'{item.id}: {item.title}'))
        needed = patch.check(context)
        if needed:
            patch.apply(context, emit)
        patch.verify(context)
        report.patches.append({'id': item.id, 'name': item.title,
                               'status': 'applied' if needed else 'already_applied'})
    metadata = root / '.p2patcher'
    metadata.mkdir(exist_ok=True)
    data = asdict(report)
    data.update(output=str(root), completed_at=datetime.now(timezone.utc).isoformat(),
                operation='patch_existing', build=profile.id,
                target=[inputs.depot_id, inputs.depot_version, inputs.depot_crc])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    (metadata / f'existing-build-report-{stamp}.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    emit(ProgressEvent('complete', 1, 1, 'Selected fixes finished'))
    return root
