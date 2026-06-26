# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


block_cipher = None

datas = [
    ("app/assets/style-light.css", "app/assets"),
    ("app/assets/style-dark.css", "app/assets"),
    ("app/assets/app.ico", "app/assets"),
    ("app/assets/logo.svg", "app/assets"),
    ("app/templates/page.html", "app/templates"),
]
# python-docx ships a default .docx template that must be bundled alongside it.
datas += collect_data_files("docx")
# The gravity-ui editor bundle (built by the frontend step), if present.
if os.path.exists("app/assets/editor/index.html"):
    datas.append(("app/assets/editor/index.html", "app/assets/editor"))

hiddenimports = (
    collect_submodules("markdown_it")
    + collect_submodules("mdit_py_plugins")
    + collect_submodules("docx")
)

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MdReader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/assets/app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MdReader",
)
