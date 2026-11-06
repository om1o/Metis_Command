"""Exercise the first-run model command without downloading models."""

import sys
from pathlib import Path

import pytest

from scripts import bootstrap


@pytest.mark.parametrize(
    ("launcher_tier", "model_tier"),
    [("Lite", "Lite"), ("Pro", "Standard"), ("Sovereign", "Sovereign")],
)
def test_model_pull_uses_available_manager_and_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher_tier: str, model_tier: str
) -> None:
    (tmp_path / "module_manager.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "def download_tier_silent(tier):\n"
        "    log = Path(os.environ['METIS_TEST_MODEL_LOG'])\n"
        "    log.write_text('started:' + tier + '\\n')\n"
        "    class Worker:\n"
        "        def join(self):\n"
        "            with log.open('a') as out:\n"
        "                out.write('joined\\n')\n"
        "    return Worker()\n",
        encoding="utf-8",
    )
    log = tmp_path / "model.log"
    monkeypatch.setenv("METIS_TEST_MODEL_LOG", str(log))
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "venv_python", lambda: Path(sys.executable))

    bootstrap._pull_models(launcher_tier)

    assert log.read_text(encoding="utf-8") == f"started:{model_tier}\njoined\n"
