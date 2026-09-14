"""Raise the July 2009 FOV limit and its settings slider to 120."""
from hashlib import sha256
import re

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file
from patches.definitions import PatchDefinition


# File offsets also equal RVAs in these binaries.
EDITS = {
    # Redirect only the ConVar maximum load to the existing read-only 120.0.
    # The absolute operand keeps its existing PE relocation entry.
    "client": ((0x362DE0, bytes.fromhex("d9 05 38 9c 37 10"), bytes.fromhex("d9 05 10 2a 3a 10")),),
    "server": (
        (0x14A1FB, bytes.fromhex("83 f8 5a"), bytes.fromhex("83 f8 78")),
        (0x14A200, bytes.fromhex("b8 5a 00 00 00"), bytes.fromhex("b8 78 00 00 00")),
    ),
}


def fov_enabled(data: bytes, kind: str) -> bool:
    edits = EDITS[kind]
    if all(data[offset:offset + len(old)] == old for offset, old, _ in edits):
        return False
    if all(data[offset:offset + len(new)] == new for offset, _, new in edits):
        return True
    raise PatchError(f"Unknown or incomplete 852_0 {kind} FOV instructions")


def with_fov(data: bytes, kind: str, enabled: bool) -> bytes:
    fov_enabled(data, kind)
    result = bytearray(data)
    for offset, old, new in EDITS[kind]:
        result[offset:offset + len(old)] = new if enabled else old
    return bytes(result)


def normalized_hash(data: bytes, kind: str) -> str:
    """Ignore only complete recognized FOV edits when validating a DLL hash."""
    return sha256(with_fov(data, kind, False)).hexdigest()


def supported_hashes(kind: str) -> set[str]:
    # Import at call time: the turret fix shares the FOV validation helpers.
    from patches.build_852_0 import vscript_scope_fix as turret

    return {
        "client": {turret.ORIGINAL_CLIENT_SHA256, turret.INTERMEDIATE_CLIENT_SHA256, turret.PATCHED_CLIENT_SHA256},
        "server": {turret.ORIGINAL_SERVER_SHA256, turret.PATCHED_SERVER_SHA256},
    }[kind]


def patch_binary(data: bytes, kind: str) -> bytes:
    if normalized_hash(data, kind) not in supported_hashes(kind):
        raise PatchError(f"Refusing to patch unknown 852_0 {kind}.dll")
    return with_fov(data, kind, True)


def patch_slider(data: bytes) -> bytes:
    # Preserve all other controls, custom layout, encoding and line endings.
    blocks = list(re.finditer(rb'"FovSlider"\s*\{[^{}]*\}', data))
    if len(blocks) != 1:
        raise PatchError("Expected exactly one FovSlider control")
    block = blocks[0]
    body = block.group()
    for key, value in ((b"cvar_name", b"fov_desired"), (b"minvalue", b"75"), (b"allowoutofrange", b"0")):
        if re.findall(rb'"' + key + rb'"\s*"([^"\r\n]*)"', body) != [value]:
            raise PatchError("Unexpected FovSlider configuration")
    maximum = re.findall(rb'"maxvalue"\s*"([^"\r\n]*)"', body)
    if maximum not in ([b"90"], [b"120"]):
        raise PatchError("Unexpected FovSlider maximum")
    body = re.sub(rb'("maxvalue"\s*")90(")', rb'\g<1>120\2', body)
    return data[:block.start()] + body + data[block.end():]


class FovLimitPatch:
    id = "852_0.fov_limit"
    display_name = "Increase FOV limit to 120"
    description = "Raise the FOV limit from 90 to 120."

    def _plan(self, context: PatchContext):
        from patches.build_852_0.vscript_scope_fix import client_path, server_path

        client = client_path(context.root)
        server = server_path(context.root)
        slider = client.parent.parent / "resource" / "OptionsSubVideoAdvancedDlg.res"
        if not slider.is_file():
            raise PatchError("852_0 video settings resource is missing")
        result = []
        for path, kind in ((client, "client"), (server, "server"), (slider, None)):
            original = path.read_bytes()
            patched = patch_binary(original, kind) if kind else patch_slider(original)
            result.append((path, original, patched))
        return result

    def check(self, context: PatchContext) -> bool:
        return any(original != patched for _, original, patched in self._plan(context))

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        plan = self._plan(context)  # Validate every input before changing any file.
        for path, original, patched in plan:
            if original != patched:
                backup_file(path, path.name + ".before-fov120.bak", context)
        for index, (path, original, patched) in enumerate(plan, 1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            if path.read_bytes() != original:
                raise PatchError(f"{path.name} changed before the FOV patch could be applied")
            if original != patched:
                atomic_write(path, patched)
            progress(ProgressEvent(self.id, index, len(plan), f"Updated {path.name} FOV limit"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("FOV limit or settings slider failed verification")


DEFINITION = PatchDefinition(FovLimitPatch(), default_selected=False,
                             after=frozenset({"852_0.continuous_campaign"}))
