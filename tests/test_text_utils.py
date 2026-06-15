import pytest
from voice.text_utils import strip_markdown


def test_bold_removed():
    assert strip_markdown("**hello** world") == "hello world"


def test_italic_removed():
    assert strip_markdown("*hello* world") == "hello world"


def test_heading_removed():
    assert strip_markdown("# Hello\nworld") == "Hello\nworld"


def test_h2_removed():
    assert strip_markdown("## Section\ntext") == "Section\ntext"


def test_inline_code_unwrapped():
    assert strip_markdown("use `print()` to output") == "use print() to output"


def test_fenced_code_block_replaced():
    result = strip_markdown("here:\n```python\nx = 1\n```\ndone")
    assert "x = 1" not in result
    assert "code block" in result


def test_link_text_kept():
    assert strip_markdown("[click here](https://example.com)") == "click here"


def test_image_alt_kept():
    assert strip_markdown("![diagram](img.png)") == "diagram"


def test_list_markers_removed():
    assert strip_markdown("- item one\n- item two") == "item one\nitem two"


def test_numbered_list_markers_removed():
    assert strip_markdown("1. first\n2. second") == "first\nsecond"


def test_blockquote_removed():
    assert strip_markdown("> quoted text") == "quoted text"


def test_horizontal_rule_removed():
    result = strip_markdown("above\n---\nbelow")
    assert "---" not in result
    assert "above" in result
    assert "below" in result


def test_plain_text_unchanged():
    assert strip_markdown("Hello, how are you?") == "Hello, how are you?"


def test_mixed_formatting():
    text = "**Bold** and *italic* with `code` and [link](http://x.com)"
    result = strip_markdown(text)
    assert "**" not in result
    assert "*" not in result
    assert "`" not in result
    assert "http://x.com" not in result
    assert "Bold" in result
    assert "link" in result


def test_underscore_bold_removed():
    assert strip_markdown("__hello__") == "hello"


def test_strips_leading_trailing_whitespace():
    assert strip_markdown("  hello  ") == "hello"
