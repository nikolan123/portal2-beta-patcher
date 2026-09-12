"""
Add launcher
This patch adds launcher script to the game's directory
"""
from __future__ import annotations

from models import PatchContext, ProgressCallback
from patches.base import atomic_write
from patches.definitions import PatchDefinition
from patches.generic.settings_ui import SETTINGS_SCRIPT


LAUNCHER = r'''@echo off
setlocal
set "ROOT=%~dp0"
set "GAMEROOT=%ROOT%"
if exist "%ROOT%game\hl2.exe" set "GAMEROOT=%ROOT%game\"
if exist "%ROOT%game\portal2.exe" set "GAMEROOT=%ROOT%game\"
set "VGame=%GAMEROOT%"
set "VContent=%ROOT%content\"
set "GAME=hl2.exe"
if not exist "%GAMEROOT%hl2.exe" if exist "%GAMEROOT%portal2.exe" set "GAME=portal2.exe"
if exist "%GAMEROOT%hl2.exe" if exist "%GAMEROOT%hl2.wrap.exe" set "GAME=hl2.wrap.exe"
set "MULTICORE="
if exist "%GAMEROOT%portal2\cfg\patcher_multicore.cfg" set "MULTICORE=+exec patcher_multicore.cfg"
set "SUBTITLES="
if exist "%GAMEROOT%portal2\cfg\patcher_subtitles.cfg" set "SUBTITLES=+exec patcher_subtitles.cfg"
set "WIDTH=1366"
set "HEIGHT=768"
set "DISPLAY_MODE=-windowed"
set "DEBUG_ARGS="
set "CUSTOM_ARGS="
if exist "%ROOT%.p2patcher\resolution.txt" for /f "usebackq tokens=1,2" %%A in ("%ROOT%.p2patcher\resolution.txt") do (
    set "WIDTH=%%A"
    set "HEIGHT=%%B"
)
if exist "%ROOT%.p2patcher\display-mode.txt" set /p "DISPLAY_MODE="<"%ROOT%.p2patcher\display-mode.txt"
if exist "%ROOT%.p2patcher\debug-mode.txt" set /p "DEBUG_ARGS="<"%ROOT%.p2patcher\debug-mode.txt"
if exist "%ROOT%.p2patcher\launch-arguments.txt" set /p "CUSTOM_ARGS="<"%ROOT%.p2patcher\launch-arguments.txt"

start "" /D "%GAMEROOT%" "%GAMEROOT%%GAME%" -game portal2 %DISPLAY_MODE% -w %WIDTH% -h %HEIGHT% -console %DEBUG_ARGS% %MULTICORE% %SUBTITLES% %CUSTOM_ARGS% %*
endlocal
'''.replace("\n", "\r\n").encode("ascii")


SETTINGS_LAUNCHER = r'''@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0.p2patcher\settings.ps1" -Root "%~dp0."
if errorlevel 1 (
    echo.
    echo Portal 2 Beta settings failed to start.
    echo The PowerShell error is shown above.
    pause
)
endlocal
'''.replace("\n", "\r\n").encode("ascii")


FIRST_RUN_AUDIO = r'''if exist "%ROOT%.p2patcher\patcher-audiocache.done" goto launch
if not exist "%ROOT%.p2patcher" mkdir "%ROOT%.p2patcher"
echo Rebuilding the audio cache for the first launch. The game will restart in a bit.
start "" /wait /D "%GAMEROOT%" "%GAMEROOT%%GAME%" -game portal2 %DISPLAY_MODE% -w %WIDTH% -h %HEIGHT% -console -novid +snd_rebuildaudiocache +quit
if errorlevel 1 (
    echo Audio cache setup failed. Launch again to retry.
    pause
    exit /b 1
)
>"%ROOT%.p2patcher\patcher-audiocache.done" echo Audio cache setup exited successfully.

:launch
'''.replace("\n", "\r\n").encode("ascii")


def launcher(first_run_audio: bool) -> bytes:
    if first_run_audio:
        return LAUNCHER.replace(b'start "" /D', FIRST_RUN_AUDIO + b'start "" /D', 1)
    return LAUNCHER


class LaunchersPatch:
    id = "launchers"
    display_name = "Launch files"
    description = "Create launchers for Portal 2 and its settings interface."

    def _path(self, context: PatchContext):
        return context.root / "Launch Portal 2.cmd"

    def _settings_launcher_path(self, context: PatchContext):
        return context.root / "Settings.bat"

    def _settings_script_path(self, context: PatchContext):
        return context.root / ".p2patcher" / "settings.ps1"

    def check(self, context: PatchContext) -> bool:
        path = self._path(context)
        settings_launcher = self._settings_launcher_path(context)
        settings_script = self._settings_script_path(context)
        return (
            not path.is_file()
            or path.read_bytes() != launcher(context.profile.first_run_audio if context.profile else False)
            or not settings_launcher.is_file()
            or settings_launcher.read_bytes() != SETTINGS_LAUNCHER
            or not settings_script.is_file()
            or settings_script.read_bytes() != SETTINGS_SCRIPT
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        atomic_write(self._path(context), launcher(context.profile.first_run_audio if context.profile else False))
        self._settings_script_path(context).parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._settings_launcher_path(context), SETTINGS_LAUNCHER)
        atomic_write(self._settings_script_path(context), SETTINGS_SCRIPT)

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Launcher verification failed")


DEFINITION = PatchDefinition(LaunchersPatch())
