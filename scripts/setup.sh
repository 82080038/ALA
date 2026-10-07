#!/usr/bin/env bash
# ============================================================
#  ALA — Skrip Setup Lingkungan (Linux / macOS)
# ============================================================
#  Penggunaan: chmod +x scripts/setup.sh && ./scripts/setup.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "╔════════════════════════════════════════════════════════╗"
echo "║  ALA — Autonomous Legal Agent — Setup Lingkungan      ║"
echo "║  Platform: $(uname -s) $(uname -m)                           "
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# --- 1. Periksa prasyarat ---
echo "[1/5] Memeriksa prasyarat..."

command -v docker >/dev/null 2>&1 || { echo "❌ Docker tidak ditemukan. Install: https://docs.docker.com/get-docker/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "❌ Docker Compose tidak ditemukan. Install: https://docs.docker.com/compose/install/"; exit 1; }

echo "  ✅ Docker: $(docker --version)"
echo "  ✅ Docker Compose: $(docker compose version)"

# Periksa Ollama (opsional, tapi direkomendasikan)
if command -v ollama >/dev/null 2>&1; then
    echo "  ✅ Ollama: $(ollama --version 2>/dev/null || echo 'terinstall')"
else
    echo "  ⚠️  Ollama tidak ditemukan. Install: https://ollama.com/download"
    echo "      Ollama diperlukan untuk inferensi LLM lokal."
fi

# --- 2. File .env ---
echo ""
echo "[2/5] Memeriksa file .env..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "  📄 Menyalin .env.example → .env"
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  ⚠️  Edit .env dan ganti password default sebelum deploy produksi!"
else
    echo "  ✅ .env sudah ada"
fi

# --- 3. Konfigurasi khusus Linux ---
echo ""
echo "[3/5] Konfigurasi khusus platform..."

if [ "$(uname -s)" = "Linux" ]; then
    echo "  🐧 Linux terdeteksi"

    # Periksa apakah Ollama mendengarkan di 0.0.0.0
    if command -v ollama >/dev/null 2>&1; then
        if systemctl is-active --quiet ollama 2>/dev/null; then
            OLLAMA_HOST_CFG=$(systemctl show ollama --property=Environment 2>/dev/null || echo "")
            if echo "$OLLAMA_HOST_CFG" | grep -q "OLLAMA_HOST=0.0.0.0"; then
                echo "  ✅ Ollama sudah dikonfigurasi untuk mendengarkan di 0.0.0.0"
            else
                echo "  ⚠️  Ollama mungkin hanya mendengarkan di 127.0.0.1."
                echo "      Untuk akses dari Docker, buat override systemd:"
                echo "      sudo mkdir -p /etc/systemd/system/ollama.service.d"
                echo "      echo -e '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0' | sudo tee /etc/systemd/system/ollama.service.d/override.conf"
                echo "      sudo systemctl daemon-reload && sudo systemctl restart ollama"
            fi
        fi
    fi

    # Periksa NVIDIA Container Toolkit (untuk GPU passthrough)
    if command -v nvidia-smi >/dev/null 2>&1; then
        echo "  ✅ NVIDIA GPU terdeteksi: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
        if dpkg -l nvidia-container-toolkit >/dev/null 2>&1; then
            echo "  ✅ NVIDIA Container Toolkit terinstall"
        else
            echo "  ⚠️  NVIDIA Container Toolkit belum terinstall."
            echo "      Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
        fi
    else
        echo "  ℹ️  Tidak ada GPU NVIDIA — sistem akan berjalan di mode CPU"
    fi
else
    echo "  🍎 macOS terdeteksi — Docker Desktop menangani host.docker.internal secara native"
fi

# --- 4. Tarik model Ollama ---
echo ""
echo "[4/5] Memeriksa model Ollama..."

if command -v ollama >/dev/null 2>&1; then
    for MODEL in "qwen2.5:3b-instruct" "qwen2.5-coder:3b"; do
        if ollama list 2>/dev/null | grep -q "$MODEL"; then
            echo "  ✅ Model $MODEL sudah tersedia"
        else
            echo "  ⬇️  Mengunduh model $MODEL..."
            ollama pull "$MODEL"
        fi
    done
else
    echo "  ⏭️  Melewati — Ollama tidak terinstall"
fi

# --- 5. Bangun dan jalankan kontainer ---
echo ""
echo "[5/5] Membangun dan menjalankan kontainer Docker..."

cd "$PROJECT_DIR"
docker compose up -d --build

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ Setup selesai!                                     ║"
echo "║                                                        ║"
echo "║  Layanan:                                              ║"
echo "║    API:       http://localhost:8080                     ║"
echo "║    Frontend:  http://localhost:3000                     ║"
echo "║    Docs:      http://localhost:8080/docs                ║"
echo "║    Neo4j:     http://localhost:7474                     ║"
echo "║    ChromaDB:  http://localhost:8001                     ║"
echo "║                                                        ║"
echo "║  Periksa kesehatan: curl http://localhost:8080/health   ║"
echo "╚════════════════════════════════════════════════════════╝"
