"""
Synthesis & Developer Agent — Agent 3.

Menghubungkan landasan hukum (Agent 1) dengan tren kejahatan riil
(Agent 2), lalu menghasilkan kode utilitas + flowchart workflow.
Menggunakan model coder `qwen2.5-coder:3b` pada GPU 1.

KEPATUHAN RANTAI PENGUNGKAPAN (KUHAP): setiap kode yang menyentuh file
bukti WAJIB memakai scaffold read-only + SHA-256 sebelum/sesudah —
dokumen mentah tidak boleh pernah dimutasi.
"""
import logging
import re
from datetime import datetime, timezone

from app.config import get_llm_coder

logger = logging.getLogger("ala.agents.code_generator")

# ---------------------------------------------------------------------------
# Scaffold rantai pengungkapan — SELALU diinjeksi ke prompt jika kode
# menyentuh file bukti (parser, extractor, analyzer, reader).
# ---------------------------------------------------------------------------
CUSTODY_SCAFFOLD = '''import hashlib

def _sha256(path: str) -> str:
    """SHA-256 file bukti — integritas untuk persidangan (KUHAP)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:  # READ-ONLY — jangan pernah mode tulis
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def _custody_open(path: str):
    """Buka bukti READ-ONLY; kembalikan (file, hash_sebelum)."""
    before = _sha256(path)
    return open(path, "rb"), before

def _custody_close(fh, path: str, before: str) -> dict:
    """Tutup bukti; verifikasi hash tidak berubah; catat custody."""
    fh.close()
    after = _sha256(path)
    record = {
        "evidence_file": path,
        "sha256_before": before,
        "sha256_after": after,
        "integrity_verified": before == after,
    }
    if before != after:
        raise RuntimeError(
            f"INTEGRITAS BUKTI GAGAL: {path} berubah saat diproses!")
    return record
'''

_SYNTH_PROMPT = """Anda adalah analis hukum senior Indonesia.
Sintesiskan landasan hukum berikut dengan tren kejahatan riil.

QUERY: {query}

LANDASAN HUKUM:
{legal_context}

TREN KEJAHATAN:
{crime_summary}

Balas HANYA JSON:
{{
  "gaps": ["celah regulasi atau strategi"],
  "strategy": "strategi penindakan dalam 2-3 kalimat",
  "relevant_laws": ["UU/pasal yang paling relevan"]
}}"""

_CODE_PROMPT = """Anda adalah engineer Python senior untuk lembaga
penegak hukum Indonesia.

KONTEKS:
Query: {query}
Strategi: {strategy}
Tren: {crime_summary}

{custody_rules}

Tugas: hasilkan SATU skrip utilitas Python yang membantu penyelidik
untuk kasus ini, plus flowchart Mermaid sederhana.

Balas HANYA JSON:
{{
  "filename": "nama_file.py",
  "language": "python",
  "description": "deskripsi singkat",
  "code": "kode python lengkap",
  "flowchart": "graph TD\\n    A[Mulai] --> B[...]"
}}

Aturan keras kode:
- Hanya stdlib + library umum (pandas, openpyxl, python-docx)
- TANPA jaringan, TANPA eval/exec, TANPA os.system/subprocess
- File bukti hanya dibaca ("rb") — TIDAK PERNAH ditulis
{custody_block}"""

_EVIDENCE_KEYWORDS = re.compile(
    r"(bukti|evidence|parse|ekstrak|extract|analisis|analyze|log|"
    r"dump|file|dokumen|scan|baca)", re.IGNORECASE)


def _extract_json(text: str):
    import json

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Fallback: JSON terpotong (num_predict habis di tengah "code").
    # Ambil field string "code" secara manual — string bisa tak tertutup.
    m = re.search(r'"code"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.DOTALL)
    if m:
        raw = m.group(1)
        try:
            code = json.loads(f'"{raw}"')  # unescape \\n, \\t, dsb.
        except json.JSONDecodeError:
            code = raw.replace("\\n", "\n").replace('\\"', '"')
        return {"code": code, "language": "python", "filename": "utility.py"}
    return None


def _legal_context_text(state) -> str:
    parts = []
    for art in (state.get("legal_articles") or [])[:6]:
        parts.append(
            f"[{art.get('law_name')} {art.get('article_number')}] "
            f"{art.get('content', '')[:300]}"
        )
    for xref in (state.get("cross_references") or [])[:4]:
        targets = ", ".join(
            f"{t.get('law', '')} {t.get('article', '')}".strip()
            for t in (xref.get("to") or [])
        )
        parts.append(
            f"XREF {xref.get('from_law', '')} "
            f"{xref.get('from_article', '')} → {targets}"
        )
    return "\n".join(parts)


def _needs_custody(code: str, description: str) -> bool:
    """Deteksi apakah kode menyentuh file bukti → scaffold wajib."""
    text = f"{description}\n{code}"
    return bool(_EVIDENCE_KEYWORDS.search(text))


def _inject_custody(code: str) -> str:
    """Pastikan scaffold custody ada; inject jika belum."""
    if "def _sha256(" in code or "def _custody_open(" in code:
        return code
    return CUSTODY_SCAFFOLD + "\n\n" + code


def synthesis_developer_agent(state) -> dict:
    """Node LangGraph: sintesis hukum×tren + generate kode utilitas."""
    audit = {
        "agent": "synthesis_developer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    updates: dict = {"audit_trail": [audit]}
    query = state.get("query", "")
    legal_ctx = _legal_context_text(state)
    crime_summary = state.get("crime_summary", "")

    # ── Sintesis hukum × tren ───────────────────────────────────────
    try:
        llm_coder = get_llm_coder()
        resp = llm_coder.invoke(_SYNTH_PROMPT.format(
            query=query, legal_context=legal_ctx[:4000],
            crime_summary=crime_summary[:2000]))
        synthesis = _extract_json(
            resp.content if hasattr(resp, "content") else str(resp)
        ) or {}
    except Exception as exc:
        logger.warning("Sintesis gagal: %s", exc)
        synthesis = {}
    synthesis.setdefault("query", query)
    updates["synthesis"] = synthesis

    # ── Generate kode ────────────────────────────────────────────────
    strategy = synthesis.get("strategy", "")
    custody_rules = ""
    custody_block = ""
    if _needs_custody(query + strategy, query):
        custody_rules = (
            "Kode ini AKAN menyentuh file bukti. WAJIB gunakan scaffold "
            "rantai pengungkapan yang disediakan — bukti dibuka via "
            "`_custody_open()` (read-only) dan hash diverifikasi via "
            "`_custody_close()`."
        )
        custody_block = (
            "- WAJIB sertakan scaffold berikut PERSIS apa adanya "
            "di atas kode:\n" + CUSTODY_SCAFFOLD
        )

    try:
        resp = llm_coder.invoke(_CODE_PROMPT.format(
            query=query, strategy=strategy,
            crime_summary=crime_summary[:1500],
            custody_rules=custody_rules, custody_block=custody_block))
        out = _extract_json(
            resp.content if hasattr(resp, "content") else str(resp)
        ) or {}
    except Exception as exc:
        logger.exception("Code generation error")
        audit.update(status="error", error=str(exc))
        updates["errors"] = [f"Synthesis & Developer Agent error: {exc}"]
        return updates

    code = out.get("code", "")
    # Enforce custody jika kode menyentuh bukti
    if code and _needs_custody(code, out.get("description", "")):
        code = _inject_custody(code)

    # Validasi sintaks SEKARANG — kode terpotong (num_predict habis) atau
    # malformed tidak layak diajukan ke persetujuan manusia.
    syntax_valid = True
    if code:
        import ast
        try:
            ast.parse(code)
        except SyntaxError as exc:
            syntax_valid = False
            updates.setdefault("errors", [])
            updates["errors"] = updates["errors"] + [
                f"Kode hasil AI tidak valid (SyntaxError baris "
                f"{exc.lineno}: {exc.msg}) — kemungkinan terpotong limit "
                f"token tier. Coba query ulang atau naikkan tier."
            ]
            logger.warning("Kode hasil AI gagal ast.parse: %s", exc)

    updates["generated_output"] = {
        "filename": out.get("filename", "utility.py"),
        "language": out.get("language", "python"),
        "description": out.get("description", ""),
        "code": code,
        "flowchart": out.get("flowchart", ""),
        "syntax_valid": syntax_valid,
    }
    audit.update(
        status="success",
        filename=out.get("filename"),
        code_lines=code.count("\n") + 1 if code else 0,
        custody_enforced=bool(code and "_sha256(" in code),
    )
    return updates
