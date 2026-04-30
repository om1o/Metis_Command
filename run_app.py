"""
run_app.py — launches the Metis Command Streamlit UI.
Run this file directly:  python run_app.py
"""

import subprocess
import sys
import os

APP_FILE = os.path.join(os.path.dirname(__file__), "dynamic_ui.py")


def main():
    print("=" * 60)
    print("  METIS COMMAND — Launching UI")
    print("=" * 60)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", APP_FILE,
         "--server.headless", "false",
         "--browser.gatherUsageStats", "false"],
        check=True,
    )


if __name__ == "__main__":
    main()
