"""
ChromaDB connection — Vector Search / RAG for crawled laws.

Collection starts EMPTY and is populated autonomously by the ALCD module.
Implementation of embedding pipeline: Phase 2.
"""
import chromadb

from app.config import settings


def get_chroma_client(
    host: str | None = None, port: int | None = None
) -> chromadb.HttpClient:
    """Create a ChromaDB HTTP client connected to the containerized service."""
    return chromadb.HttpClient(
        host=host or settings.chromadb_host,
        port=port or settings.chromadb_port,
    )


def get_laws_collection(client: chromadb.HttpClient):
    """Get or create the indonesian_laws collection (starts empty)."""
    return client.get_or_create_collection(
        name="indonesian_laws",
        metadata={"description": "Indonesian legal documents — autonomously populated by ALCD"},
    )
