# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None
root = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(root, 'desktop.py')],
    pathex=[root],
    binaries=[],
    datas=[
        (os.path.join(root, 'frontend'), 'frontend'),
        (os.path.join(root, 'persona'), 'persona'),
    ],
    hiddenimports=[
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'backend',
        'backend.main',
        'backend.config',
        'backend.database',
        'backend.models',
        'backend.logger',
        'backend.routers',
        'backend.routers.chat',
        'backend.routers.config',
        'backend.routers.conversations',
        'backend.routers.memory',
        'backend.routers.persona',
        'backend.routers.proactive',
        'backend.services',
        'backend.services.llm_service',
        'backend.services.memory_service',
        'backend.services.context_builder',
        'backend.services.summary_service',
        'backend.services.persona_service',
        'backend.services.proactive_engine',
        'backend.services.relevance_engine',
        'backend.services.token_estimator',
        'webview',
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
    name='Memoria',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # Set icon path here if you have one
)
