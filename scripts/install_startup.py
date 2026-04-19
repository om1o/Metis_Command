"""
Install / uninstall Metis in the Windows Startup registry.

Usage:
    python scripts/install_startup.py install
    python scripts/install_startup.py uninstall
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MetisCommand"


def _reg():
    try:
        import winreg  # type: ignore
    except ImportError as e:
        raise SystemExit("This helper only runs on Windows.") from e
    return winreg


def install() -> None:
    winreg = _reg()
    target = Path(__file__).resolve().parent.parent / "start_metis.pyw"
    if not target.exists():
        raise SystemExit(f"start_metis.pyw not found at {target}")
    cmd = f'"{sys.executable}" "{target}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
    print(f"[Metis] Startup entry set:\n    {cmd}")


def uninstall() -> None:
    winreg = _reg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        print("[Metis] Startup entry removed.")
    except FileNotFoundError:
        print("[Metis] No startup entry was set.")


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "install").lower()
    if cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    else:
        print(__doc__)
