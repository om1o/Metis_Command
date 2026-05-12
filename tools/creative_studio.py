"""
Creative Studio — local image generation via diffusers + Stable Diffusion.

Sovereign-tier only. Lite/Pro callers receive an "upsell" Artifact
instead of an image so the Director can see the gate in action.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from artifacts import Artifact, save_artifact
from subscription import Tier, require_tier


IMAGES_DIR = Path("artifacts") / "generated"
DEFAULT_MODEL = "stabilityai/sd-turbo"


def _upsell_artifact(prompt: str) -> Artifact:
    return save_artifact(Artifact(
        type="upsell",
        title="Creative Studio requires Sovereign tier",
        content=(
            "Image generation with Stable Diffusion runs locally on your GPU "
            "and is included with the Sovereign tier.\n\n"
            f"Your prompt was:\n    {prompt!r}\n\n"
            "Upgrade via the Marketplace tab to unlock."
        ),
        metadata={"feature": "creative_studio", "required_tier": Tier.SOVEREIGN.value
                  if hasattr(Tier, "SOVEREIGN") else "Sovereign"},
    ))


def generate_image(
    prompt: str,
    *,
    size: str = "512x512",
    steps: int = 4,
    model: str = DEFAULT_MODEL,
) -> Artifact:
    """Generate an image locally and return an Artifact describing it."""
    if not require_tier("Enterprise"):  # Enterprise ≙ Sovereign for now
        return _upsell_artifact(prompt)

    try:
        import torch  # type: ignore
        from diffusers import AutoPipelineForText2Image  # type: ignore
    except Exception:
        return save_artifact(Artifact(
            type="doc",
            title="Image generation unavailable",
            content=(
                "Install diffusers to enable Creative Studio:\n"
                "    pip install diffusers accelerate safetensors torch"
            ),
        ))

    w, _, h = size.partition("x")
    try:
        pipe = AutoPipelineForText2Image.from_pretrained(
            model,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        )
        if torch.cuda.is_available():
            pipe = pipe.to("cuda")

        result = pipe(
            prompt=prompt,
            num_inference_steps=steps,
            width=int(w or 512),
            height=int(h or 512),
        )
        image = result.images[0]

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        out = IMAGES_DIR / f"img_{int(time.time()*1000)}.png"
        image.save(out)

        return save_artifact(Artifact(
            type="image",
            title=prompt[:80],
            path=str(out),
            metadata={"prompt": prompt, "model": model, "steps": steps, "size": size},
        ))
    except Exception as e:
        return save_artifact(Artifact(
            type="doc",
            title="Image generation failed",
            content=f"{type(e).__name__}: {e}",
            metadata={"prompt": prompt},
        ))


def as_crewai_tool():
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return None

    @tool("GenerateImage")
    def _gen(prompt: str) -> str:
        """Generate an image from `prompt` locally. Returns the artifact path."""
        art = generate_image(prompt)
        return art.path or art.id

    return _gen
