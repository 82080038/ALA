FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Install Python 3.11 + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    build-essential libpq-dev curl \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && python3 -m pip install --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch dengan dukungan CUDA 12.4 — agar torch.cuda.is_available() = True
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124

# Install dependencies lengkap (Fase 2/3: agen AI, ALCD, crawling)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser Playwright untuk Internet Crawler Agent (JS-heavy sites)
RUN playwright install --with-deps chromium

# Copy kode aplikasi
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
