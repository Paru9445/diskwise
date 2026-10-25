# PyInstaller spec for the Diskwise desktop app. Build with packaging/build.py.
#   macOS   -> dist/Diskwise.app
#   Windows -> dist/Diskwise/Diskwise.exe (folder)
#   Linux   -> dist/Diskwise/Diskwise (folder)
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
VERSION = re.search(r'__version__ = "(.+?)"', (SRC / "diskwise" / "__init__.py").read_text()).group(1)

a = Analysis(
    [str(ROOT / "packaging" / "diskwise_app.py")],
    pathex=[str(SRC)],
    datas=[(str(SRC / "diskwise" / "ui.html"), "diskwise")],
    hiddenimports=["diskwise.desktop"],
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Diskwise",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Diskwise", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Diskwise.app",
        bundle_identifier="dev.praveensaxena.diskwise",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Diskwise",
            "CFBundleShortVersionString": VERSION,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
