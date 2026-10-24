from __future__ import annotations

from core.registry import tool


@tool(
    "Generate an image from a text prompt using a local Stable Diffusion model on the GPU. "
    "Saves a PNG and returns its path. Needs a CUDA GPU; unavailable on CPU-only machines."
)
def generate_image(prompt: str) -> str:
    from agents.image_gen import generate_image as _gen
    return _gen(prompt)
