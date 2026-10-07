"""ALCD sub-modules — pipeline pembangunan pengetahuan hukum otonom."""
from app.agents.alcd.autonomous_ingestor import ingest_parsed_document, register_knowledge
from app.agents.alcd.document_parser import DocumentParser
from app.agents.alcd.graph_builder import build_graph_for_document
from app.agents.alcd.ontology_generator import CORE_OBJECTIVE, generate_ontology
from app.agents.alcd.source_discoverer import (
    _DEFAULT_TRUSTED as TRUSTED_DOMAINS,
    SourceDiscoverer,
)

__all__ = [
    "CORE_OBJECTIVE",
    "DocumentParser",
    "SourceDiscoverer",
    "TRUSTED_DOMAINS",
    "build_graph_for_document",
    "generate_ontology",
    "ingest_parsed_document",
    "register_knowledge",
]
