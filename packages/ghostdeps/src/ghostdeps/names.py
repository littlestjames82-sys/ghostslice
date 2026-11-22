"""Name normalisation and import-name to distribution-name mapping.

Comparing declared dependencies against imports is a name problem before
it is anything else: the import name and the distribution name often
differ (``import yaml`` is declared as PyYAML). Normalisation follows
PEP 503 for Python-style names; JS and Cargo names are lowercased with
``_`` folded to ``-`` (Cargo crate names use ``_``, package names ``-``).
"""
from __future__ import annotations

import re

_SEP = re.compile(r"[-_.]+")


def norm(name: str) -> str:
    """Canonical comparison key for a package or import name."""
    return _SEP.sub("-", name.strip()).lower()


# Import module (top-level) -> distribution name, for the mismatches that
# show up constantly in real projects. Keys and values are raw names;
# callers normalise both sides. This table is a heuristic, and the pack
# records when a mapping was applied so the evidence stays visible.
PY_IMPORT_TO_DIST = {
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "magic": "python-magic",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodome",
    "OpenSSL": "pyOpenSSL",
    "fitz": "PyMuPDF",
    "pptx": "python-pptx",
    "docx": "python-docx",
    "attr": "attrs",
    "attrs": "attrs",
    "gi": "PyGObject",
    "flask_sqlalchemy": "Flask-SQLAlchemy",
    "flask_login": "Flask-Login",
    "flask_wtf": "Flask-WTF",
    "flask_cors": "Flask-CORS",
    "flask_migrate": "Flask-Migrate",
    "flask_restful": "Flask-RESTful",
    "sqlalchemy": "SQLAlchemy",
    "celery": "celery",
    "redis": "redis",
    "requests": "requests",
    "numpy": "numpy",
    "pandas": "pandas",
    "pytest": "pytest",
    "setuptools": "setuptools",
    "pkg_resources": "setuptools",
    "Pillow": "Pillow",
    "rest_framework": "djangorestframework",
    "django_filters": "django-filter",
    "channels": "channels",
    "PIL.Image": "Pillow",
}


def py_dist_for_import(module_top: str) -> tuple[str, bool]:
    """Return (distribution name guess, mapping_was_applied)."""
    if module_top in PY_IMPORT_TO_DIST:
        dist = PY_IMPORT_TO_DIST[module_top]
        return dist, dist != module_top
    return module_top, False


# Node.js builtin modules (bare specifiers). `node:` prefixed forms are
# handled by stripping the prefix before lookup.
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "diagnostics_channel", "dns", "domain", "events",
    "fs", "http", "http2", "https", "inspector", "module", "net", "os",
    "path", "perf_hooks", "process", "punycode", "querystring", "readline",
    "repl", "stream", "string_decoder", "sys", "timers", "tls", "trace_events",
    "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
}


def js_package_name(specifier: str) -> str | None:
    """Package name for a bare JS/TS specifier, or None if it is a path.

    Relative (./ ../), absolute (/), and URL specifiers are not packages.
    Scoped names keep both segments (@scope/name). A ``node:`` prefix
    is stripped first, so ``node:fs`` and ``fs`` name the same builtin
    instead of two different modules. Malformed scoped specifiers
    (``@scope`` with no package, ``@scope/`` with an empty package,
    ``@/pkg`` with an empty scope), names containing whitespace, and
    Windows drive paths are not packages and return None; they used
    to be reported as imported-but-undeclared packages.
    """
    if not specifier or specifier.startswith((".", "/", "#")):
        return None
    if "://" in specifier:
        return None
    if len(specifier) >= 3 and specifier[1] == ":" \
            and specifier[2] in ("/", "\\"):
        return None  # Windows drive path, e.g. C:/src/util
    if any(ch.isspace() for ch in specifier):
        return None
    if specifier.startswith("node:"):
        specifier = specifier[5:]
        if not specifier:
            return None
    parts = specifier.split("/")
    if specifier.startswith("@"):
        if len(parts) < 2 or not parts[0][1:] or not parts[1]:
            return None
        return "/".join(parts[:2])
    return parts[0] or None


def js_builtin(specifier: str) -> bool:
    """True when ``specifier`` names a Node.js builtin module.

    Both bare names (``fs``) and ``node:``-prefixed forms
    (``node:fs``) are recognised, including subpaths such as
    ``fs/promises``.
    """
    name = specifier[5:] if specifier.startswith("node:") else specifier
    return name.split("/")[0] in NODE_BUILTINS
