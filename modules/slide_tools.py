from __future__ import annotations

from core.registry import tool


@tool(
    "Generate a PowerPoint (.pptx) slide deck about a topic. Expands the topic into a titled "
    "outline and builds the deck locally. Optionally set num_slides (default 5). Returns the "
    "saved file path."
)
def generate_slides(topic: str, num_slides: int = 5) -> str:
    from agents.slides import generate_slides as _gen
    return _gen(topic, num_slides)
