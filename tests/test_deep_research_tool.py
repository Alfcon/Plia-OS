import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_deep_research_tool_delegates():
    with patch("agents.deep_research.run_deep_research", new_callable=AsyncMock, return_value="# R") as m:
        from modules.deep_research_tools import deep_research
        out = await deep_research("topic", source="both", max_subqueries=3)
    m.assert_awaited_once_with("topic", "both", 3, "chat")
    assert "R" in out
