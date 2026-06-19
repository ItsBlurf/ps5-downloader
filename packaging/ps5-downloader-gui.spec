# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["../src/ps5_downloader/desktop/app.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "ps5_downloader.cli.main",
        "ps5_downloader.server.api",
        "ps5_downloader.plugins.mediafire",
        "ps5_downloader.plugins.rootz",
        "ps5_downloader.plugins.akirabox",
        "ps5_downloader.plugins.onefichier",
        "ps5_downloader.plugins.buzzheavier",
        "ps5_downloader.plugins.github",
        "ps5_downloader.plugins.generic_html",
        "ps5_downloader.plugins.direct_http",
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ps5-downloader-gui",
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
