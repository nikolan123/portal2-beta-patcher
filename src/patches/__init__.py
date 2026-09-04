from __future__ import annotations

from patches.p1_hl2_assets import Hl2AssetsPatch
from patches.p2_search_paths import SearchPathsPatch
from patches.p3_sound_manifest import SoundManifestPatch
from patches.p4_dialogue_fix import DialogueFixPatch
from patches.p5_thread_fix import ThreadFixPatch
from patches.p6_launchers import LaunchersPatch
from patches.p7_hammer import HammerPatch
from patches.p8_prerelease_assets import PrereleaseAssetsPatch
from patches.p9_multicore import MulticorePatch
from patches.p10_goldberg import GoldbergPatch


PATCHES = [
    Hl2AssetsPatch(),
    SearchPathsPatch(),
    SoundManifestPatch(),
    DialogueFixPatch(),
    ThreadFixPatch(),
    LaunchersPatch(),
    HammerPatch(),
    PrereleaseAssetsPatch(),
    MulticorePatch(),
    GoldbergPatch(),
]

PATCH_DEPENDENCIES = {
    "p3": {"p1"},
}

PATCH_MODES = {
    "p1": frozenset({"852_0"}),
    "p2": frozenset({"852_0"}),
    "p3": frozenset({"852_0"}),
    "p4": frozenset({"852_0"}),
    "p5": frozenset({"852_0", "generic"}),
    "p6": frozenset({"852_0", "generic"}),
    "p7": frozenset({"852_0"}),
    "p8": frozenset({"852_0"}),
    "p9": frozenset({"generic"}),
    "p10": frozenset({"852_0", "generic"}),
}


def normalize_patch_ids(selected_ids, mode: str = "852_0", runnable: bool = True) -> tuple[str, ...]:
    """Add required patches and return IDs in execution order."""
    if mode not in {"852_0", "generic"}:
        raise ValueError(f"Unknown build mode: {mode}")
    compatible = {patch_id for patch_id, modes in PATCH_MODES.items() if mode in modes}
    selected = set(selected_ids) & compatible
    if mode == "852_0":
        selected.update({"p2", "p6"})
    elif runnable:
        selected.add("p6")
    changed = True
    while changed:
        changed = False
        for patch_id in tuple(selected):
            dependencies = PATCH_DEPENDENCIES.get(patch_id, set())
            if not dependencies.issubset(selected):
                selected.update(dependencies)
                changed = True
    return tuple(patch.id for patch in PATCHES if patch.id in selected)
