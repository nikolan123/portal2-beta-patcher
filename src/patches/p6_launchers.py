"""
Patch 6: Add launcher
This patch adds launcher script to the game's directory
"""
from __future__ import annotations

from models import PatchContext, ProgressCallback
from patches.base import atomic_write


LAUNCHER = r'''@echo off
setlocal
set "ROOT=%~dp0"
set "VGame=%ROOT%"
set "VContent=%ROOT%"
set "GAME=hl2.exe"
if exist "%ROOT%hl2.wrap.exe" set "GAME=hl2.wrap.exe"
set "MULTICORE="
if exist "%ROOT%portal2\cfg\patcher_multicore.cfg" set "MULTICORE=+exec patcher_multicore.cfg"

start "" /D "%ROOT%" "%ROOT%%GAME%" -game portal2 -windowed -w 1366 -h 768 -console %MULTICORE% %*
endlocal
'''.replace("\n", "\r\n").encode("ascii")


class LaunchersPatch:
    id = "p6"
    display_name = "Launch files"
    description = "Create a launcher that sets the beta content paths and uses the thread fix when installed."

    def _path(self, context: PatchContext):
        return context.root / "Launch Portal 2.cmd"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        return not path.is_file() or path.read_bytes() != LAUNCHER

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        atomic_write(self._path(context), LAUNCHER)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Launcher verification failed")
