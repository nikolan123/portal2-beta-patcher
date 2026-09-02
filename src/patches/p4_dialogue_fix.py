"""
Patch 4: Fix GLaDOS dialogue
This patch adds a script to the game that fixes GLaDOS dialogue
"""
from __future__ import annotations

import hashlib

from models import PatchContext, ProgressCallback
from patches.base import atomic_write


SCRIPT = b'''\
function fixlines()
{
    local existing = Entities.FindByName(null, "@glados")
    if (!existing)
    {
        local ent = Entities.CreateByClassname("generic_actor")
        ent.__KeyValueFromString("targetname", "@glados")
        ent.SetOrigin(Vector(16000, 16000, 16000))
    }
}

// The game crashes if the actor is created immediately.
EntFire("worldspawn", "CallScriptFunction", "fixlines", 1.0)
'''
EXPECTED_SHA256 = hashlib.sha256(SCRIPT).hexdigest()

class DialogueFixPatch:
    id = "p4"
    display_name = "GLaDOS dialogue"
    description = "Create the missing GLaDOS actor after map startup so her dialogue can play."

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "scripts" / "vscripts" / "mapspawn.nut"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        return not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != SCRIPT:
            backup = path.with_name("mapspawn.original.bak")
            if not backup.exists():
                backup.write_bytes(path.read_bytes())
                context.report.backups.append(str(backup.relative_to(context.root)))
        atomic_write(path, SCRIPT)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("GLaDOS dialogue fix verification failed")
