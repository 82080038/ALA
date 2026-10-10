"""
Sandbox Guardrails — pemindai keamanan kode hasil generate AI.

Kode dari Agent 3 WAJIB melewati tiga lapis pemeriksaan sebelum boleh
dieksekusi di sandbox:

1. Syntax check (ast.parse)
2. Import whitelist — hanya stdlib aman + library data yang diizinkan
3. Blacklist scanning — pola berbahaya (jaringan, subprocess, eval/exec,
   penulisan path sensitif, mutasi bukti)
"""
import ast
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("ala.sandbox.guardrails")

# ---------------------------------------------------------------------------
# Whitelist import — top-level package yang boleh dipakai kode generatean.
# ---------------------------------------------------------------------------
ALLOWED_IMPORTS: frozenset[str] = frozenset({
    # stdlib data processing
    "csv", "json", "xml", "re", "io", "collections", "itertools",
    "functools", "datetime", "time", "math", "statistics", "decimal",
    "hashlib", "hmac", "base64", "binascii", "textwrap", "string",
    "difflib", "unicodedata", "struct", "zipfile", "gzip", "bz2",
    "lzma", "tarfile", "pathlib", "fnmatch", "glob", "tempfile",
    "dataclasses", "enum", "typing", "copy", "pprint", "heapq",
    "bisect", "array", "queue", "uuid", "random", "secrets",
    "logging", "warnings", "contextlib", "abc", "operator",
    "sqlite3",  # analisis DB lokal read-only
    # library data yang diizinkan (disediakan di image sandbox)
    "pandas", "numpy", "openpyxl", "docx",
    "bs4", "lxml",  # parsing file HTML/XML bukti
    "PIL", "pytesseract", "pdfplumber", "pypdf",
    "chardet", "chardet2",
    "python_dateutil", "dateutil",
})

# ---------------------------------------------------------------------------
# Blacklist — pola yang TIDAK BOLEH muncul dalam bentuk apapun.
# ---------------------------------------------------------------------------
_BLOCKED_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr",  # refleksi arbitrer
    "os.system", "os.popen", "os.spawnl", "os.spawnlp", "os.spawnle",
    "os.spawnlpe", "os.spawnv", "os.spawnvp", "os.spawnve",
    "os.spawnvpe", "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.execv", "os.execve", "os.execvp", "os.execvpe", "os.fork",
    "os.kill", "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "os.rename", "os.renames", "os.chmod", "os.chown", "os.setuid",
    "os.setgid", "os.environ",
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "socket.socket", "socket.create_connection",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.head", "requests.request",
    "urllib.request.urlopen", "urllib.request.urlretrieve",
    "urllib.parse.urlparse",  # diblok di URL berbahaya — cek terpisah
    "httpx.get", "httpx.post", "httpx.request",
    "shutil.rmtree", "shutil.move", "shutil.chown",
    "pty.spawn", "pty.fork",
    "signal.signal", "signal.alarm",
    "sys.exit", "sys._exit", "sys.modules",
    "builtins.eval", "builtins.exec",
    "code.InteractiveConsole", "code.InteractiveInterpreter",
    "pickle.loads", "pickle.load",
    "marshal.loads", "marshal.load",
    "ctypes.CDLL", "ctypes.cdll", "ctypes.PyDLL",
    "webbrowser.open",
    "input", "breakpoint",  # interaktivitas — hang di sandbox
})

# Nama method yang setara dengan open(mode tulis) — open('w') diblok,
# jadi jalur tulis alternatif ini juga diblok demi konsistensi lapis
# guardrail (sandbox ro-FS tetap pertahanan terakhir).
_BLOCKED_METHOD_NAMES: frozenset[str] = frozenset({
    "write_text", "write_bytes", "mkdir", "unlink", "rename",
    "replace", "touch", "rmdir", "symlink_to", "hardlink_to",
    "chmod", "chown",
})

_BLOCKED_ATTR_ROOTS: frozenset[str] = frozenset({
    "os", "subprocess", "socket", "requests", "urllib", "httpx",
    "ftplib", "telnetlib", "smtplib", "poplib", "imaplib",
    "paramiko", "fabric", "invoke",
    "ctypes", "cffi", "mmap",
    "multiprocessing", "threading",  # paralelisme tak terbatas
    "sys",
})

# Path sensitif yang tidak boleh ditulis/dibaca kode generatean
_BLOCKED_PATHS: tuple[tuple[str, ...], ...] = (
    ("/etc", "/proc", "/sys", "/root", "/dev", "/boot", "/run/secrets"),
    ("..",),  # path traversal
)

# Pattern regex untuk deteksi mutasi file bukti / aksi berbahaya
_DANGEROUS_PATTERNS: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), d) for p, d in [
        (r"open\s*\([^)]*['\"][wax]\+?b?['\"]", "file dibuka mode tulis/append"),
        (r"os\.environ", "akses environment variable"),
        (r"['\"](?:/etc|/proc|/sys|/root|/dev)/", "akses path sensitif"),
        (r"['\"]\.\.", "path traversal '..'"),
        (r"['\"~].*?\.(ssh|gnupg|aws|kube|docker)/", "akses kredensial home"),
        (r"(?:id_rsa|id_dsa|id_ecdsa|id_ed25519|\.pem['\"])",
         "akses kunci privat"),
        (r"['\"][^'\"]*/?\.env['\"]", "akses file .env (rahasia)"),
        (r"__dict__\s*\[", "mutasi __dict__"),
        (r"import\s+os\b", "import os dilarang"),
        (r"import\s+subprocess\b", "import subprocess dilarang"),
        (r"import\s+socket\b", "import socket dilarang"),
        (r"import\s+requests\b", "import requests dilarang"),
        (r"import\s+urllib\b", "import urllib dilarang"),
        (r"import\s+httpx\b", "import httpx dilarang"),
        (r"import\s+ctypes\b", "import ctypes dilarang"),
        (r"import\s+pickle\b", "import pickle dilarang"),
        (r"import\s+marshal\b", "import marshal dilarang"),
        (r"import\s+multiprocessing\b", "import multiprocessing dilarang"),
        (r"import\s+threading\b", "import threading dilarang"),
        (r"import\s+sys\b", "import sys dilarang"),
        (r"from\s+os\b", "from os import dilarang"),
        (r"from\s+subprocess\b", "from subprocess import dilarang"),
        (r"from\s+socket\b", "from socket import dilarang"),
        (r"from\s+requests\b", "from requests import dilarang"),
        (r"from\s+urllib\b", "from urllib import dilarang"),
        (r"from\s+httpx\b", "from httpx import dilarang"),
        (r"from\s+sys\b", "from sys import dilarang"),
        (r"from\s+ctypes\b", "from ctypes import dilarang"),
    ]
)


@dataclass
class GuardrailResult:
    """Hasil pemeriksaan keamanan satu potong kode."""
    allowed: bool
    syntax_ok: bool = True
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.allowed:
            return "PASS — kode aman untuk dieksekusi sandbox"
        return f"BLOCKED — {len(self.violations)} pelanggaran"


def _check_syntax(code: str, result: GuardrailResult) -> ast.Module | None:
    try:
        return ast.parse(code)
    except SyntaxError as exc:
        result.syntax_ok = False
        result.violations.append(f"SyntaxError: {exc.msg} (baris {exc.lineno})")
        return None


def _check_imports(tree: ast.Module, result: GuardrailResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    result.violations.append(
                        f"Import '{alias.name}' tidak diizinkan "
                        f"(baris {node.lineno})"
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                result.violations.append(
                    f"from '{node.module}' import tidak diizinkan "
                    f"(baris {node.lineno})"
                )


def _check_calls(tree: ast.Module, result: GuardrailResult) -> None:
    """Deteksi pemanggilan fungsi/atribut berbahaya via AST."""
    for node in ast.walk(tree):
        # Pemanggilan fungsi: eval(), os.system(), getattr(...)
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                parts = []
                cur = func
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                name = ".".join(reversed(parts))
            if name in _BLOCKED_CALLS:
                result.violations.append(
                    f"Pemanggilan '{name}()' dilarang (baris {node.lineno})"
                )
            elif isinstance(func, ast.Attribute) and \
                    func.attr in _BLOCKED_METHOD_NAMES:
                result.violations.append(
                    f"Method tulis '.{func.attr}()' dilarang — hanya "
                    f"mode baca diizinkan (baris {node.lineno})"
                )
            elif name == "open":
                _check_open_mode(node, result)
        # Akses atribut modul berbahaya: os.environ, sys.modules
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and \
                    node.value.id in _BLOCKED_ATTR_ROOTS:
                full = f"{node.value.id}.{node.attr}"
                if full not in ALLOWED_IMPORTS:
                    result.violations.append(
                        f"Akses '{full}' dilarang (baris {node.lineno})"
                    )


# Mode open() yang diizinkan — hanya baca (default 'r' jika tanpa argumen)
_ALLOWED_OPEN_MODES: frozenset[str] = frozenset({"r", "rb", "rt"})


def _check_open_mode(node: ast.Call, result: GuardrailResult) -> None:
    """open() hanya boleh mode baca — bukti tidak boleh dimutasi."""
    mode_node = None
    if len(node.args) >= 2:
        mode_node = node.args[1]
    else:
        for kw in node.keywords:
            if kw.arg == "mode":
                mode_node = kw.value
    if mode_node is None:
        return  # default 'r' — aman
    if isinstance(mode_node, ast.Constant) and isinstance(
        mode_node.value, str
    ):
        if mode_node.value not in _ALLOWED_OPEN_MODES:
            result.violations.append(
                f"open() mode '{mode_node.value}' dilarang — hanya "
                f"mode baca diizinkan (baris {node.lineno})"
            )
    else:
        result.violations.append(
            f"open() dengan mode non-literal tidak dapat diverifikasi "
            f"(baris {node.lineno})"
        )


def _check_regex(code: str, result: GuardrailResult) -> None:
    for pattern, desc in _DANGEROUS_PATTERNS:
        m = pattern.search(code)
        if m:
            line = code[: m.start()].count("\n") + 1
            result.violations.append(f"{desc} (baris ~{line})")


def scan_code(code: str) -> GuardrailResult:
    """Pindai satu skrip Python — kembalikan GuardrailResult.

    allowed=True hanya jika syntax valid DAN nol pelanggaran.
    """
    result = GuardrailResult(allowed=False)
    if not code or not code.strip():
        result.violations.append("Kode kosong")
        return result

    tree = _check_syntax(code, result)
    if tree is None:
        return result

    _check_imports(tree, result)
    _check_calls(tree, result)
    _check_regex(code, result)

    # Verifikasi rantai pengungkapan jika kode menyentuh file bukti
    if re.search(r"open\s*\(", code):
        if "sha256" not in code:
            result.warnings.append(
                "Kode membuka file tanpa verifikasi SHA-256 — "
                "rantai pengungkapan tidak terpenuhi"
            )

    result.allowed = not result.violations
    if not result.allowed:
        logger.warning("Guardrail BLOCKED: %s", "; ".join(result.violations))
    return result
