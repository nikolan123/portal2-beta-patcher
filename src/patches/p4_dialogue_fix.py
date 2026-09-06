"""
Patch 4: Fix GLaDOS dialogue
This patch adds a script to the game that fixes GLaDOS dialogue
"""
from __future__ import annotations

import hashlib

from models import PatchContext, ProgressCallback
from patches.base import PatchError, atomic_write, backup_file


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

ORIGINAL_SCENE_CANCEL = b'''\
\t\t//Cancel any vcd that's already playing
\t\tlocal curscene = self.GetCurrentScene()
\t\tif ( curscene != null )
\t\t{
\t\t\t//printl("===================Cancelling!")
\t\t\tEntFireByHandle( curscene, "Cancel", "", 0, null, null )
\t\t}
'''

PATCHED_SCENE_CANCEL = b'''\
\t\t// A new block can be requested while an older VCD is still queued to
\t\t// start. GetCurrentScene() cannot see those queued scenes, so cancel
\t\t// every scene handle before scheduling the new block.
\t\tif (dingon)
\t\t{
\t\t\tforeach (sceneName, sceneData in SceneTable)
\t\t\t{
\t\t\t\tif ("vcd" in sceneData)
\t\t\t\t\tEntFireByHandle(sceneData.vcd, "Cancel", "", 0, null, null)
\t\t\t}
\t\t\twaiting = 0
\t\t\twaitNext = null
\t\t\twaitLength = null
\t\t}
\t\telse
\t\t{
\t\t\tlocal curscene = self.GetCurrentScene()
\t\t\tif (curscene != null)
\t\t\t\tEntFireByHandle(curscene, "Cancel", "", 0, null, null)
\t\t}
'''


def patch_glados_script(data: bytes) -> bytes:
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    original_block = ORIGINAL_SCENE_CANCEL.replace(b"\n", newline)
    patched_block = PATCHED_SCENE_CANCEL.replace(b"\n", newline)
    if patched_block in data:
        return data
    if data.count(original_block) != 1:
        raise PatchError("glados.nut does not contain the expected dialogue playback code")
    return data.replace(original_block, patched_block, 1)


def glados_script_is_patched(data: bytes) -> bool:
    return PATCHED_SCENE_CANCEL in data.replace(b"\r\n", b"\n")

class DialogueFixPatch:
    id = "p4"
    display_name = "GLaDOS dialogue"
    description = "Create the missing GLaDOS actor and prevent overlapping single-player dialogue."

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "scripts" / "vscripts" / "mapspawn.nut"

    def _glados_path(self, context: PatchContext):
        return context.root / "portal2" / "scripts" / "vscripts" / "choreo" / "glados.nut"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        glados = self._glados_path(context)
        return (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256
            or not glados.is_file()
            or not glados_script_is_patched(glados.read_bytes())
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != SCRIPT:
            backup = path.with_name("mapspawn.original.bak")
            if not backup.exists():
                backup.write_bytes(path.read_bytes())
                context.report.backups.append(str(backup.relative_to(context.root)))
        atomic_write(path, SCRIPT)

        glados = self._glados_path(context)
        if not glados.is_file():
            raise PatchError(f"Missing dialogue script: {glados}")
        original = glados.read_bytes()
        patched = patch_glados_script(original)
        if patched != original:
            backup_file(glados, "glados.original.bak", context)
            atomic_write(glados, patched)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("GLaDOS dialogue fix verification failed")
