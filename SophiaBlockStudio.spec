# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

a = Analysis(
    ['block_studio.py'],
    pathex=['D:\\PythonTest\\AduinoTest'],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('universal_firmware', 'universal_firmware'),
    ],
    hiddenimports=[
        'waitress',
        'waitress.adjustments',
        'waitress.buffers',
        'waitress.channel',
        'waitress.compat',
        'waitress.parser',
        'waitress.proxy_headers',
        'waitress.receiver',
        'waitress.server',
        'waitress.task',
        'waitress.trigger',
        'waitress.utilities',
        'waitress.wasyncore',
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'serial.tools.list_ports_windows',
        'flask',
        'edge_tts',
        'edge_tts.constants',
        'edge_tts.submaker',
        'asyncio',
        'avr_flasher',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'pandas', 'pygame', 'tkinter'],
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
    name='SophiaBlockStudio',
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
    icon=['app_icon.ico'],
)

