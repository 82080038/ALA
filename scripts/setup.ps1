# ============================================================
#  ALA — Skrip Setup Lingkungan (Windows PowerShell)
# ============================================================
#  Penggunaan: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# ============================================================
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Write-Host @"

+============================================================+
|  ALA — Autonomous Legal Agent — Setup Lingkungan           |
|  Platform: Windows PowerShell $($PSVersionTable.PSVersion) |
+============================================================+

"@

# --- 1. Periksa prasyarat ---
Write-Host "[1/5] Memeriksa prasyarat..." -ForegroundColor Cyan

try {
    $dockerVersion = docker --version
    Write-Host "  [OK] Docker: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Docker tidak ditemukan. Install: https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Red
    exit 1
}

try {
    $composeVersion = docker compose version
    Write-Host "  [OK] Docker Compose: $composeVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Docker Compose tidak ditemukan." -ForegroundColor Red
    exit 1
}

# Periksa Ollama
$ollamaInstalled = $false
try {
    $ollamaVersion = ollama --version 2>$null
    Write-Host "  [OK] Ollama: $ollamaVersion" -ForegroundColor Green
    $ollamaInstalled = $true
} catch {
    Write-Host "  [!] Ollama tidak ditemukan. Install: https://ollama.com/download" -ForegroundColor Yellow
    Write-Host "      Ollama diperlukan untuk inferensi LLM lokal." -ForegroundColor Yellow
}

# --- 2. File .env ---
Write-Host ""
Write-Host "[2/5] Memeriksa file .env..." -ForegroundColor Cyan

$envFile = Join-Path $ProjectDir ".env"
$envExample = Join-Path $ProjectDir ".env.example"

if (-not (Test-Path $envFile)) {
    Write-Host "  Menyalin .env.example -> .env" -ForegroundColor Yellow
    Copy-Item $envExample $envFile
    Write-Host "  [!] Edit .env dan ganti password default sebelum deploy produksi!" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] .env sudah ada" -ForegroundColor Green
}

# --- 3. Konfigurasi khusus Windows ---
Write-Host ""
Write-Host "[3/5] Konfigurasi khusus platform..." -ForegroundColor Cyan
Write-Host "  Windows terdeteksi - Docker Desktop menangani host.docker.internal secara native" -ForegroundColor Green

# Periksa apakah NVIDIA GPU tersedia
try {
    $gpuInfo = nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
    if ($gpuInfo) {
        Write-Host "  [OK] NVIDIA GPU terdeteksi: $($gpuInfo.Trim())" -ForegroundColor Green
    }
} catch {
    Write-Host "  [i] Tidak ada GPU NVIDIA terdeteksi - sistem akan berjalan di mode CPU" -ForegroundColor Yellow
}

# --- 4. Tarik model Ollama ---
Write-Host ""
Write-Host "[4/5] Memeriksa model Ollama..." -ForegroundColor Cyan

if ($ollamaInstalled) {
    $models = @("qwen2.5:3b-instruct", "qwen2.5-coder:3b")
    foreach ($model in $models) {
        $modelList = ollama list 2>$null
        if ($modelList -match [regex]::Escape($model)) {
            Write-Host "  [OK] Model $model sudah tersedia" -ForegroundColor Green
        } else {
            Write-Host "  Mengunduh model $model..." -ForegroundColor Yellow
            ollama pull $model
        }
    }
} else {
    Write-Host "  Melewati - Ollama tidak terinstall" -ForegroundColor Yellow
}

# --- 5. Bangun dan jalankan kontainer ---
Write-Host ""
Write-Host "[5/5] Membangun dan menjalankan kontainer Docker..." -ForegroundColor Cyan

Push-Location $ProjectDir
try {
    docker compose up -d --build
} finally {
    Pop-Location
}

Write-Host @"

+============================================================+
|  [OK] Setup selesai!                                       |
|                                                            |
|  Layanan:                                                  |
|    API:       http://localhost:8080                         |
|    Frontend:  http://localhost:3000                         |
|    Docs:      http://localhost:8080/docs                    |
|    Neo4j:     http://localhost:7474                         |
|    ChromaDB:  http://localhost:8001                         |
|                                                            |
|  Periksa kesehatan:                                        |
|    Invoke-RestMethod http://localhost:8080/health           |
+============================================================+

"@ -ForegroundColor Green
