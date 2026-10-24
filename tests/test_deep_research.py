import pytest
from unittest.mock import AsyncMock, patch


def test_parse_json_array_clean():
    from agents.deep_research import _parse_json_array
    assert _parse_json_array('["a","b"]') == ["a", "b"]


def test_parse_json_array_in_prose():
    from agents.deep_research import _parse_json_array
    assert _parse_json_array('Here you go: ["x", "y"] done') == ["x", "y"]


def test_parse_json_array_none():
    from agents.deep_research import _parse_json_array
    assert _parse_json_array("no array here") is None


@pytest.mark.asyncio
async def test_plan_queries_parses_and_caps():
    from agents.deep_research import _plan_queries
    with patch("agents.llm.call_llm", new_callable=AsyncMock, return_value={"content": '["q1","q2","q3"]'}):
        out = await _plan_queries("topic", max_subqueries=2)
    assert out == ["q1", "q2"]


@pytest.mark.asyncio
async def test_plan_queries_fallback_on_unparseable():
    from agents.deep_research import _plan_queries
    with patch("agents.llm.call_llm", new_callable=AsyncMock, return_value={"content": "no json"}):
        out = await _plan_queries("my topic", max_subqueries=4)
    assert out == ["my topic"]


@pytest.mark.asyncio
async def test_plan_queries_fallback_on_llm_error():
    from agents.deep_research import _plan_queries
    with patch("agents.llm.call_llm", new_callable=AsyncMock, side_effect=RuntimeError("down")):
        out = await _plan_queries("t", max_subqueries=4)
    assert out == ["t"]


@pytest.mark.asyncio
async def test_web_sources_dedups_and_scrapes():
    import agents.deep_research as dr

    def _ddg(sq, n):
        return [
            {"title": "T1", "href": "http://a", "body": "b1"},
            {"title": "T2", "href": "http://b", "body": "b2"},
        ]

    with patch.object(dr, "_ddg_search", side_effect=_ddg), \
         patch.object(dr, "_scrape", new_callable=AsyncMock, return_value="page text"):
        out = await dr._web_sources(["q1", "q2"], per_query=2)
    assert {s["url"] for s in out} == {"http://a", "http://b"}  # deduped across both queries
    assert len(out) == 2
    assert out[0]["text"] == "page text"


@pytest.mark.asyncio
async def test_web_sources_scrape_failure_falls_back_to_snippet():
    import agents.deep_research as dr
    with patch.object(dr, "_ddg_search", return_value=[{"title": "T", "href": "http://x", "body": "snippet body"}]), \
         patch.object(dr, "_scrape", new_callable=AsyncMock, return_value=""):
        out = await dr._web_sources(["q"], per_query=1)
    assert out[0]["text"] == "snippet body"


@pytest.mark.asyncio
async def test_academic_sources_wraps_research_search():
    import agents.deep_research as dr
    with patch("modules.research_tools.research_search", new_callable=AsyncMock, return_value="## arXiv\n1. [Paper](u)"):
        out = await dr._academic_sources(["q1"])
    assert len(out) == 1
    assert out[0]["title"] == "q1"
    assert "arXiv" in out[0]["text"]


@pytest.mark.asyncio
async def test_gather_sources_both_combines():
    import agents.deep_research as dr
    with patch.object(dr, "_web_sources", new_callable=AsyncMock, return_value=[{"title": "w", "url": "http://w", "text": "wt"}]), \
         patch.object(dr, "_academic_sources", new_callable=AsyncMock, return_value=[{"title": "a", "url": "", "text": "at"}]):
        out = await dr._gather_sources(["q"], "both")
    assert len(out) == 2
    assert {s["title"] for s in out} == {"w", "a"}


@pytest.mark.asyncio
async def test_gather_sources_academic_only():
    import agents.deep_research as dr
    with patch.object(dr, "_web_sources", new_callable=AsyncMock) as web, \
         patch.object(dr, "_academic_sources", new_callable=AsyncMock, return_value=[{"title": "a", "url": "", "text": "at"}]):
        out = await dr._gather_sources(["q"], "academic")
    web.assert_not_awaited()
    assert out[0]["title"] == "a"


@pytest.mark.asyncio
async def test_synthesize_no_sources():
    from agents.deep_research import _synthesize
    out = await _synthesize("t", [])
    assert "no sources" in out.lower()


@pytest.mark.asyncio
async def test_synthesize_returns_report():
    from agents.deep_research import _synthesize
    with patch("agents.llm.call_llm", new_callable=AsyncMock, return_value={"content": "# Report\n..."}):
        out = await _synthesize("t", [{"title": "a", "url": "http://a", "text": "stuff"}])
    assert "Report" in out


@pytest.mark.asyncio
async def test_synthesize_fallback_on_llm_error_keeps_sources():
    from agents.deep_research import _synthesize
    with patch("agents.llm.call_llm", new_callable=AsyncMock, side_effect=RuntimeError("down")):
        out = await _synthesize("t", [{"title": "a", "url": "http://src", "text": "stuff"}])
    assert "http://src" in out


@pytest.mark.asyncio
async def test_run_deep_research_end_to_end(tmp_path):
    import agents.deep_research as dr
    with patch.object(dr, "_plan_queries", new_callable=AsyncMock, return_value=["q1"]), \
         patch.object(dr, "_gather_sources", new_callable=AsyncMock, return_value=[{"title": "a", "url": "http://a", "text": "t"}]), \
         patch.object(dr, "_synthesize", new_callable=AsyncMock, return_value="# The Report"), \
         patch("modules.research_tools._RESEARCH_DIR", tmp_path):
        out = await dr.run_deep_research("topic", source="web", output_formats="chat,file")
    assert "The Report" in out
    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    assert "Saved to" in out
