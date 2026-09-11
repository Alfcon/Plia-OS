import re


def truncate_for_tts(text: str, max_words: int) -> str:
    """Truncate text at last sentence boundary before max_words. Returns original if no limit."""
    if not max_words or max_words <= 0:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    for end in (".", "!", "?"):
        idx = truncated.rfind(end)
        if idx > len(truncated) // 4:  # avoid truncating at start punctuation
            return truncated[: idx + 1] + " (see dashboard for full response)"
    return truncated + " … (see dashboard for full response)"


def strip_markdown(text: str) -> str:
    """Remove markdown formatting so TTS reads clean prose."""
    if not text:
        return ""
    # Fenced code blocks → "code block"
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    # Inline code → bare text
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Bold/italic (**x**, *x*, __x__, _x_)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
    # Headings (# Heading → Heading)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Images ![alt](url) → alt
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # Links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Blockquotes
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # List markers (- item, * item, 1. item)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Collapse excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
