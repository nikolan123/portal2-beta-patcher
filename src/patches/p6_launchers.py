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


FIRST_RUN_AUDIO = r'''if exist "%ROOT%.p2patcher\patcher-audiocache.done" goto launch
if not exist "%ROOT%.p2patcher" mkdir "%ROOT%.p2patcher"
echo Rebuilding the audio cache for the first launch. The game will restart in a bit.
start "" /wait /D "%ROOT%" "%ROOT%%GAME%" -game portal2 -windowed -w 1366 -h 768 -console +snd_rebuildaudiocache +quit
if errorlevel 1 (
    echo Audio cache setup failed. Launch again to retry.
    pause
    exit /b 1
)
>"%ROOT%.p2patcher\patcher-audiocache.done" echo Audio cache setup exited successfully.

:launch
'''.replace("\n", "\r\n").encode("ascii")


def launcher(mode: str) -> bytes:
    if mode == "852_0":
        return LAUNCHER.replace(b'start "" /D', FIRST_RUN_AUDIO + b'start "" /D', 1)
    return LAUNCHER


class LaunchersPatch:
    id = "p6"
    display_name = "Launch files"
    description = "Create a launcher that sets the beta content paths and uses the thread fix when installed."

    def _path(self, context: PatchContext):
        return context.root / "Launch Portal 2.cmd"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        return not path.is_file() or path.read_bytes() != launcher(context.mode)

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        atomic_write(self._path(context), launcher(context.mode))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Launcher verification failed")
