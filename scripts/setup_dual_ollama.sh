#!/usr/bin/env bash
# ============================================================
#  ALA — Dual-GPU Ollama Setup (2x GTX 1050 Ti 4GB)
# ============================================================
#  Mengkonfigurasi DUA instance Ollama yang terisolasi per GPU:
#    Instance #1 (ollama.service)       :11434 → GPU 0
#      model: qwen2.5:3b-instruct (penalaran, Agen 0–2)
#    Instance #2 (ollama-coder.service) :11435 → GPU 1
#      model: qwen2.5-coder:3b (generate kode, Agen 3)
#
#  Penggunaan: sudo ./scripts/setup_dual_ollama.sh
# ============================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Jalankan dengan sudo: sudo $0"
    exit 1
fi

echo "╔════════════════════════════════════════════════════════╗"
echo "║  ALA — Dual-GPU Ollama Setup                          ║"
echo "╚════════════════════════════════════════════════════════╝"

# --- 1. Verifikasi GPU ---
echo "[1/4] Memverifikasi GPU..."
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_COUNT=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
    if [ "$GPU_COUNT" -lt 2 ]; then
        echo "  ⚠️  Hanya $GPU_COUNT GPU terdeteksi — instance kedua akan "
        echo "      dibagikan ke GPU 0 (fallback aman, performa menurun)."
    fi
else
    echo "  ⚠️  nvidia-smi tidak ditemukan — lanjut dengan asumsi 2 GPU."
fi

# --- 2. Override instance utama: pin ke GPU 0 ---
echo "[2/4] Mem-pin ollama.service (:11434) ke GPU 0..."
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
# GPU pinning — model penalaran hanya boleh di GPU 0
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF
echo "  ✅ /etc/systemd/system/ollama.service.d/override.conf"

# --- 3. Instance coder: GPU 1 di port 11435 ---
echo "[3/4] Membuat ollama-coder.service (:11435) ke GPU 1..."
cat > /etc/systemd/system/ollama-coder.service <<'EOF'
[Unit]
Description=Ollama Coder Service — GPU 1 (qwen2.5-coder:3b, port 11435)
After=network-online.target ollama.service

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin"
Environment="OLLAMA_HOST=0.0.0.0:11435"
# GPU pinning — model coder hanya boleh di GPU 1 (anti-OOM)
Environment="CUDA_VISIBLE_DEVICES=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
# Berbagi direktori model dengan instance utama (blobs read-only)
Environment="OLLAMA_MODELS=/usr/share/ollama/.ollama/models"

[Install]
WantedBy=default.target
EOF
echo "  ✅ /etc/systemd/system/ollama-coder.service"

# --- 4. Reload & start ---
echo "[4/4] Reload systemd dan restart kedua instance..."
systemctl daemon-reload
systemctl restart ollama
systemctl enable --now ollama-coder
systemctl restart ollama-coder

sleep 3
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  Status Instance                                      ║"
echo "╚════════════════════════════════════════════════════════╝"
systemctl is-active ollama ollama-coder || true
echo ""
if curl -sf http://127.0.0.1:11434/api/version >/dev/null; then
    echo "  ✅ Reasoning (:11434) online — $(curl -s http://127.0.0.1:11434/api/version)"
else
    echo "  ❌ Reasoning (:11434) tidak merespons"
fi
if curl -sf http://127.0.0.1:11435/api/version >/dev/null; then
    echo "  ✅ Coder (:11435) online — $(curl -s http://127.0.0.1:11435/api/version)"
else
    echo "  ❌ Coder (:11435) tidak merespons"
fi
echo ""
echo "Selesai. Verifikasi model per-instance:"
echo "  curl http://127.0.0.1:11434/api/tags   # GPU 0 — qwen2.5:3b-instruct"
echo "  curl http://127.0.0.1:11435/api/tags   # GPU 1 — qwen2.5-coder:3b"
