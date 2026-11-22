"""Context transformation rules (PLAN.md MVP section 2).

Only recognisable project-file context blocks are transformed. The
user's prompt text, system instructions, conversation history,
tool calls, images, and unknown fields pass untouched. Exclusions
apply in plan order: junk/lockfiles, files flagged by the secrets
guard, then budget downgrades and duplicate drops.
"""

import json

from conftest import (
    BIG_BODY_MARKER,
    CANARY_SECRET,
    DUP_MARKER,
    LOCKFILE_MARKER,
    PROMPT_MARKER,
    SECRET_MARKER,
    ProxyProcess,
    context_block,
    context_block_mode_header,
    http_post,
    make_project,
    messages_request,
    project_sections,
    requires_core,
    write_profile,
)

HEADERS = {"x-api-key": "CANARY-API-KEY-ghostproxy-leak-test-0000000001",
           "anthropic-version": "2023-06-01", "content-type": "application/json"}


def _run(proxy, fake_upstream, request):
    raw = json.dumps(request).encode()
    status, _ = http_post(proxy.url + "/v1/messages", raw, HEADERS)
    assert status == 200
    received = fake_upstream.recorded[-1]
    return json.loads(received["body"])


@requires_core
def test_flagged_secret_file_is_excluded(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    blob = json.dumps(sent)
    assert CANARY_SECRET not in blob
    assert SECRET_MARKER not in blob, \
        "the whole flagged file is excluded (PLAN: excluded and logged, path + type only)"
    assert "def main" in blob, "unflagged context must still be transformed and sent"


@requires_core
def test_lockfile_is_excluded(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    assert LOCKFILE_MARKER not in json.dumps(sent)


@requires_core
def test_duplicate_content_sent_once(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    assert json.dumps(sent).count(DUP_MARKER) == 1, \
        "exact duplicates (dup_a.py / dup_b.py) are dropped to a single copy"


@requires_core
def test_prompt_system_and_history_untouched(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    assert sent["system"] == request["system"]
    assert sent["messages"][0] == request["messages"][0]
    assert sent["messages"][1] == request["messages"][1]
    texts = [b.get("text", "") for b in sent["messages"][2]["content"]
             if isinstance(b, dict) and b.get("type") == "text"]
    assert any(PROMPT_MARKER in t for t in texts), "the user's own prompt block is never rewritten"


@requires_core
def test_unknown_fields_tools_and_images_pass_untouched(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    extra_block = {"type": "image",
                   "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}}
    tool_block = {"type": "tool_use", "id": "toolu_1", "name": "read_file",
                  "input": {"path": "app.py"}}
    request = messages_request(
        [context_block("app.py", (project / "app.py").read_text())],
        extra={"future_field_xyz": {"nested": [1, 2, 3]}},
    )
    request["messages"][2]["content"].extend([extra_block, tool_block])
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    content = sent["messages"][2]["content"]
    assert extra_block in content
    assert tool_block in content
    assert sent["future_field_xyz"] == {"nested": [1, 2, 3]}


@requires_core
def test_budget_downgrade_keeps_signatures_drops_bodies(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    write_profile(project, {"budget_tokens": 300})
    request = messages_request(project_sections(project))
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    blob = json.dumps(sent)
    assert "def compute" in blob, "signatures survive a budget downgrade"
    assert BIG_BODY_MARKER not in blob, "bodies are what the fit ladder drops first"


@requires_core
def test_unrecognised_shape_passes_through_byte_for_byte(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    fake_upstream.mode = "mirror"
    alien = json.dumps({"not": "anthropic", "shape": ["at", "all"]}).encode()
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, _ = http_post(proxy.url + "/v1/chat/completions", alien, HEADERS)
    assert status == 200
    assert fake_upstream.recorded[-1]["body"] == alien, \
        "shapes the proxy does not understand are passed through, never guessed at"


@requires_core
def test_ghostslice_prompt_md_sections_are_recognised(fake_upstream, tmp_path):
    """The exact header GhostSlice PROMPT.md writes, mode annotation
    included, must be recognised and transformed like any other
    context section."""
    project = make_project(tmp_path)
    sections = [context_block_mode_header(name, (project / name).read_text())
                for name in ("app.py", "local_secrets.py")]
    request = messages_request(sections)
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        sent = _run(proxy, fake_upstream, request)
    assert SECRET_MARKER not in json.dumps(sent), \
        "a GhostSlice PROMPT.md section naming the secrets file must still be excluded"


@requires_core
def test_streaming_response_is_forwarded_as_stream(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    fake_upstream.mode = "stream"
    request = messages_request([], extra={"stream": True})
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, body = http_post(proxy.url + "/v1/messages",
                                 json.dumps(request).encode(), HEADERS)
    assert status == 200
    assert b"chunk-0" in body and b"chunk-2" in body
