import pytest
from unittest.mock import patch
from pathlib import Path


def _make_store_no_chromadb(tmp_path):
    with patch.dict("sys.modules", {"chromadb": None}):
        import importlib
        import agents.document_store as ds
        importlib.reload(ds)
        return ds._DocumentStore(str(tmp_path))


def test_store_unavailable_graceful(tmp_path):
    store = _make_store_no_chromadb(tmp_path)
    assert store._ready is False
    result = store.index_directory(str(tmp_path))
    assert "unavailable" in result.lower()


def test_store_query_unavailable(tmp_path):
    store = _make_store_no_chromadb(tmp_path)
    result = store.query("anything")
    assert "unavailable" in result.lower()


def test_store_list_sources_unavailable(tmp_path):
    store = _make_store_no_chromadb(tmp_path)
    assert store.list_sources() == []


def test_store_delete_unavailable(tmp_path):
    store = _make_store_no_chromadb(tmp_path)
    assert store.delete_source("/some/path.txt") == 0


def test_index_directory_missing(tmp_path):
    store = _make_store_no_chromadb(tmp_path)
    result = store.index_directory(str(tmp_path / "nonexistent"))
    assert "unavailable" in result.lower() or "not found" in result.lower()


def test_chunk_basic():
    from agents.document_store import _chunk
    text = " ".join(["word"] * 100)
    chunks = _chunk(text, size=50, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        assert c.strip()


def test_chunk_empty():
    from agents.document_store import _chunk
    result = _chunk("", size=50, overlap=10)
    assert isinstance(result, list)


def test_read_file_text_txt(tmp_path):
    from agents.document_store import _read_file_text
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    assert _read_file_text(f) == "hello world"


def test_read_file_text_md(tmp_path):
    from agents.document_store import _read_file_text
    f = tmp_path / "test.md"
    f.write_text("# heading\ncontent")
    assert "heading" in _read_file_text(f)


def test_read_file_text_unsupported(tmp_path):
    from agents.document_store import _read_file_text
    f = tmp_path / "test.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert _read_file_text(f) == ""
