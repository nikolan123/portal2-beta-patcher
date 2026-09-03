from __future__ import annotations

from patches.p1_hl2_assets import Hl2AssetsPatch
from patches.p2_search_paths import SearchPathsPatch
from patches.p3_sound_manifest import SoundManifestPatch
from patches.p4_dialogue_fix import DialogueFixPatch
from patches.p5_thread_fix import ThreadFixPatch
from patches.p6_launchers import LaunchersPatch
from patches.p7_hammer import HammerPatch
from patches.p8_prerelease_assets import PrereleaseAssetsPatch


PATCHES = [
    Hl2AssetsPatch(),
    SearchPathsPatch(),
    SoundManifestPatch(),
    DialogueFixPatch(),
    ThreadFixPatch(),
    LaunchersPatch(),
    HammerPatch(),
    PrereleaseAssetsPatch(),
]

PATCH_DEPENDENCIES = {
    "p3": {"p1"},
}

REQUIRED_PATCH_IDS = {"p2", "p6"}


def normalize_patch_ids(selected_ids) -> tuple[str, ...]:
    """Add required patches and return IDs in execution order."""
    selected = set(selected_ids) | REQUIRED_PATCH_IDS
    changed = True
    while changed:
        changed = False
        for patch_id in tuple(selected):
            dependencies = PATCH_DEPENDENCIES.get(patch_id, set())
            if not dependencies.issubset(selected):
                selected.update(dependencies)
                changed = True
    return tuple(patch.id for patch in PATCHES if patch.id in selected)
