# load_dotenv MUST be the first two lines — crewai/langchain read env vars at import time
from dotenv import load_dotenv
load_dotenv()

import os
import csv
from datetime import datetime
from crew_engine import run_swarm_mission

BANNER = r"""
 __  __ _____ _____ _____     ___  ____
|  \/  | ____|_   _|_ _\ \   / / |/ ___|
| |\/| |  _|   | |  | |  \ \ / /| |\___ \
| |  | | |___  | |  | |   \ V / | | ___) |
|_|  |_|_____| |_| |___|   \_/  |_||____/
"""


def export_csv(results_text: str, topic: str) -> str:
    """Write mission results to a timestamped CSV and return the file path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = "".join(c if c.isalnum() else "_" for c in topic)[:40]
    filename = f"leads_{safe_topic}_{timestamp}.csv"

    lines = [l.strip() for l in results_text.splitlines() if l.strip()]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "content"])
        for i, line in enumerate(lines, 1):
            writer.writerow([i, line])

    return filename


if __name__ == "__main__":
    print(BANNER)
    print("=" * 70)
    print(">>>>>        METIS OS ONLINE  —  Swarm Intelligence        <<<<<")
    print("=" * 70)

    topic = input("Director, what is our target for today? ").strip()
    if not topic:
        print("[ABORT] No target provided.")
        raise SystemExit(1)

    print(f"\n[MISSION STARTING] Hunting: '{topic}' — stand by...\n")

    try:
        results = run_swarm_mission(topic)
        results_text = str(results)
    except Exception as e:
        print(f"\n[MISSION FAILED] {e}")
        raise SystemExit(1)

    print("\n" + "=" * 70)
    print(">>>>>              MISSION RESULTS                        <<<<<")
    print("=" * 70)
    print(results_text)

    csv_path = export_csv(results_text, topic)
    print("=" * 70)
    print(f"[EXPORTED] Results saved to: {csv_path}")
    print("=" * 70)
