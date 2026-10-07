# Sandbox eksekusi kode AI — dikunci penuh
# Digunakan oleh backend/app/sandbox/execution_env.py untuk menjalankan
# skrip utilitas yang digenerate Agen 3 secara terisolasi.
#
# Constraint runtime (diterapkan saat `docker run`, lihat SECURITY.md §4.2):
#   --network=none --read-only --tmpfs=/tmp:size=256m
#   --memory=256m --cpus=0.5 --user=sandbox_user
FROM python:3.11-slim

# Dependensi — pustaka data umum untuk skrip utilitas hasil AI.
# Semua tetap aman: sandbox berjalan tanpa jaringan, read-only, non-root.
# Pin mayor-minor untuk reprodusibilitas (bukan `latest`).
RUN pip install --no-cache-dir \
    "regex>=2024.0" \
    "pandas>=2.2,<3" \
    "numpy>=1.26,<3" \
    "openpyxl>=3.1,<4" \
    "beautifulsoup4>=4.12,<5" \
    "lxml>=5.2,<6" \
    "pdfplumber>=0.11,<1" \
    "pypdf>=4,<6" \
    "python-docx>=1.1,<2" \
    "pillow>=10,<12" \
    "pytesseract>=0.3,<1" \
    "chardet>=5,<6" \
    "python-dateutil>=2.9,<3"

# Pengguna non-root (principle of least privilege)
RUN useradd -m -s /bin/bash sandbox_user
USER sandbox_user

WORKDIR /sandbox

# Default: jalankan skrip yang di-mount ke /sandbox/script.py
CMD ["python", "/sandbox/script.py"]
