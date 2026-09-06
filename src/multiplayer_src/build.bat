@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "OUTPUT_DIR=%REPO_ROOT%\build\native"
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

cl.exe /nologo /LD /O2 /MT /W4 /WX /EHsc- /GR- ^
    /Fo:"%OUTPUT_DIR%\p18_multiplayer_852_0.obj" ^
    "%SCRIPT_DIR%p18_multiplayer_852_0.cpp" ^
    /link /Brepro ^
    /OUT:"%OUTPUT_DIR%\p18_multiplayer_852_0.asi" ^
    /PDB:"%OUTPUT_DIR%\p18_multiplayer_852_0.pdb"
if errorlevel 1 exit /b %errorlevel%

del /q "%OUTPUT_DIR%\p18_multiplayer_852_0.obj" 2>nul
del /q "%OUTPUT_DIR%\p18_multiplayer_852_0.pdb" 2>nul

echo Built "%OUTPUT_DIR%\p18_multiplayer_852_0.asi"
