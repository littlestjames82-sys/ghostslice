"""Hardening regression tests (improve lane: harden, Oct 18 2026).

Each test pins a bug found by auditing the v0.1 code paths that the
original suite did not exercise: malformed framing headers, query
strings defeating routing, chunked request bodies, profile/config
type confusion, the ledger scrub eating documented fields, and
transform bookkeeping for GhostSlice's strip-tests mode. Every test
fails against the pre-fix code and passes after it.
"""

import json
import os
import socket
import subprocess
import sys

import pytest

from conftest import (
    GHOSTSLICE_SRC,
    SRC,
    SECRET_MARKER,
    ProxyProcess,
    http_get,
    http_post,
    make_project,
    messages_request,
    project_sections,
    requires_core,
)

HEADERS = {"x-api-key": "CANARY-API-KEY-ghostproxy-leak-test-0000000001",
           "anthropic-version": "2023-06-01",
           "content-type": "application/json"}


# ------------------------------------------------------------ ledger scrub

def test_scrub_preserves_secret_types_in_ledger(tmp_path):
    """README promises the transform map records path + finding TYPE.
    The old substring scrub deleted the whole secret_types field
    (its name contains 'secret') before the entry reached disk."""
    from ghostproxy.ledger import Ledger, make_entry

    entry = make_entry(
        project="p", method="POST", path="/v1/messages", status=200,
        transform={
            "transform_map": [{
                "path": "a.py", "action": "dropped",
                "reason": "secret-guard", "tokens_in": 5, "tokens_out": 0,
                "secret_types": ["aws-access-key"],
                "mode_before": "full", "mode_after": "exclude",
            }],
            "context_tokens_in": 5, "context_tokens_out": 0,
            "tokens_in": 5, "tokens_out": 0,
            "files_seen": ["a.py"], "files_dropped": ["a.py"],
        },
        latency_ms=1.0)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(entry)
    (row,) = ledger.entries()
    assert row["transform_map"][0]["secret_types"] == ["aws-access-key"]
    assert row["transform_map"][0]["reason"] == "secret-guard"


def test_scrub_drops_credential_keys_but_keeps_innocent_ones():
    from ghostproxy.ledger import _scrub

    cleaned = _scrub({
        "api_key": "v", "x-api-key": "v", "authorization": "v",
        "auth_token": "v", "oauth": "v", "client_secret": "v",
        "author": "kept", "authority": "kept", "tokens_in": 3,
    })
    assert cleaned == {"author": "kept", "authority": "kept",
                       "tokens_in": 3}


def test_build_report_tolerates_corrupt_field_types():
    """Ledger.entries already skips corrupt JSON lines; the roll-up
    must also survive hand-edited rows with non-numeric token fields
    instead of crashing `ghostproxy report` with a traceback."""
    from ghostproxy.ledger import build_report

    report = build_report([
        {"tokens_in": "abc", "tokens_out": None,
         "context_tokens_in": [1], "context_tokens_out": "x"},
        {"tokens_in": 10, "tokens_out": 4},
    ])
    assert report["requests"] == 2
    assert report["tokens_in"] == 10
    assert report["tokens_out"] == 4


# ------------------------------------------------------------ config

@pytest.mark.parametrize("overrides", [
    {"upstream": 123},
    {"upstream": None},
    {"upstream": "http://"},
    {"upstream": "https://"},
    {"upstream": "http://127.0.0.1:abc"},
    {"upstream": "http://127.0.0.1:99999"},
    {"upstream_timeout": "abc"},
    {"upstream_timeout": -5},
    {"upstream_timeout": 0},
    {"max_body_bytes": -1},
    {"max_body_bytes": "big"},
    {"port": True},
    {"budget_tokens": True},
    {"enabled": "false"},
    {"log_bodies": "yes"},
])
def test_config_rejects_bad_values_with_config_error(overrides):
    """Bad types/ranges used to leak AttributeError (non-string
    upstream), pass silently (negative timeout made every request
    fail; negative max_body_bytes disabled ALL transformation
    including the secrets guard), or invert meaning (the string
    'false' is truthy). All must be ConfigError now."""
    from ghostproxy.config import ConfigError, ProxyConfig

    with pytest.raises(ConfigError):
        ProxyConfig(**overrides)


def test_profile_cannot_turn_on_body_logging(tmp_path):
    """README trust rule: 'A profile file cannot turn body logging
    on.' The old build_config merged the profile's log_bodies: true
    straight into the config; only the explicit serve flag may."""
    from ghostproxy.config import build_config

    (tmp_path / ".ghostslice.json").write_text(json.dumps(
        {"proxy": {"log_bodies": True, "budget_tokens": 123}}))
    config = build_config(tmp_path)
    assert config.log_bodies is False
    assert config.budget_tokens == 123  # other profile keys still work
    assert build_config(tmp_path, {"log_bodies": True}).log_bodies is True


def test_serve_ipv6_loopback_refusal_is_a_config_error():
    """config accepts ::1 as a loopback literal but the v0.1 server
    binds 127.0.0.1 only; the refusal must be a ConfigError the CLI
    reports cleanly, not a bare ValueError traceback."""
    from ghostproxy.config import ConfigError, ProxyConfig
    from ghostproxy.server import serve

    with pytest.raises(ConfigError):
        serve(ProxyConfig(host="::1", port=18766))


# ------------------------------------------------------------ transform

def test_strip_tests_mode_after_is_reported_truthfully():
    """A test file sliced to strip-tests reported mode_after 'full'
    (its original mode) and its (mode: ...) header was rewritten
    back to full, so the transform map lied about what was sent."""
    from ghostproxy.transform import transform_request

    request = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text",
         "text": "# File: test_app.py (mode: full)\n\n"
                 "def test_one():\n    assert compute(1) == 1\n"}]}]}
    result = transform_request(request)
    (block,) = result.transform_map
    assert block["action"] == "strip-tests"
    assert block["mode_after"] == "strip-tests"
    sent_text = result.request["messages"][0]["content"][0]["text"]
    assert sent_text.startswith("# File: test_app.py (mode: strip-tests)")


@pytest.mark.parametrize("payload", [[1, 2, 3], "just a string", 42, None])
def test_transform_non_object_request_passes_through(payload):
    """transform_request documents 'never raises for shape problems';
    a non-object JSON body raised AttributeError, crashing the
    transform CLI command with a traceback."""
    from ghostproxy.transform import transform_request

    result = transform_request(payload)
    assert result.request == payload
    assert result.fallback is True
    assert result.fallback_reason == "request-not-an-object"


# ------------------------------------------------------------ CLI surface

def _cli(args, timeout=60):
    env = dict(os.environ)
    paths = [str(SRC)] + ([str(GHOSTSLICE_SRC)] if GHOSTSLICE_SRC.is_dir()
                          else [])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.run([sys.executable, "-m", "ghostproxy"] + args,
                          env=env, capture_output=True, text=True,
                          timeout=timeout)


def test_cli_transform_malformed_json_is_a_clean_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("this is not json")
    proc = _cli(["transform", str(bad)])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_cli_transform_missing_file_is_a_clean_error(tmp_path):
    proc = _cli(["transform", str(tmp_path / "nope.json")])
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_cli_transform_non_object_json_passes_through(tmp_path):
    doc = tmp_path / "alien.json"
    doc.write_text("[1, 2, 3]")
    proc = _cli(["transform", str(doc)])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [1, 2, 3]


# ------------------------------------------------------------ server framing

def _raw_exchange(port, payload: bytes, timeout=10) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(payload)
        chunks = []
        while True:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


@requires_core
def test_malformed_content_length_does_not_kill_proxy(fake_upstream, tmp_path):
    """int(Content-Length) on 'abc' raised inside the handler and
    dropped the connection with no response at all: fail-open says
    the request path must degrade, never vanish."""
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        response = _raw_exchange(
            proxy.port,
            b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: abc\r\n\r\n")
        assert b"200" in response.split(b"\r\n", 1)[0], response[:200]
        # ...and the proxy still serves ordinary traffic afterwards.
        status, _ = http_post(proxy.url + "/v1/messages",
                              json.dumps(messages_request([])).encode(),
                              HEADERS)
        assert status == 200


@requires_core
def test_negative_content_length_does_not_hang_proxy(fake_upstream, tmp_path):
    """rfile.read(-5) reads until EOF: a negative Content-Length
    wedged the handler on a keep-alive connection."""
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        response = _raw_exchange(
            proxy.port,
            b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: -5\r\n\r\n")
        assert b"200" in response.split(b"\r\n", 1)[0], response[:200]


@requires_core
def test_chunked_request_body_is_forwarded_intact(fake_upstream, tmp_path):
    """A Transfer-Encoding: chunked request has no Content-Length;
    the old reader took that as an empty body and forwarded an
    empty request upstream. Sent over a raw socket on purpose:
    http.client silently substitutes Content-Length for a
    known-length body even with encode_chunked=True, which would
    make this test pass without any chunked framing on the wire.
    The framing below also carries a chunk extension and a trailer,
    both of which the reader must step over."""
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    body = json.dumps(messages_request([])).encode()
    half = len(body) // 2
    wire = (
        b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        + b"%x;ext=1\r\n%s\r\n" % (half, body[:half])
        + b"%x\r\n%s\r\n" % (len(body) - half, body[half:])
        + b"0\r\nX-Trailer: done\r\n\r\n")
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        response = _raw_exchange(proxy.port, wire)
        assert b"200" in response.split(b"\r\n", 1)[0], response[:200]
    assert fake_upstream.recorded[-1]["body"] == body


@requires_core
def test_query_string_does_not_disable_transformation(fake_upstream,
                                                      tmp_path):
    """Routing compared the raw path, query included, against
    /v1/messages: '/v1/messages?beta=true' silently skipped the
    transform, forwarding secret-flagged files the guard exists
    to exclude."""
    project = make_project(tmp_path)
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, _ = http_post(proxy.url + "/v1/messages?beta=true",
                              json.dumps(request).encode(), HEADERS)
        assert status == 200
    sent = json.dumps(json.loads(fake_upstream.recorded[-1]["body"]))
    assert SECRET_MARKER not in sent


@requires_core
def test_health_endpoint_tolerates_a_query_string(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, body = http_get(proxy.url + "/health?probe=1")
        assert status == 200
        assert json.loads(body)["status"] == "ok"
    assert fake_upstream.recorded == [], \
        "a health probe must be served locally, not proxied upstream"
