"""Harden-wave regression tests (Oct 18, 2026).

Each test pins a defect found by probing the shipped tool:

- CLI robustness: a missing pattern file, a wrong-typed config
  value, or an uncreatable output directory crashed with an
  uncaught traceback (exit 1) instead of the documented clean
  exit 2. The worst config case was {"no_redact": "false"}: the
  string is truthy, so bool() coercion silently DISABLED
  redaction for a config that said the opposite, and a planted
  secret-shaped key was emitted verbatim.
- Redaction gaps: bearer tokens in the RFC 6750 base64 charset
  ('+', '/', '=' padding) were only partially redacted and their
  tails leaked; `Authorization: Basic ...` blobs were not
  redacted at all; URL passwords containing ':' never matched
  the url-password shape; GitHub fine-grained PATs
  (github_pat_...) were not recognised; dotted sk- keys leaked
  everything after the dot.

Redaction assertions are boolean (secret present or not, shape
names hit), never comparisons against printed secret text.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostlogs.redact import redact_line  # noqa: E402

from conftest import (  # noqa: E402
    all_output_text,
    build_pack,
    load_manifest,
    run_ghostlogs,
)

# Synthetic, fake values built to shape lengths. Not real secrets.
BEARER_TOKEN = "abcdefghij1234+/XYZw9876=="
BASIC_BLOB = "dXNlcjpwYXNzd29yZDEyMw=="
GITHUB_PAT = "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789abcd"
URL_PW_TAIL = "word123"
SK_TAIL = "IjKlMnOp5678"
AWS_SHAPED = "AKIA" + "BCDFGHJKLMNPQRS1"


def _small_log(tmp_path):
    log = tmp_path / "small.log"
    log.write_text("INFO start\nERROR boom\nINFO end\n")
    return log


# --- CLI robustness: clean exit 2, never a traceback ----------------

def test_missing_pattern_file_fails_cleanly(tmp_path):
    log = _small_log(tmp_path)
    proc = run_ghostlogs(
        ["pack", log, "-o", tmp_path / "pack",
         "--patterns", tmp_path / "nope.txt"])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "pack" / "manifest.json").exists()


def test_doctor_missing_pattern_file_fails_cleanly(tmp_path):
    proc = run_ghostlogs(["doctor", "--patterns", tmp_path / "nope.txt"])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_config_patterns_file_missing_fails_cleanly(tmp_path):
    log = _small_log(tmp_path)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"patterns_file": "nope.txt"}))
    proc = run_ghostlogs(["pack", log, "-o", tmp_path / "pack",
                          "--config", cfg])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("cfg", [
    {"budget": "8000"},
    {"budget": None},
    {"budget": True},
    {"window_before": 1.5},
    {"window_after": "5"},
    {"no_redact": "false"},
    {"no_redact": 0},
    {"patterns_file": 42},
])
def test_config_wrong_types_fail_cleanly(tmp_path, cfg):
    log = _small_log(tmp_path)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))
    proc = run_ghostlogs(["pack", log, "-o", tmp_path / "pack",
                          "--config", cfg_path])
    assert proc.returncode == 2, (cfg, proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "pack" / "manifest.json").exists()


def test_config_no_redact_false_keeps_redaction_on(tmp_path):
    """The valid form of the dangerous config: an explicit JSON
    false must leave redaction enabled and the planted key out of
    every output."""
    log = tmp_path / "secret.log"
    log.write_text(
        "INFO start\n"
        f"ERROR upstream rejected key {AWS_SHAPED}\n"
        "INFO end\n")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"no_redact": False}))
    proc, out = build_pack(log, tmp_path / "pack", ["--config", cfg])
    assert proc.returncode == 0, proc.stderr
    assert load_manifest(out)["redaction"]["enabled"] is True
    assert AWS_SHAPED not in all_output_text(out, proc)


def test_output_path_existing_file_fails_cleanly(tmp_path):
    log = _small_log(tmp_path)
    blocker = tmp_path / "outfile"
    blocker.write_text("not a directory")
    proc = run_ghostlogs(["pack", log, "-o", blocker])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


# --- Redaction gaps --------------------------------------------------

def test_bearer_base64_token_fully_redacted():
    out, hits = redact_line(f"Authorization: Bearer {BEARER_TOKEN}")
    assert "bearer-token" in hits
    assert "XYZw9876" not in out
    assert BEARER_TOKEN not in out


def test_basic_auth_blob_redacted():
    out, hits = redact_line(f"Authorization: Basic {BASIC_BLOB}")
    assert "basic-auth" in hits
    assert BASIC_BLOB not in out


def test_basic_word_in_prose_is_not_redacted():
    line = "Basic configuration loaded for the service"
    out, hits = redact_line(line)
    assert hits == []
    assert out == line


def test_url_password_with_colon_redacted():
    line = ("connect https://user:pass:word123@db.internal:5432/x "
            "failed")
    out, hits = redact_line(line)
    assert "url-password" in hits
    assert URL_PW_TAIL not in out
    assert "pass:" not in out


def test_url_with_port_only_is_not_redacted():
    line = "GET https://example.com:8080/path 200"
    out, hits = redact_line(line)
    assert "url-password" not in hits
    assert out == line


def test_github_fine_grained_pat_redacted():
    out, hits = redact_line(f"tok {GITHUB_PAT} end")
    assert "github-token" in hits
    assert GITHUB_PAT not in out


def test_sk_key_with_dot_fully_redacted():
    out, hits = redact_line(
        f"key sk-proj-AbCdEfGh1234.{SK_TAIL}_qrstuv end")
    assert "openai-or-anthropic-key" in hits
    assert SK_TAIL not in out


def test_hardened_shapes_never_reach_pack_outputs(tmp_path):
    """End to end: every hardened shape planted inside an error
    window is absent from the pack, the manifest, and stdio, and
    each shape's redaction is counted in the manifest."""
    log = tmp_path / "leaks.log"
    log.write_text(
        "INFO boot complete\n"
        f"ERROR Authorization: Bearer {BEARER_TOKEN}\n"
        f"ERROR Authorization: Basic {BASIC_BLOB}\n"
        "ERROR connect https://user:pass:word123@db.internal/x "
        "failed\n"
        f"ERROR tok {GITHUB_PAT} rejected\n"
        "INFO shutdown complete\n")
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    for secret in (BEARER_TOKEN, "XYZw9876", BASIC_BLOB,
                   URL_PW_TAIL, GITHUB_PAT):
        assert secret not in everything, secret
    counts = load_manifest(out)["redaction"]["counts"]
    for shape in ("bearer-token", "basic-auth", "url-password",
                  "github-token"):
        assert counts.get(shape, 0) >= 1, (shape, counts)
