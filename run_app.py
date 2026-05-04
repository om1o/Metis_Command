"""
Deprecated entry point.

The Metis web UI is served by FastAPI in api_bridge.py (default port 7331).
Use:  python launch.py
Or:   python -m uvicorn api_bridge:app --host 127.0.0.1 --port 7331

To run the legacy Streamlit UI manually:  streamlit run dynamic_ui.py
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "run_app.py is deprecated.\n"
        "  Start the app:  python launch.py\n"
        "  Dev API only:   python -m uvicorn api_bridge:app --host 127.0.0.1 --port 7331\n"
        "  Legacy Streamlit:  streamlit run dynamic_ui.py",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
