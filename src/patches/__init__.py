from __future__ import annotations

from patches.p1_hl2_assets import Hl2AssetsPatch
from patches.p2_search_paths import SearchPathsPatch
from patches.p3_sound_manifest import SoundManifestPatch
from patches.p4_dialogue_fix import DialogueFixPatch
from patches.p5_thread_fix import ThreadFixPatch
from patches.p6_launchers import LaunchersPatch


PATCHES = [
    Hl2AssetsPatch(),
    SearchPathsPatch(),
    SoundManifestPatch(),
    DialogueFixPatch(),
    ThreadFixPatch(),
    LaunchersPatch(),
]

