"""
Shared State — ALA_State untuk pipeline LangGraph multi-agen.

Semua agen (ALCD → Legal Foundation → Internet Crawler → Synthesis &
Developer) membaca dan memperbarui state ini secara sekuensial.

`audit_trail` dan `errors` menggunakan reducer `operator.add` agar setiap
agen menambahkan (append) entri baru, bukan menimpa.
"""
import operator
from typing import Annotated, NotRequired, Optional, TypedDict


class CrimeSource(TypedDict):
    title: str
    url: str
    snippet: str
    published_date: Optional[str]


class LegalArticle(TypedDict):
    law_name: str
    article_number: str
    title: str
    content: str
    relevance_score: float
    source_url: NotRequired[str]
    topic: NotRequired[str]
    # Opsional — struktur hukum formal (hanya bila ada di metadata):
    elements: NotRequired[dict]  # pelaku/perbuatan/sikap_batin/ancaman
    kaidah: NotRequired[dict]    # putusan: ratio/pasal/amar terstruktur


class CrossReference(TypedDict):
    from_article: str
    to_article: str
    relationship: str


class GeneratedOutput(TypedDict, total=False):
    filename: str
    language: str
    description: str
    code: str
    flowchart: str
    kuhap_validated: bool
    custody_scaffolded: bool


class ALA_State(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────
    query: str

    # ── Konteks tenant & kuota (diisi middleware FastAPI) ──
    institution_id: str          # tenant pemilik request (data operasional)
    tier_level: str              # free | premium_l1 | premium_l2
    context_token_budget: int    # num_ctx efektif: min(tier_cap, hw_ceiling)
    mode: str                    # "full" (4 agen) | "legal" (hanya pasal)

    # ── Agent 0: ALCD (bootstrap pengetahuan — GLOBAL) ─────
    knowledge_ready: bool
    knowledge_score: float
    ontology_coverage: dict

    # ── Agent 1: Legal Foundation ──────────────────────────
    legal_articles: list[LegalArticle]
    cross_references: list[CrossReference]
    legal_summary: str

    # ── Agent 2: Internet Crawler ──────────────────────────
    crime_data: list[CrimeSource]
    crime_summary: str

    # ── Agent 3: Synthesis & Developer ─────────────────────
    synthesis: dict
    generated_output: GeneratedOutput

    # ── Metadata (append via reducer) ──────────────────────
    audit_trail: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
