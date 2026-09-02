"""
Patch 3: Repair sound manifest so portal 2 loads the correct files
"""
from __future__ import annotations

from models import PatchContext, ProgressCallback
from patches.base import atomic_write, backup_file


HL2_SOUND_SCRIPTS = (
    "game_sounds_weapons.txt",
    "game_sounds_world.txt",
    "game_sounds_ambient_generic.txt",
    "game_sounds_items.txt",
    "game_sounds_physics.txt",
    "game_sounds_vehicles.txt",
    "level_sounds_e3_c17.txt",
    "level_sounds_e3_town.txt",
    "level_sounds_e3_bugbait.txt",
    "level_sounds_eli_lab.txt",
    "level_sounds_trainyard.txt",
    "level_sounds_k_lab.txt",
    "level_sounds_k_lab2.txt",
    "level_sounds_coast.txt",
    "level_sounds_novaprospekt.txt",
    "level_sounds_streetwar.txt",
    "level_sounds_streetwar2.txt",
    "level_sounds_breencast.txt",
    "level_sounds_citadel.txt",
    "level_sounds_canals.txt",
    "level_sounds_ravenholm.txt",
    "level_sounds_ravenholm2.txt",
    "level_sounds_canals2.txt",
    "level_sounds_music.txt",
    "npc_sounds_eli.txt",
    "npc_sounds_alyx.txt",
    "npc_sounds_dog.txt",
    "npc_sounds_citizen.txt",
    "npc_sounds_barney.txt",
    "npc_sounds_soldier.txt",
    "npc_sounds_strider.txt",
    "npc_sounds_zombie.txt",
    "npc_sounds_vortigaunt.txt",
    "npc_sounds_turret.txt",
    "npc_sounds_scanner.txt",
    "npc_sounds_rollermine.txt",
    "npc_sounds_poisonzombie.txt",
    "npc_sounds_metropolice.txt",
    "npc_sounds_combinecamera.txt",
    "npc_sounds_manhack.txt",
    "npc_sounds_ichthyosaur.txt",
    "npc_sounds_blackheadcrab.txt",
    "npc_sounds_fastheadcrab.txt",
    "npc_sounds_headcrab.txt",
    "npc_sounds_fastzombie.txt",
    "npc_sounds_birds.txt",
    "npc_sounds_gunship.txt",
    "npc_sounds_dropship.txt",
    "npc_sounds_barnacle.txt",
    "npc_sounds_attackheli.txt",
    "npc_sounds_antlionguard.txt",
    "npc_sounds_antlion.txt",
    "npc_sounds_env_headcrabcanister.txt",
    "npc_sounds_combine_ball.txt",
    "npc_sounds_combine_mine.txt",
    "npc_sounds_sniper.txt",
    "npc_sounds_stalker.txt",
    "npc_sounds_gman.txt",
)


class SoundManifestPatch:
    id = "p3"
    display_name = "Sound manifest"
    description = "Register the missing Half-Life 2 sound scripts so maps can precache and play their sounds."

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "scripts" / "game_sounds_manifest.txt"

    def check(self, context: PatchContext) -> bool:
        text = self._path(context).read_text(encoding="utf-8", errors="replace").casefold()
        return any(f'"scripts/{name}"'.casefold() not in text for name in HL2_SOUND_SCRIPTS)

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        backup_file(path, "game_sounds_manifest.original.bak", context)
        text = path.read_text(encoding="utf-8", errors="strict")
        closing = text.rfind("}")
        if closing < 0:
            raise RuntimeError("Sound manifest has no closing brace")
        folded = text.casefold()
        additions = [
            f'\t"precache_file"\t\t"scripts/{name}"'
            for name in HL2_SOUND_SCRIPTS
            if f'"scripts/{name}"'.casefold() not in folded
        ]
        if additions:
            text = text[:closing].rstrip() + "\n\n\t// Restored Half-Life 2 sound scripts\n" + "\n".join(additions) + "\n" + text[closing:]
        atomic_write(path, text.encode("utf-8"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Sound manifest is missing restored HL2 entries")
