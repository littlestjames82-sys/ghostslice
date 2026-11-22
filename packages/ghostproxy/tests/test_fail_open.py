"""Fail-open battery (PLAN.md Verification bar).

Design rule under test: if the proxy errors, times out, or cannot
parse a request, the ORIGINAL request goes through untouched and the
failure is logged. A context tool must never be the reason an agent
run dies. All traffic here goes to a fake upstream on 127.0.0.1.
"""

import json

import pytest

from conftest import (
    CANARY_API_KEY,
    ProxyProcess,
    context_block,
    http_post,
    make_project,
    messages_request,
    requires_core,
    wait_for,
)

HEADERS = {"x-api-key": CANARY_API_KEY, "anthropic-version": "2023-06-01",
           "content-type": "application/json"}


def _fallback_was_logged(proxy, workdir, project):
    """True if 'fallback' shows up in proxy output or a proxy-written file."""
    haystacks = [proxy.log_text()]
    for base in (workdir, project):
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in (".log", ".jsonl", ".json", ".md"):
                try:
                    haystacks.append(path.read_text(errors="replace"))
                except OSError:
                    pass
    return any("fallback" in text.lower() for text in haystacks)


@requires_core
def test_malformed_json_forwarded_untouched(fake_upstream, tmp_path):
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    broken = b'{"model": "claude-test-model", "messages": [ {"role": '
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, body = http_post(proxy.url + "/v1/messages", broken, HEADERS)
        assert status == 200
        assert body == broken, "malformed body must reach the client response untouched"
        assert fake_upstream.recorded[-1]["body"] == broken, \
            "malformed body must reach the upstream byte for byte"
        logged = wait_for(lambda: _fallback_was_logged(proxy, tmp_path / "work", project))
        assert logged, "a parse failure must be logged as a fallback, not silent"


@requires_core
def test_oversize_body_forwarded_untouched(fake_upstream, tmp_path):
    fake_upstream.mode = "mirror"
    project = make_project(tmp_path)
    big_text = "x" * (4 * 1024 * 1024)  # ~4 MB, beyond any sane transform buffer
    request = messages_request([context_block("huge.py", big_text)])
    raw = json.dumps(request).encode()
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, body = http_post(proxy.url + "/v1/messages", raw, HEADERS, timeout=90)
        assert status == 200
        assert fake_upstream.recorded[-1]["body"] == raw, \
            "oversize bodies fail open: forwarded in full, never truncated"


@requires_core
def test_unparseable_slicing_target_fails_open(fake_upstream, tmp_path):
    """Content that breaks the slicer must not break the request.

    The context below names a Python file whose content cannot be
    parsed (unbalanced everything) and asks for it under a budget
    small enough that a transform must be attempted. Either a valid
    transformed request or the original request is acceptable at the
    upstream; a proxy error, a hang, or a dropped request is not.
    """
    project = make_project(tmp_path)
    garbage = "def broken(:\n  class (((\n" * 50
    request = messages_request([context_block("broken.py", garbage)])
    raw = json.dumps(request).encode()
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, _ = http_post(proxy.url + "/v1/messages", raw, HEADERS)
        assert status == 200
        assert fake_upstream.recorded, "request never reached the upstream"
        received = fake_upstream.recorded[-1]["body"]
        if received != raw:
            parsed = json.loads(received)  # transformed is fine, corrupt is not
            assert parsed["model"] == "claude-test-model"


@requires_core
def test_upstream_500_passes_through_and_proxy_survives(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request([])
    raw = json.dumps(request).encode()
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        fake_upstream.mode = "error500"
        status, body = http_post(proxy.url + "/v1/messages", raw, HEADERS)
        assert status == 500
        assert b"fake upstream failure" in body, \
            "the upstream's own error must reach the client, not a proxy invention"
        fake_upstream.mode = "echo_json"
        status, _ = http_post(proxy.url + "/v1/messages", raw, HEADERS)
        assert status == 200, "proxy must still serve after an upstream 500"


@requires_core
@pytest.mark.xfail(
    reason="Known core gap at time of writing (see REPORT_B.md): when the "
           "upstream drops mid-stream, the proxy leaves the client stream "
           "open until its upstream timeout instead of closing the client "
           "stream promptly; the client read times out. Fail-open covers "
           "the request path, the stream teardown path does not yet.",
    strict=False,
)
def test_mid_stream_drop_does_not_wedge_proxy(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request([], extra={"stream": True})
    raw = json.dumps(request).encode()
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        fake_upstream.mode = "stream"
        fake_upstream.server.drop_after = 1  # upstream dies mid-stream
        http_post(proxy.url + "/v1/messages", raw, HEADERS, timeout=20)
        fake_upstream.server.drop_after = None
        status, _ = http_post(proxy.url + "/v1/messages", raw, HEADERS, timeout=20)
        assert status == 200, "proxy must keep serving after a dropped stream"
