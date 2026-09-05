from __future__ import annotations

from dataclasses import dataclass

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
from patches.p11_legacy_paint import LegacyPaintPatch
from patches.p12_july_2010_assets import July2010AssetsPatch
from patches.p13_july_2009_assets import July2009AssetsPatch
from patches.p14_march_assets import MarchAssetsPatch


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
    LegacyPaintPatch(),
    July2010AssetsPatch(),
    July2009AssetsPatch(),
    MarchAssetsPatch(),
]

PATCH_DEPENDENCIES = {
    "p3": {"p1"},
}

@dataclass(frozen=True)
class BuildPatchSet:
    optional: frozenset[str]
    required: frozenset[str]

    @property
    def all(self) -> frozenset[str]:
        return self.optional | self.required


PATCH_COMPATIBILITY = {
    "generic": BuildPatchSet(
        optional=frozenset({"p5", "p9", "p10"}), # thread fix, multicore rendering, goldberg
        required=frozenset({"p6"}), # launcher
    ),
    (852, 0): BuildPatchSet(
        optional=frozenset({"p1", "p3", "p4", "p5", "p7", "p8", "p10"}), # hl2 assets, sound manifest, dialogue, thread fix, hammer, extra assets, goldberg
        required=frozenset({"p2", "p6"}), # search paths, launcher
    ),
    (852, 1): BuildPatchSet(
        optional=frozenset({"p5", "p10", "p11", "p12", "p13", "p14"}), # thread fix, goldberg, paint fix, jul 2010 assets, jul 2009 assets, extra assets
        required=frozenset({"p6"}), # launcher
    ),
}


def build_target(mode: str, depot_id: int | None, depot_version: int | None) -> tuple[int, int]:
    if mode == "852_0":
        return (852, 0)
    if mode != "generic":
        raise ValueError(f"Unknown build mode: {mode}")
    if depot_id is None or depot_version is None:
        raise ValueError("Generic patch selection requires a depot ID and version")
    return (depot_id, depot_version)


def compatible_patch_ids(
    mode: str,
    depot_id: int | None = None,
    depot_version: int | None = None,
) -> tuple[str, ...]:
    target = build_target(mode, depot_id, depot_version)
    patch_set = PATCH_COMPATIBILITY.get(target, PATCH_COMPATIBILITY["generic"])
    return tuple(
        patch.id for patch in PATCHES
        if patch.id in patch_set.all
    )


def selectable_patch_ids(
    mode: str,
    depot_id: int | None = None,
    depot_version: int | None = None,
) -> tuple[str, ...]:
    target = build_target(mode, depot_id, depot_version)
    optional = PATCH_COMPATIBILITY.get(target, PATCH_COMPATIBILITY["generic"]).optional
    return tuple(patch.id for patch in PATCHES if patch.id in optional)


def normalize_patch_ids(
    selected_ids,
    mode: str = "852_0",
    runnable: bool = True,
    depot_id: int | None = None,
    depot_version: int | None = None,
) -> tuple[str, ...]:
    """Add required patches and return IDs in execution order."""
    target = build_target(mode, depot_id, depot_version)
    patch_set = PATCH_COMPATIBILITY.get(target, PATCH_COMPATIBILITY["generic"])
    selected = set(selected_ids) & patch_set.all
    if runnable:
        selected.update(patch_set.required)
    changed = True
    while changed:
        changed = False
        for patch_id in tuple(selected):
            dependencies = PATCH_DEPENDENCIES.get(patch_id, set())
            if not dependencies.issubset(selected):
                selected.update(dependencies)
                changed = True
    return tuple(patch.id for patch in PATCHES if patch.id in selected)
