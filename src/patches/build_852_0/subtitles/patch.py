"""
Install English subtitles and the fixes needed to display them correctly.

- Subtitles:
  - Installs closecaption_english.txt and its compiled closecaption_english.dat (tools/compile_subtitles.py) database.
  - Installs patcher_subtitles.cfg with scene_maxcaptionradius 0 so GLaDOS scene captions display even though the dialogue actor is outside the map.
- Aquarium Core:
  - Replaces game_sounds_spheres_auto_generated.txt with the original 852_0 file modified only by changing sphere02.NOTHELD, sphere02.HELD, and sphere02.PAIN to volume 0 and CHAN_AUTO. These random sound groups cannot identify which WAV they selected, so we play them ourselves in aquarium_core.nut, and moving the muted events off CHAN_VOICE prevents them from cutting off those replacement lines.
  - Installs aquarium_core.nut and launches it in p2_lab_slowfield_1 and p2_lab_hub_2. The script finds brain_core_sphere_0, connects to its pickup, drop, damage, and punt outputs, activates nearby chatter using the first map's existing trigger_once volumes, and resumes held chatter after the transition into the second map.
- Curiosity Core:
  - Installs curiosity_core.nut and launches it only in p2_lab_lasers_1.
  - Redirects three Curiosity Core sounds through their existing Portal sound events so their captions display reliably.
- Map startup:
  - Appends the Aquarium and Curiosity script launches to portal2/scripts/vscripts/mapspawn.nut while preserving the dialogue patch's existing contents.
  - Depends on 852_0.dialogue and also declares that it runs after it because the dialogue patch creates mapspawn.nut first.

To contribute subtitles, edit closecaption_english.txt and compile with compile_subtitles.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from models import PatchContext, ProgressCallback, ProgressEvent
from patches.base import atomic_write, backup_file
from patches.definitions import PatchDefinition, Resource
from patches.resources import resource_path


PACKAGE = "build_852_0/subtitles"
FILES = {
    "closecaption_english.txt": "portal2/resource/closecaption_english.txt",
    "closecaption_english.dat": "portal2/resource/closecaption_english.dat",
    "patcher_subtitles.cfg": "portal2/cfg/patcher_subtitles.cfg",
    "game_sounds_spheres_auto_generated.txt": "portal2/scripts/game_sounds_spheres_auto_generated.txt",
    "aquarium_core.nut": "portal2/scripts/vscripts/subtitle_fixes/aquarium_core.nut",
    "curiosity_core.nut": "portal2/scripts/vscripts/subtitle_fixes/curiosity_core.nut",
}

MAPSPAWN_BLOCK = b'''\
// Portal 2 beta subtitle fixes
if (GetMapName() == "p2_lab_slowfield_1" || GetMapName() == "p2_lab_hub_2")
{
    EntFire("worldspawn", "RunScriptFile", "subtitle_fixes/aquarium_core.nut", 0.1)
}

if (GetMapName() == "p2_lab_lasers_1")
{
    EntFire("worldspawn", "RunScriptFile", "subtitle_fixes/curiosity_core.nut", 0.1)
}
'''

def bundled_path(name: str) -> Path:
    return resource_path(Resource(PACKAGE, name))


def destination_path(context: PatchContext, name: str) -> Path:
    return context.root / FILES[name]


def mapspawn_has_subtitle_fixes(data: bytes) -> bool:
    normalized = data.replace(b"\r\n", b"\n")
    return MAPSPAWN_BLOCK in normalized


def patch_mapspawn(data: bytes) -> bytes:
    if mapspawn_has_subtitle_fixes(data):
        return data
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    block = MAPSPAWN_BLOCK.replace(b"\n", newline)
    if not data:
        return block
    return data.rstrip() + newline * 2 + block


class Subtitles8520Patch:
    id = "852_0.subtitles"
    display_name = "Experimental English subtitles"
    description = "Add English subtitles and fixes required for them"

    def _mapspawn_path(self, context: PatchContext) -> Path:
        return context.root / "portal2" / "scripts" / "vscripts" / "mapspawn.nut"

    def check(self, context: PatchContext) -> bool:
        for name in FILES:
            destination = destination_path(context, name)
            if not destination.is_file():
                return True
            if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(bundled_path(name).read_bytes()).digest():
                return True
        mapspawn = self._mapspawn_path(context)
        return not mapspawn.is_file() or not mapspawn_has_subtitle_fixes(mapspawn.read_bytes())

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        total = len(FILES) + 1
        for index, name in enumerate(FILES, 1):
            source = bundled_path(name).read_bytes()
            destination = destination_path(context, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.is_file() or destination.read_bytes() != source:
                if destination.is_file():
                    backup_file(destination, destination.name + ".before-subtitles.bak", context)
                atomic_write(destination, source)
            progress(ProgressEvent(self.id, index, total, f"Installing {destination.name}"))

        mapspawn = self._mapspawn_path(context)
        mapspawn.parent.mkdir(parents=True, exist_ok=True)
        original = mapspawn.read_bytes() if mapspawn.is_file() else b""
        patched = patch_mapspawn(original)
        if patched != original:
            if mapspawn.is_file():
                backup_file(mapspawn, "mapspawn.before-subtitles.bak", context)
            atomic_write(mapspawn, patched)
        progress(ProgressEvent(self.id, total, total, "Installed subtitle map fixes"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("English subtitle patch verification failed")


DEFINITION = PatchDefinition(
    Subtitles8520Patch(),
    dependencies=frozenset({"852_0.dialogue"}),
    after=frozenset({"852_0.dialogue"}),
    resources=tuple(Resource(PACKAGE, name) for name in FILES),
)
