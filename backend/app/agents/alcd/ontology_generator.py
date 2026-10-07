"""
Ontology Generator — ALCD Fase 1.

Merumuskan peta pengetahuan (knowledge tree) terstruktur dari core
objective tunggal menggunakan LLM penalaran. Hasil disimpan ke tabel
`ontology_nodes` (scope GLOBAL).
"""
import json
import logging
import re

logger = logging.getLogger("ala.alcd.ontology")

CORE_OBJECTIVE = (
    "Optimalkan dan otomatisasi alur kerja untuk Aparat Penegak Hukum (APH) "
    "Indonesia"
)

_ONTOLOGY_PROMPT = """Kamu adalah arsitek pengetahuan hukum Indonesia.
Tujuan sistem: "{objective}"

Rumuskan ontologi pengetahuan hukum yang WAJIB dikuasai sistem ini.
Balas HANYA dengan JSON array valid — tanpa teks lain — berisi objek:
[
  {{"category": "nama kategori", "subcategory": "nama sub", "description":
    "mengapa pengetahuan ini dibutuhkan APH", "priority": 1}}
]

Aturan:
- priority 1 = paling kritis (KUHP, KUHAP), 5 = pendukung
- Wajib sertakan: hukum pidana materiil (KUHP, UU ITE, UU Tipikor,
  UU Narkotika, UU TPPU), hukum formil (KUHAP), regulasi teknis
  (Perkap/Perja), dan yurisprudensi (Putusan MA)
- Maksimal 15 node
"""

# Fallback jika LLM tidak dapat dijangkau / output tidak parse-able.
DEFAULT_ONTOLOGY: list[dict] = [
    {"category": "Hukum Pidana Materiil", "subcategory": "KUHP",
     "description": "Kitab Undang-Undang Hukum Pidana — kerangka delik utama",
     "priority": 1},
    {"category": "Hukum Pidana Formil", "subcategory": "KUHAP",
     "description": "Hukum acara pidana — alat bukti, prosedur, chain of custody",
     "priority": 1},
    {"category": "Hukum Pidana Materiil", "subcategory": "UU ITE",
     "description": "Informasi & Transaksi Elektronik — delik siber",
     "priority": 2},
    {"category": "Hukum Pidana Materiil", "subcategory": "UU Tipikor",
     "description": "Pemberantasan Tindak Pidana Korupsi",
     "priority": 2},
    {"category": "Hukum Pidana Materiil", "subcategory": "UU TPPU",
     "description": "Pencegahan & Pemberantasan Tindak Pidana Pencucian Uang",
     "priority": 2},
    {"category": "Hukum Pidana Materiil", "subcategory": "UU Narkotika",
     "description": "Narkotika & psikotropika — delik peredaran gelap",
     "priority": 3},
    {"category": "Regulasi Teknis", "subcategory": "Perkap/Perja",
     "description": "Peraturan Kapolri & Kejaksaan — SOP penegakan",
     "priority": 3},
    {"category": "Yurisprudensi", "subcategory": "Putusan MA",
     "description": "Putusan Mahkamah Agung — preseden & bukti elektronik",
     "priority": 4},
]


def _extract_json_array(text: str) -> list[dict] | None:
    """Ekstrak JSON array pertama dari output LLM secara toleran."""
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [n for n in data if isinstance(n, dict) and n.get("category")]


def generate_ontology(llm) -> list[dict]:
    """Hasilkan ontologi hukum dari core objective via LLM.

    Args:
        llm: ChatOllama penalaran (GPU 0).

    Returns:
        List node ontologi `[{category, subcategory, description, priority}]`.
        Fallback ke DEFAULT_ONTOLOGY jika LLM gagal.
    """
    try:
        resp = llm.invoke(_ONTOLOGY_PROMPT.format(objective=CORE_OBJECTIVE))
        content = resp.content if hasattr(resp, "content") else str(resp)
        nodes = _extract_json_array(content)
        if nodes:
            logger.info("Ontologi LLM berhasil: %d node", len(nodes))
            return nodes
        logger.warning("Output ontologi tidak dapat diparse — pakai default")
    except Exception as exc:
        logger.warning("LLM gagal untuk ontologi (%s) — pakai default", exc)
    return DEFAULT_ONTOLOGY
