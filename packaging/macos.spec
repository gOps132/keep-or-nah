# -*- mode: python ; coding: utf-8 -*-

app_name = "Keep or Nah"
logo_datas = [("../public/logo.png", "public")]

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=logo_datas,
    hiddenimports=["keep_or_nah_core"],
    hookspath=[".."],
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
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)

app = BUNDLE(
    coll,
    name=f"{app_name}.app",
    icon="../build/assets/KeepOrNah.icns",
    bundle_identifier="com.keepornah.app",
)
