"""
LangGraph Orchestrator — ALA Multi-Agent State Machine.

Orchestrates the 4-agent pipeline over a shared ALA_State:

    ALCD Agent (Agent 0)          — bootstrap knowledge from zero
        -> Legal Foundation (Agent 1)  — master acquired law corpus
        -> Internet Crawler (Agent 2)  — universal crime trend discovery
        -> Synthesis & Developer (Agent 3) — law x reality, code gen

Shared state fields: query, institution_id, tier_level,
context_token_budget, knowledge_ready, knowledge_score,
ontology_coverage, legal_articles, cross_references, legal_summary,
crime_data, crime_summary, synthesis, generated_output,
audit_trail, errors.
"""
import logging
from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agents.code_generator import synthesis_developer_agent
from app.agents.curriculum_designer import alcd_agent
from app.agents.internet_crawler import internet_crawler_agent
from app.agents.legal_foundation import legal_foundation_agent
from app.agents.state import ALA_State

logger = logging.getLogger("ala.orchestrator")


def _knowledge_gate(state: ALA_State) -> str:
    """Kondisi: lanjut ke Agent 1 hanya jika pengetahuan siap.

    Jika ALCD belum siap (mis. bootstrap gagal total), tetap lanjut
    dengan basis pengetahuan parsial — APH masih menerima output
    berlabel parsial daripada request hang.
    """
    if state.get("knowledge_ready"):
        return "legal_foundation"
    logger.warning(
        "Knowledge belum siap (score=%.2f) — lanjut dengan data parsial",
        state.get("knowledge_score") or 0.0,
    )
    return "legal_foundation"


@lru_cache(maxsize=1)
def build_graph():
    """Bangun state machine LangGraph (lazy singleton)."""
    graph = StateGraph(ALA_State)

    graph.add_node("alcd", alcd_agent)
    graph.add_node("legal_foundation", legal_foundation_agent)
    graph.add_node("internet_crawler", internet_crawler_agent)
    graph.add_node("synthesis_developer", synthesis_developer_agent)

    graph.set_entry_point("alcd")
    graph.add_conditional_edges("alcd", _knowledge_gate)
    graph.add_edge("legal_foundation", "internet_crawler")
    graph.add_edge("internet_crawler", "synthesis_developer")
    graph.add_edge("synthesis_developer", END)

    return graph.compile()


def run_pipeline(
    query: str,
    institution_id: str = "",
    tier_level: str = "free",
    context_token_budget: int = 2048,
) -> ALA_State:
    """Jalankan pipeline 4-agen untuk satu query.

    Args:
        query: pertanyaan pengguna.
        institution_id: tenant (untuk data operasional, BUKAN hukum).
        tier_level: tier SaaS pengguna.
        context_token_budget: num_ctx efektif dari middleware.

    Returns:
        ALA_State final dengan semua output agen.
    """
    app = build_graph()
    initial: ALA_State = {
        "query": query,
        "institution_id": institution_id,
        "tier_level": tier_level,
        "context_token_budget": context_token_budget,
        "audit_trail": [],
        "errors": [],
    }
    logger.info("Pipeline mulai — institusi=%s tier=%s budget=%d",
                institution_id, tier_level, context_token_budget)
    return app.invoke(initial)
