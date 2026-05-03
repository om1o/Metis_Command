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
    env = os.environ.copy()
    # Ensure Streamlit never prompts for onboarding in non-interactive runs.
    env["STREAMLIT_BROWSER_GATHERUSAGESTATS"] = "false"
    # Headless avoids the onboarding email prompt entirely.
    env["STREAMLIT_SERVER_HEADLESS"] = "true"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            APP_FILE,
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
