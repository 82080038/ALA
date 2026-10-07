"""
ALA — Autonomous Legal Agent
Titik masuk aplikasi FastAPI
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Konfigurasi logging root agar log agen (ala.*) terlihat di docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_v1_router
from app.config import hw, print_hardware_report, settings
from app.middleware.tenant import TenantIsolationMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Siklus hidup aplikasi — cetak profil hardware saat startup."""
    print_hardware_report()
    yield


app = FastAPI(
    title="Autonomous Legal Agent (ALA)",
    description="Sistem intelijen hukum berbasis AI untuk Aparat Penegak Hukum (APH) Indonesia",
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(TenantIsolationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Endpoint pemeriksaan kesehatan untuk Docker dan load balancer."""
    import httpx
    ollama_status = "unknown"
    ollama_models = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                ollama_status = "connected"
                ollama_models = [m["name"] for m in resp.json().get("models", [])]
            else:
                ollama_status = "error"
    except Exception:
        ollama_status = "unreachable"
    return {
        "status": "healthy",
        "service": "ala-api",
        "version": "0.3.0",
        "llm_provider": "ollama (lokal)",
        "ollama_status": ollama_status,
        "ollama_models": ollama_models,
        "hardware": {
            "cpu_cores": hw.cpu_cores_logical,
            "max_workers": hw.cpu_max_workers,
            "ram_total_gb": hw.ram_total_gb,
            "cuda_available": hw.cuda_available,
            "cuda_device_count": hw.cuda_device_count,
            "device_target": hw.device,
            "ollama_num_ctx": hw.ollama_num_ctx,
            "ollama_num_predict": hw.ollama_num_predict,
            "sandbox_mem_limit_mb": hw.sandbox_mem_limit_mb,
        },
    }
