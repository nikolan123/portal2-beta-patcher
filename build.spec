# Run tools/prepare-native.ps1 first, then:
# uv run pyinstaller build.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("tkinterdnd2")
# Use exactly the same resource declarations as runtime patch loading.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(SPECPATH) / "src"))
from patches.registry import DEFINITIONS
from patches.resources import packaging_data
datas.extend(packaging_data(DEFINITIONS))


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
    manifest='''<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
      <application xmlns="urn:schemas-microsoft-com:asm.v3">
        <windowsSettings>
          <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
          <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">system</dpiAwareness>
        </windowsSettings>
      </application>
    </assembly>''',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
