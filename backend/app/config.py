"""
Konfigurasi aplikasi dimuat dari variabel lingkungan.
Termasuk: Hardware Intelligence & Resource Optimizer (HIRO).
"""
import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("ala.config")

# Host shell dapat mengekspor DEBUG=release (non-boolean) — pydantic_settings
# memprioritaskan env var atas .env dan akan menolak nilai itu. Normalisasi
# sebelum Settings() diinstansiasi (pola yang sama dipakai tests/conftest.py).
if os.environ.get("DEBUG", "").lower() not in {
    "true", "false", "1", "0", "yes", "no", "on", "off",
}:
    os.environ["DEBUG"] = "false"


# ---------------------------------------------------------------------------
# Hardware Intelligence & Resource Optimizer (HIRO)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HardwareProfile:
    """Profil perangkat keras yang terdeteksi saat startup."""

    # CPU
    cpu_cores_logical: int = 0
    cpu_max_workers: int = 1

    # RAM (bytes)
    ram_total_bytes: int = 0
    ram_available_bytes: int = 0
    sandbox_mem_limit_bytes: int = 0

    # GPU / CUDA
    cuda_available: bool = False
    cuda_device_count: int = 0
    cuda_devices: tuple = field(default_factory=tuple)
    cuda_total_vram_mb: int = 0

    # Target perangkat untuk embedding & inferensi
    device: str = "cpu"

    # Parameter Ollama yang dioptimalkan berdasarkan VRAM
    ollama_num_ctx: int = 2048
    ollama_num_predict: int = 512

    @property
    def ram_total_gb(self) -> float:
        return round(self.ram_total_bytes / (1024 ** 3), 1)

    @property
    def ram_available_gb(self) -> float:
        return round(self.ram_available_bytes / (1024 ** 3), 1)

    @property
    def sandbox_mem_limit_mb(self) -> int:
        return self.sandbox_mem_limit_bytes // (1024 ** 2)


def _detect_cuda() -> dict:
    """Deteksi GPU NVIDIA CUDA. Fallback aman jika torch tidak tersedia."""
    result = {
        "available": False,
        "device_count": 0,
        "devices": [],
        "total_vram_mb": 0,
    }
    try:
        import torch
        if torch.cuda.is_available():
            result["available"] = True
            count = torch.cuda.device_count()
            result["device_count"] = count
            total_vram = 0
            for i in range(count):
                props = torch.cuda.get_device_properties(i)
                vram_mb = props.total_memory // (1024 ** 2)
                total_vram += vram_mb
                result["devices"].append({
                    "index": i,
                    "name": props.name,
                    "vram_mb": vram_mb,
                })
            result["total_vram_mb"] = total_vram
    except ImportError:
        # torch belum terinstall (Fase 1 build ringan) — fallback ke cek env
        nvidia_visible = os.environ.get("NVIDIA_VISIBLE_DEVICES", "")
        cuda_version = os.environ.get("CUDA_VERSION", "")
        if nvidia_visible or cuda_version:
            result["available"] = True
            result["device_count"] = 1
            result["devices"].append({
                "index": 0,
                "name": f"NVIDIA (env: CUDA_VERSION={cuda_version})",
                "vram_mb": 0,
            })
    except Exception as exc:
        logger.warning("Deteksi CUDA gagal: %s", exc)
    return result


def _detect_ram() -> dict:
    """Deteksi RAM sistem — lintas-platform (Linux, Windows, macOS)."""
    total = 0
    available = 0
    current_os = platform.system()
    try:
        if current_os == "Linux":
            # Linux: baca /proc/meminfo
            mem_info_path = Path("/proc/meminfo")
            if mem_info_path.exists():
                info = {}
                with mem_info_path.open() as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            info[parts[0].rstrip(":")] = int(parts[1]) * 1024
                total = info.get("MemTotal", 0)
                available = info.get("MemAvailable", info.get("MemFree", 0))
        elif current_os == "Windows":
            # Windows: gunakan kernel32.GlobalMemoryStatusEx via ctypes
            import ctypes
            import ctypes.wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.wintypes.DWORD),
                    ("dwMemoryLoad", ctypes.wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = stat.ullTotalPhys
            available = stat.ullAvailPhys
        else:
            # macOS / fallback: shutil (kurang akurat, tapi portabel)
            usage = shutil.disk_usage("/")
            total = usage.total
            available = usage.free
    except Exception as exc:
        logger.warning("Deteksi RAM gagal (%s): %s", current_os, exc)
    return {"total": total, "available": available}


def _optimal_ollama_params(vram_mb: int) -> dict:
    """Hitung parameter Ollama optimal berdasarkan VRAM yang tersedia."""
    if vram_mb >= 8000:
        return {"num_ctx": 8192, "num_predict": 4096}
    elif vram_mb >= 4000:
        # num_predict ≥2048 — skrip utuh butuh ruang generate yang cukup;
        # prediksi panjang tidak membebani VRAM sebesar konteks
        return {"num_ctx": 4096, "num_predict": 2048}
    elif vram_mb >= 2000:
        return {"num_ctx": 2048, "num_predict": 1024}
    else:
        # CPU fallback atau VRAM sangat terbatas
        return {"num_ctx": 2048, "num_predict": 512}


def profile_hardware() -> HardwareProfile:
    """Profil seluruh sumber daya perangkat keras host/kontainer."""

    # --- CPU ---
    cores = os.cpu_count() or 1
    max_workers = max(1, cores - 1)

    # --- RAM ---
    ram = _detect_ram()
    ram_total = ram["total"]
    ram_avail = ram["available"]
    sandbox_limit = ram_total // 4  # maks 25% RAM host

    # --- CUDA / GPU ---
    cuda = _detect_cuda()
    device = "cuda" if cuda["available"] else "cpu"

    # --- Parameter Ollama ---
    # Ceiling num_ctx memakai VRAM GPU TERBESAR TUNGGAL (bukan total) —
    # tiap model hidup utuh di satu GPU; menjumlah VRAM antar-GPU akan
    # meng-overcommit konteks dan memicu OOM pada kartu 4 GB.
    max_single_vram = max(
        (d["vram_mb"] for d in cuda["devices"]), default=0
    )
    ollama_params = _optimal_ollama_params(max_single_vram)

    return HardwareProfile(
        cpu_cores_logical=cores,
        cpu_max_workers=max_workers,
        ram_total_bytes=ram_total,
        ram_available_bytes=ram_avail,
        sandbox_mem_limit_bytes=sandbox_limit,
        cuda_available=cuda["available"],
        cuda_device_count=cuda["device_count"],
        cuda_devices=tuple(
            (d["index"], d["name"], d["vram_mb"]) for d in cuda["devices"]
        ),
        cuda_total_vram_mb=cuda["total_vram_mb"],
        device=device,
        ollama_num_ctx=ollama_params["num_ctx"],
        ollama_num_predict=ollama_params["num_predict"],
    )


# Profil singleton — dihitung sekali saat modul dimuat
hw: HardwareProfile = profile_hardware()


def print_hardware_report() -> None:
    """Cetak Laporan Profil Perangkat Keras ke log konsol."""
    border = "=" * 60
    lines = [
        "",
        border,
        "  🖥️  LAPORAN PROFIL PERANGKAT KERAS (HIRO)",
        border,
        f"  Prosesor        : {hw.cpu_cores_logical} core logis",
        f"  Worker paralel  : {hw.cpu_max_workers} (cpu_count - 1)",
        f"  RAM Total       : {hw.ram_total_gb} GB",
        f"  RAM Tersedia    : {hw.ram_available_gb} GB",
        f"  Batas Sandbox   : {hw.sandbox_mem_limit_mb} MB (25% RAM)",
        "  " + "-" * 56,
        f"  CUDA Tersedia   : {'✅ Ya' if hw.cuda_available else '❌ Tidak (mode CPU)'}",
        f"  Jumlah GPU      : {hw.cuda_device_count}",
    ]
    for idx, name, vram in hw.cuda_devices:
        lines.append(f"    GPU {idx}         : {name} — {vram} MB VRAM")
    lines.extend([
        f"  Total VRAM      : {hw.cuda_total_vram_mb} MB",
        f"  Target Perangkat: {hw.device.upper()}",
        "  " + "-" * 56,
        f"  Ollama num_ctx     : {hw.ollama_num_ctx}",
        f"  Ollama num_predict : {hw.ollama_num_predict}",
        "  " + "-" * 56,
        f"  Reasoning → GPU 0  : {settings.ollama_model_reasoning} "
        f"@ {get_ollama_reasoning_url()}",
        f"  Coder     → GPU 1  : {settings.ollama_model_coder} "
        f"@ {get_ollama_coder_url()}",
        border,
        "",
    ])
    report = "\n".join(lines)
    logger.info(report)
    # Juga cetak ke stdout agar terlihat di docker logs
    print(report)


# ---------------------------------------------------------------------------
# Settings Aplikasi
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    # PostgreSQL
    # database_url        → role APLIKASI non-superuser (RLS ditegakkan)
    # database_admin_url  → role superuser, HANYA untuk init/migrasi DDL
    database_url: str = "postgresql://ala_app:password@localhost:5432/ala_db"
    database_admin_url: str = ""  # kosong → fallback ke database_url

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # Ollama (LLM Lokal — dual-instance GPU pinning)
    # Instance #1 :11434 → GPU 0 (qwen2.5:3b-instruct, Agen 0–2)
    # Instance #2 :11435 → GPU 1 (qwen2.5-coder:3b, Agen 3)
    ollama_base_url: str = "http://host.docker.internal:11434"  # legacy fallback
    ollama_reasoning_url: str = ""   # kosong → fallback ke ollama_base_url
    ollama_coder_url: str = ""       # kosong → fallback ke reasoning URL
    ollama_model_reasoning: str = "qwen2.5:3b-instruct"
    ollama_model_coder: str = "qwen2.5-coder:3b"
    ollama_temperature_reasoning: float = 0.2
    ollama_temperature_coder: float = 0.1

    # Embedding retrieval (ingest + query harus model yang sama).
    # Default multilingual-e5-small (384-dim). Upgrade path
    # (benchmark HuggingFace untuk Bahasa Indonesia):
    #   - LazarusNLP/all-indo-e5-small-v4 : drop-in 384-dim, dilatih
    #     khusus Indonesia — RECOMMENDED upgrade pertama.
    #   - BAAI/bge-m3 (atau alphaedge-ai/bge-m3-ind-* yang dipangkas):
    #     1024-dim, native dense+sparse, lebih kuat tapi lebih berat.
    # WAJIB: ganti model = ruang vektor berubah → kosongkan koleksi
    # Chroma `indonesian_laws` dan re-embed ulang seluruh korpus
    # (jalankan bootstrap ALCD ulang). Mencampur vektor beda model
    # merusak retrieval diam-diam.
    embedding_model: str = "intfloat/multilingual-e5-small"

    # Reranker cross-encoder lokal (zero-cost). Default multilingual-mMARCO
    # MiniLM — layak di CPU. Upgrade ke BAAI/bge-reranker-v2-m3 (lebih kuat
    # untuk Bahasa Indonesia) bila torch CUDA tersedia.
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_top: int = 48
    # Snapshot indeks BM25 ke disk — hindari rebuild penuh tiap cold-start
    # (kritis saat korpus >100K chunk). Invalidasi otomatis via count koleksi
    # + penghapusan eksplisit setelah ingest.
    bm25_index_path: str = str(Path.home() / ".chroma" / "bm25_index.pkl")

    # Google Custom Search (opsional — discovery dokumen publik ALCD/crawler)
    google_cse_id: str = ""
    google_cse_api_key: str = ""

    # JWT — HS256 lokal, zero-cost (tanpa provider eksternal)
    jwt_secret: str = "change_me"
    jwt_expiry_hours: int = 24
    # Fallback header X-User-Role/X-Institution-ID untuk pengembangan
    # lokal standalone. WAJIB false di deployment nyata.
    auth_dev_headers: bool = True

    # ALCD
    alcd_enabled: bool = True
    alcd_min_readiness_score: float = 0.8
    alcd_self_eval_threshold: float = 0.7
    alcd_schedule_interval: str = "168h"
    alcd_max_concurrent_crawls: int = 3
    alcd_trusted_domains: str = "jdih.kemenkumham.go.id,peraturan.bpk.go.id,putusan3.mahkamahagung.go.id"
    alcd_crawl_rate_limit: int = 1
    # OCR fallback untuk PDF scan tanpa text-layer (UU 1/2023 dsb.) —
    # butuh ocrmypdf + tesseract bahasa 'ind' terpasang di host.
    alcd_ocr_enabled: bool = True
    # Serap korpus yang sudah diverifikasi proyek lain (SPKT sqlite,
    # LexisAI chroma) sebagai saluran akuisisi — path via env
    # SPKT_DB_PATH / LEXISAI_CHROMA_PATH.
    alcd_import_external: bool = True
    # Doktrin fondasi ilmu hukum (asas, teori, metode) digenerate LLM
    # sebagai lapisan konseptual — ditandai kategori 'doktrin'.
    alcd_doctrine_enabled: bool = True

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "info"
    debug: bool = False
    db_echo: bool = False  # echo SQLAlchemy ke log (DEBUG terpisah dari DEBUG app)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()


# ---------------------------------------------------------------------------
# SaaS Token Tiering — batas konteks per tier_level
# ---------------------------------------------------------------------------

# Batas maksimum PERMINTAAN per tier. Nilai efektif selalu diklamp oleh
# ceiling hardware HIRO (VRAM 4 GB → num_ctx maks 4096).
TIER_TOKEN_LIMITS: dict[str, dict[str, int]] = {
    "free":       {"num_ctx": 2048,  "num_predict": 512},
    "premium_l1": {"num_ctx": 8192,  "num_predict": 2048},
    "premium_l2": {"num_ctx": 16384, "num_predict": 4096},
}

# Tier internal untuk pekerjaan latar (ALCD dsb.) — pakai ceiling hardware penuh
_INTERNAL_TIER = "premium_l2"


def get_context_budget(tier_level: str) -> dict[str, int]:
    """Batas token efektif = min(tier_cap, hardware_ceiling_HIRO).

    Args:
        tier_level: `free`, `premium_l1`, atau `premium_l2` dari users.tier_level.

    Returns:
        Dict `{"num_ctx": int, "num_predict": int}` siap dipakai ChatOllama.
    """
    caps = TIER_TOKEN_LIMITS.get(tier_level, TIER_TOKEN_LIMITS["free"])
    return {
        "num_ctx": min(caps["num_ctx"], hw.ollama_num_ctx),
        "num_predict": min(caps["num_predict"], hw.ollama_num_predict),
    }


# ---------------------------------------------------------------------------
# LLM & Embedding Factory Functions
# ---------------------------------------------------------------------------

def get_ollama_reasoning_url() -> str:
    """URL instance Ollama penalaran (GPU 0 — :11434)."""
    return settings.ollama_reasoning_url or settings.ollama_base_url


def get_ollama_coder_url() -> str:
    """URL instance Ollama coder (GPU 1 — :11435). Fallback ke reasoning."""
    return settings.ollama_coder_url or get_ollama_reasoning_url()


def get_llm_reasoning(tier_level: str = _INTERNAL_TIER):
    """Dapatkan LLM penalaran hukum (Agen 0-2) via Ollama GPU 0 (:11434)."""
    from langchain_ollama import ChatOllama
    budget = get_context_budget(tier_level)
    return ChatOllama(
        model=settings.ollama_model_reasoning,
        base_url=get_ollama_reasoning_url(),
        temperature=settings.ollama_temperature_reasoning,
        num_ctx=budget["num_ctx"],
        num_predict=budget["num_predict"],
    )


def get_llm_coder(tier_level: str = _INTERNAL_TIER):
    """Dapatkan LLM pembuatan kode (Agen 3) via Ollama GPU 1 (:11435)."""
    from langchain_ollama import ChatOllama
    budget = get_context_budget(tier_level)
    return ChatOllama(
        model=settings.ollama_model_coder,
        base_url=get_ollama_coder_url(),
        temperature=settings.ollama_temperature_coder,
        num_ctx=budget["num_ctx"],
        num_predict=budget["num_predict"],
    )


def get_embedding_device() -> str:
    """Dapatkan target perangkat untuk model embedding HuggingFace."""
    return hw.device


def get_max_workers() -> int:
    """Dapatkan jumlah worker paralel optimal untuk crawling/indexing."""
    return hw.cpu_max_workers


def get_sandbox_mem_limit() -> str:
    """Dapatkan batas memori sandbox sebagai string Docker (misal '512m')."""
    return f"{hw.sandbox_mem_limit_mb}m"
