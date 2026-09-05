# Run with: uv run pyinstaller build.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("tkinterdnd2")
datas.append(("src/patches/p1_hl2_assets.txt", "patches"))
datas.append(("src/patches/p8_prerelease_assets.zip", "patches"))
datas.append(("src/patches/p14_march_assets.zip", "patches"))

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Portal2BetaPatcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
