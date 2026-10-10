"""Uji sandbox guardrails — AST scan harus loloskan kode aman,
menolak import/pola berbahaya, dan membatasi open() ke mode baca."""
from app.sandbox.guardrails import scan_code

SAFE = """
import json
import hashlib

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

print(json.dumps({"ok": True}))
"""

EVIL_IMPORTS = ["import os", "import subprocess", "import socket",
                "import requests", "from os import system"]


def test_safe_code_passes():
    r = scan_code(SAFE)
    assert r.allowed, r.summary


def test_malicious_imports_blocked():
    for snippet in EVIL_IMPORTS:
        r = scan_code(snippet)
        assert not r.allowed, f"seharusnya ditolak: {snippet}"


def test_dangerous_calls_blocked():
    for code in ["eval('1+1')", "exec('x=1')",
                 "__import__('os').system('id')"]:
        r = scan_code(code)
        assert not r.allowed, f"seharusnya ditolak: {code}"


def test_open_read_modes_allowed():
    for mode in ['"r"', '"rb"', '"rt"']:
        r = scan_code(f"open('data.txt', {mode})")
        assert r.allowed, f"mode {mode} seharusnya diizinkan"


def test_open_write_modes_blocked():
    for mode in ['"w"', '"wb"', '"a"', '"x"', '"w+"']:
        r = scan_code(f"open('out.txt', {mode})")
        assert not r.allowed, f"mode {mode} seharusnya ditolak"


def test_open_dynamic_mode_blocked():
    # Mode non-literal tidak dapat diverifikasi statis → wajib ditolak
    r = scan_code("m = 'w'\nopen('f.txt', m)")
    assert not r.allowed


def test_sensitive_paths_blocked():
    for path in ["/etc/passwd", "/etc/shadow", "~/.ssh/id_rsa"]:
        r = scan_code(f"open('{path}', 'rb')")
        assert not r.allowed, f"path {path} seharusnya ditolak"


def test_syntax_error_reported():
    r = scan_code("def broken(:\n")
    assert not r.allowed


def test_path_write_methods_blocked():
    """Path.write_text dkk. adalah open('w') terselubung — harus ditolak."""
    for code in [
        "from pathlib import Path\nPath('o.txt').write_text('x')",
        "from pathlib import Path\np = Path('d')\np.mkdir()",
        "from pathlib import Path\nPath('a').unlink()",
    ]:
        r = scan_code(code)
        assert not r.allowed, f"seharusnya ditolak: {code}"


def test_path_read_methods_allowed():
    r = scan_code(
        "from pathlib import Path\nprint(Path('d.txt').read_text())")
    assert r.allowed, r.summary


def test_custody_scaffold_passes():
    """Scaffold chain-of-custody (read-only + SHA-256) wajib lolos scan."""
    from app.agents.code_generator import CUSTODY_SCAFFOLD
    r = scan_code(CUSTODY_SCAFFOLD)
    assert r.allowed, r.summary
