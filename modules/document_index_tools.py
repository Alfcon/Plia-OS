from __future__ import annotations
from core.registry import tool


@tool("Index documents in a directory for semantic search. glob defaults to common text/document types.")
def index_documents(directory: str, glob: str = "**/*.txt") -> str:
    from agents.document_store import get_document_store
    return get_document_store().index_directory(directory, glob)


@tool("Search the indexed document store for text relevant to a query.")
def query_documents(query: str, n_results: int = 5) -> str:
    from agents.document_store import get_document_store
    return get_document_store().query(query, n_results)


@tool("List all document sources currently indexed in the document store.")
def list_indexed_sources() -> str:
    from agents.document_store import get_document_store
    sources = get_document_store().list_sources()
    if not sources:
        return "No documents indexed yet. Use index_documents to add some."
    return "\n".join(f"• {s}" for s in sources)


@tool("Remove a previously indexed document source from the store by its full path.")
def remove_indexed_source(source_path: str) -> str:
    from agents.document_store import get_document_store
    n = get_document_store().delete_source(source_path)
    if n == 0:
        return f"Source not found or nothing deleted: {source_path}"
    return f"Removed {n} chunk(s) for {source_path}"
