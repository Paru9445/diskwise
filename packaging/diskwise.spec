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

HERE = ROOT / "packaging"
# PyInstaller turns the PNG into an .ico on Windows (needs Pillow at build time).
ICON = str(HERE / ("icon.icns" if sys.platform == "darwin" else "icon.png"))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Diskwise",
    console=False,
    upx=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Diskwise", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Diskwise.app",
        icon=ICON,
        bundle_identifier="dev.praveensaxena.diskwise",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Diskwise",
            "CFBundleShortVersionString": VERSION,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "MIT License",
            # The text macOS shows in its permission prompts.
            "NSDesktopFolderUsageDescription": "Diskwise measures your Desktop to find large and forgotten files. It only deletes what you pick.",
            "NSDocumentsFolderUsageDescription": "Diskwise measures your Documents to find old projects and build leftovers. It only deletes what you pick.",
            "NSDownloadsFolderUsageDescription": "Diskwise looks for old installers and large downloads you may not need. It only deletes what you pick.",
            "NSRemovableVolumesUsageDescription": "Diskwise measures folders on this drive when you open it in Folders.",
            "NSNetworkVolumesUsageDescription": "Diskwise measures folders on this network drive when you open it in Folders.",        },
    )
