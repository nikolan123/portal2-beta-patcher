@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "OUTPUT_DIR=%REPO_ROOT%\build\launcher"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"

if not exist "%VSWHERE%" (
    echo Visual Studio Installer could not be found.
    exit /b 1
)

set "VS_ROOT="
for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS_ROOT=%%I"
if not defined VS_ROOT (
    echo Visual Studio with the C++ x86 build tools could not be found.
    exit /b 1
)

call "%VS_ROOT%\VC\Auxiliary\Build\vcvars32.bat" >nul
if errorlevel 1 exit /b %errorlevel%

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if errorlevel 1 exit /b %errorlevel%

cl.exe /nologo /O2 /MT /W4 /DWIN32 /D_WINDOWS ^
    /Fo:"%OUTPUT_DIR%\hl2.obj" ^
    /Fe:"%OUTPUT_DIR%\hl2.exe" ^
    "%SCRIPT_DIR%hl2.cpp" ^
    /link /SUBSYSTEM:WINDOWS /MACHINE:X86 user32.lib
if errorlevel 1 exit /b %errorlevel%

echo Built "%OUTPUT_DIR%\hl2.exe"
