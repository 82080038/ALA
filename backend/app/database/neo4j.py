"""
Neo4j connection — Graph Database for legal ontology and relation mapping.

Graph starts EMPTY and is populated autonomously by the ALCD module.
Implementation of graph schema and queries: Phase 2.
"""
from neo4j import GraphDatabase

from app.config import settings


def get_neo4j_driver():
    """Create a Neo4j driver instance."""
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def verify_neo4j_connection(driver) -> bool:
    """Test the Neo4j connection with a simple query."""
    try:
        with driver.session() as session:
            result = session.run("RETURN 1 AS ping")
            return result.single()["ping"] == 1
    except Exception:
        return False
