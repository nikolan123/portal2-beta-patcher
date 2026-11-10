"""Use the Spacewar app ID for 852_0 matchmaking."""
from __future__ import annotations

import re
from pathlib import Path

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file
from patches.definitions import PatchDefinition


APP_IDS = (b"852", b"480")
APP_ID_LINE = re.compile(rb"(?im)^(appID[ \t]*=[ \t]*)(852|480)([ \t]*\r?)$")


def runtime_root(root: Path) -> Path:
    candidates = [
        path for path in (root, root / "game")
        if (path / "portal2" / "GameInfo.txt").is_file()
        and ((path / "hl2.exe").is_file() or (path / "portal2.exe").is_file())
    ]
    if len(candidates) != 1:
        raise PatchError("Expected exactly one 852_0 game directory")
    return candidates[0]


def patch_appid(data: bytes) -> bytes:
    # The original file ends in NUL.
    terminator = b"\0" if data.endswith(b"\0") else b"\r\n" if data.endswith(b"\r\n") else b"\n" if data.endswith(b"\n") else b""
    value = data[:len(data) - len(terminator)] if terminator else data
    if value not in APP_IDS:
        raise PatchError("Unexpected 852_0 steam_appid.txt contents")
    return b"480" + terminator


def patch_steam_inf(data: bytes) -> bytes:
    matches = list(APP_ID_LINE.finditer(data))
    if len(matches) != 1:
        raise PatchError("Expected one appID=852 or appID=480 in portal/steam.inf")
    match = matches[0]
    return data[:match.start(2)] + b"480" + data[match.end(2):]


class Matchmaking8520Patch:
    id = "852_0.matchmaking"
    display_name = "Steam matchmaking"
    description = "Enable Steam matchmaking by changing app id to 480."

    def _plan(self, context: PatchContext) -> list[tuple[Path, bytes | None, bytes]]:
        root = runtime_root(context.root)
        paths = (
            (root / "steam_appid.txt", patch_appid),
            (root / "portal" / "steam.inf", patch_steam_inf),
        )
        plan = []
        for path, transform in paths:
            if path.name == "steam_appid.txt" and not path.exists():
                plan.append((path, None, b"480\n"))
                continue
            if not path.is_file():
                raise PatchError(f"Required 852_0 matchmaking file is missing: {path}")
            original = path.read_bytes()
            plan.append((path, original, transform(original)))
        return plan

    def check(self, context: PatchContext) -> bool:
        return any(original != patched for _, original, patched in self._plan(context))

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        plan = self._plan(context)  # Validate both files before touching either.
        for path, original, patched in plan:
            if original is not None and original != patched:
                backup_file(path, path.name + ".before-matchmaking.bak", context)
        for index, (path, original, patched) in enumerate(plan, 1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Matchmaking patch cancelled")
            current = path.read_bytes() if path.exists() else None
            if current != original:
                raise PatchError(f"{path} changed during matchmaking patch")
            if original != patched:
                atomic_write(path, patched)
            progress(ProgressEvent(self.id, index, len(plan), f"Updated {path.name}"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("852_0 Steam app ID update failed verification")


DEFINITION = PatchDefinition(Matchmaking8520Patch(), default_selected=False)
