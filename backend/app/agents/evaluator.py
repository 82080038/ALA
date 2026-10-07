"""
Self-Evaluation & Feature Clustering Agent.

Dua tanggung jawab:
1. Evaluasi diri ALCD — generate pertanyaan uji per node ontologi, query
   RAG pipeline sendiri, skor jawaban via LLM-as-judge (0.0–1.0), catat
   gap ke `self_eval_logs` untuk re-research.
2. Klasterisasi fitur SaaS — menilai kompleksitas + beban CUDA alat yang
   digenerate AI lalu menyarankan tier akses (free / premium_l1 /
   premium_l2) untuk divalidasi Super Admin.
"""
import json
import logging
import re
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("ala.agents.evaluator")

_QUIZ_PROMPT = """Berdasarkan topik "{topic}", buat 3 pertanyaan uji singkat
tentang hukum Indonesia yang harus bisa dijawab sistem. Balas HANYA JSON
array string: ["pertanyaan 1", "pertanyaan 2", "pertanyaan 3"]"""

_JUDGE_PROMPT = """Pertanyaan: {question}
Jawaban sistem: {answer}

Nilai kualitas jawaban dari 0.0 sampai 1.0 berdasarkan kebenaran hukum,
kelengkapan, dan relevansi. Balas HANYA angka desimal."""

_CLUSTER_PROMPT = """Nilai alat AI berikut untuk platform SaaS APH:
Nama: {name}
Deskripsi: {description}
Jumlah baris kode: {lines}

Balas HANYA JSON: {{"complexity": 0.0-1.0, "cuda_weight": 0.0-1.0}}
complexity = kedalaman penalaran hukum & jumlah langkah.
cuda_weight = estimasi beban GPU saat alat dijalankan."""


def _extract_json(text: str):
    match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _score_answer(llm, question: str, answer: str) -> float:
    """LLM-as-judge — kembalikan skor 0.0–1.0."""
    try:
        resp = llm.invoke(_JUDGE_PROMPT.format(
            question=question, answer=answer[:2000]))
        text = resp.content if hasattr(resp, "content") else str(resp)
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            return max(0.0, min(1.0, float(match.group(1))))
    except Exception as exc:
        logger.warning("Judge gagal: %s", exc)
    return 0.0


def evaluate_node(llm, node: dict, rag_answer_fn, db) -> dict:
    """Evaluasi satu node ontologi via self-quiz + RAG + LLM-as-judge.

    Args:
        llm: model penalaran.
        node: dict ontologi (category/subcategory).
        rag_answer_fn: callable(question: str) -> str — pipeline RAG sendiri.
        db: SQLAlchemy session untuk self_eval_logs.

    Returns:
        {"topic", "score", "gaps": [pertanyaan yang lemah]}
    """
    from app.models.operational import SelfEvalLog

    topic = node.get("subcategory") or node.get("category", "")
    questions = [f"Jelaskan ruang lingkup {topic} menurut hukum Indonesia."]
    try:
        resp = llm.invoke(_QUIZ_PROMPT.format(topic=topic))
        parsed = _extract_json(
            resp.content if hasattr(resp, "content") else str(resp))
        if isinstance(parsed, list) and parsed:
            questions = [str(q) for q in parsed[:5]]
    except Exception as exc:
        logger.warning("Quiz generation gagal: %s", exc)

    scores, gaps = [], []
    for q in questions:
        try:
            answer = rag_answer_fn(q)
        except Exception as exc:
            answer = ""
            logger.warning("RAG jawab gagal: %s", exc)
        score = _score_answer(llm, q, answer)
        scores.append(score)
        db.add(SelfEvalLog(
            ontology_node_id=node.get("id"),
            question=q,
            generated_answer=answer[:4000],
            answer_quality=score,
            gap_description=(
                None if score >= settings.alcd_self_eval_threshold
                else f"Skor {score:.2f} < {settings.alcd_self_eval_threshold} "
                     f"untuk topik {topic}"
            ),
            remediation_action=(
                None if score >= settings.alcd_self_eval_threshold
                else "re-research terjadwal"
            ),
            resolved=score >= settings.alcd_self_eval_threshold,
            resolved_at=(
                datetime.now(timezone.utc)
                if score >= settings.alcd_self_eval_threshold else None
            ),
        ))
        if score < settings.alcd_self_eval_threshold:
            gaps.append(q)
    db.commit()

    avg = sum(scores) / len(scores) if scores else 0.0
    return {"topic": topic, "score": round(avg, 3), "gaps": gaps}


def classify_feature(llm, name: str, description: str, code: str) -> dict:
    """Klasterisasi fitur AI — kompleksitas, beban CUDA, saran tier.

    Mapping tier (PROMPTING.md §SaaS):
      < 0.3 → free | 0.3–0.7 → premium_l1 | > 0.7 → premium_l2
    """
    defaults = {"ai_complexity_score": 0.5, "ai_cuda_weight": 0.5,
                "ai_suggested_tier": "premium_l1"}
    try:
        resp = llm.invoke(_CLUSTER_PROMPT.format(
            name=name, description=description,
            lines=code.count("\n") + 1))
        parsed = _extract_json(
            resp.content if hasattr(resp, "content") else str(resp))
        if isinstance(parsed, dict):
            complexity = max(0.0, min(1.0, float(
                parsed.get("complexity", 0.5))))
            cuda = max(0.0, min(1.0, float(parsed.get("cuda_weight", 0.5))))
        else:
            complexity, cuda = 0.5, 0.5
    except Exception as exc:
        logger.warning("Clustering LLM gagal: %s", exc)
        return defaults

    if complexity < 0.3:
        tier = "free"
    elif complexity <= 0.7:
        tier = "premium_l1"
    else:
        tier = "premium_l2"
    return {
        "ai_complexity_score": round(complexity, 3),
        "ai_cuda_weight": round(cuda, 3),
        "ai_suggested_tier": tier,
    }
