"""
Code Interpreter — ChatGPT Advanced-Data-Analysis-style REPL.

Runs Python with pandas, numpy, matplotlib preloaded in the Docker sandbox
when available, otherwise the same subprocess fallback skill_forge uses.
Every run captures:
    - the returned stdout
    - any files written to the scratch folder (CSVs, images, plots)
    - plotted figures saved as PNG Artifacts

Designed so an agent can say "analyze this CSV" and get both a text
answer AND a chart Artifact the UI can show in the right pane.
"""

from __future__ import annotations

import base64
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

from artifacts import Artifact, save_artifact
from safety import audited


SCRATCH_DIR = Path("artifacts") / "scratch"


BOOTSTRAP = r"""
import os, sys, io, json, base64
sys.path.insert(0, os.getcwd())
try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception as _e:
    print(f"[code_interpreter] scientific stack missing: {_e}", file=sys.stderr)
_SAVED_IMAGES = []
def _metis_savefig():
    import matplotlib.pyplot as _plt
    path = os.path.join(os.environ.get('METIS_SCRATCH','.'),
                        f'plot_{os.getpid()}_{len(_SAVED_IMAGES)}.png')
    _plt.savefig(path, dpi=130, bbox_inches='tight')
    _plt.close('all')
    _SAVED_IMAGES.append(path)
    return path
"""


FOOTER = r"""
try:
    import matplotlib.pyplot as _plt
    if _plt.get_fignums():
        _metis_savefig()
    print("\n__METIS_IMAGES__=" + json.dumps(_SAVED_IMAGES))
except Exception:
    pass
"""


@audited("code_interpreter.run")
def run(code: str, *, timeout: int = 60) -> dict[str, Any]:
    """Execute `code` with the data-science stack preloaded."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = SCRATCH_DIR / uuid.uuid4().hex[:10]
    run_dir.mkdir(parents=True, exist_ok=True)
    script = f"{BOOTSTRAP}\n{textwrap.dedent(code).rstrip()}\n{FOOTER}\n"

    # Route through skill_forge's sandbox so Docker path/subprocess fallback
    # is shared. The sandbox captures stdout + stderr for us.
    from skill_forge import run_in_sandbox
    sandbox_result = run_in_sandbox(script, timeout=timeout)

    stdout = sandbox_result.get("stdout", "") or ""
    images: list[str] = []
    marker = "__METIS_IMAGES__="
    if marker in stdout:
        head, _, tail = stdout.rpartition(marker)
        try:
            import json as _json
            images = _json.loads(tail.strip().splitlines()[0])
            stdout = head
        except Exception:
            pass

    artifacts: list[Artifact] = []

    # Convert any generated plots to Artifacts the UI pane can render.
    for idx, img_path in enumerate(images):
        try:
            src = Path(img_path)
            if not src.exists():
                continue
            dst = run_dir / f"plot_{idx}.png"
            dst.write_bytes(src.read_bytes())
            artifacts.append(save_artifact(Artifact(
                type="image",
                title=f"Plot {idx + 1}",
                path=str(dst),
                metadata={"run_dir": str(run_dir), "source": "code_interpreter"},
            )))
        except Exception:
            continue

    # Wrap the text output as a doc Artifact too.
    text_artifact = save_artifact(Artifact(
        type="doc",
        title="Code Interpreter Result",
        content=stdout[:20_000],
        metadata={
            "run_dir":    str(run_dir),
            "ok":         sandbox_result.get("ok"),
            "exit_code":  sandbox_result.get("exit_code"),
            "mode":       sandbox_result.get("mode"),
            "stderr":     sandbox_result.get("stderr", "")[:4000],
        },
    ))

    return {
        "ok":        sandbox_result.get("ok", False),
        "stdout":    stdout,
        "stderr":    sandbox_result.get("stderr", ""),
        "exit_code": sandbox_result.get("exit_code"),
        "mode":      sandbox_result.get("mode"),
        "images":    [a.path for a in artifacts],
        "artifact_ids": [text_artifact.id] + [a.id for a in artifacts],
    }


def analyze_file(path: str, *, question: str = "Summarize this data.") -> dict[str, Any]:
    """
    Convenience: load a CSV/Parquet/JSON via pandas and ask the Coder to
    answer `question` about it. Returns the analysis + any plots.
    """
    p = Path(path).resolve()
    if not p.exists():
        return {"ok": False, "error": f"not found: {p}"}
    code = f"""
df = pd.read_csv(r'{p}') if '{p.suffix}' == '.csv' else pd.read_json(r'{p}')
print("shape:", df.shape)
print(df.describe(include='all').head(20))
"""
    result = run(code)
    result["question"] = question
    return result


# ── CrewAI adapter ───────────────────────────────────────────────────────────

def as_crewai_tool():
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return None

    @tool("CodeInterpreter")
    def _run(code: str) -> str:
        """Run Python with pandas/numpy/matplotlib preloaded. Returns JSON."""
        import json as _json
        return _json.dumps(run(code))

    return _run
