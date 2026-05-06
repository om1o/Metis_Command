# PyInstaller spec for Metis — single-file Windows build.
# Usage:  pyinstaller metis.spec
#
# Builds start_metis.pyw into dist/Metis.exe with the tray + webview daemon.
# Streamlit + FastAPI run as child subprocesses at runtime, so we bundle the
# Python source alongside the executable via a datas list.

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

ROOT = Path.cwd()

datas = []
for module in [
    "dynamic_ui.py",
    "ui_theme.py",
    "api_bridge.py",
    "metis_daemon.py",
    "brain_engine.py",
    "module_manager.py",
    "swarm_agents.py",
    "task_manager.py",
    "crew_engine.py",
    "memory.py",
    "memory_vault.py",
    "memory_loop.py",
    "identity_matrix.py",
    "skill_forge.py",
    "artifacts.py",
    "marketplace.py",
    "subscription.py",
    "mts_format.py",
    "auth_engine.py",
    "cloud_sync.py",
    "custom_tools.py",
    "comms_link.py",
    "hardware_scanner.py",
    "supabase_client.py",
    "schema.sql",
    ".env.example",
]:
    if (ROOT / module).exists():
        datas.append((str(ROOT / module), "."))

for folder in ["tools", "plugins", "animations", "docs"]:
    src = ROOT / folder
    if src.exists():
        for f in src.rglob("*"):
            if f.is_file():
                datas.append((str(f), str(f.parent.relative_to(ROOT))))

a = Analysis(
    ["start_metis.pyw"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "streamlit",
        "uvicorn",
        "fastapi",
        "pystray",
        "pynput",
        "webview",
        "crewai",
        "chromadb",
        "supabase",
        "stripe",
        "pyttsx3.drivers.sapi5",
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
    name="Metis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowless — tray only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
