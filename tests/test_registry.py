import pytest
from core.registry import tool, get_tool_schemas, call_tool, list_tools


def test_register_and_call():
    @tool(description="add two numbers")
    def add(a: int, b: int) -> int:
        return a + b

    assert call_tool("add", {"a": 3, "b": 4}) == 7


def test_schema_shape():
    @tool(description="greet someone")
    def greet(name: str) -> str:
        return f"Hello, {name}"

    schemas = get_tool_schemas()
    assert len(schemas) == 1
    fn = schemas[0]["function"]
    assert fn["name"] == "greet"
    assert fn["description"] == "greet someone"
    assert fn["parameters"]["properties"]["name"]["type"] == "string"
    assert "name" in fn["parameters"]["required"]


def test_optional_param_not_in_required():
    @tool(description="say something")
    def say(text: str, loud: bool = False) -> str:
        return text.upper() if loud else text

    schemas = get_tool_schemas()
    required = schemas[0]["function"]["parameters"]["required"]
    assert "text" in required
    assert "loud" not in required


def test_duplicate_name_warns_and_skips(caplog):
    @tool(description="first")
    def dupe() -> str:
        return "a"

    with caplog.at_level("WARNING"):
        @tool(description="second")
        def dupe() -> str:  # noqa: F811
            return "b"

    assert "already registered" in caplog.text
    # Original tool still registered (not replaced)
    assert call_tool("dupe", {}) == "a"


def test_unknown_tool_raises():
    with pytest.raises(KeyError):
        call_tool("nonexistent", {})


def test_list_tools():
    @tool(description="do a thing")
    def thing() -> str:
        return "done"

    tools = list_tools()
    assert tools == {"thing": "do a thing"}
