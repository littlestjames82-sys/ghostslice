"""Fixture sanity - needs no core. Pins the fixtures themselves so a
behavioural failure can never be a fixture lie.

Fixtures:
  clean/                        one narrow python3 server, no findings due
  messy/mcp.json                duplicate pair (same command + args),
                                filesystem access to "/", a missing
                                command, a shell server, and a server
                                whose env holds FAKE canary secrets
  duplicates_across_files/      the same server name + definition in
                                mcp.json and .cursor/mcp.json
  duplicate_scopes/             the same server name at top level and
                                nested under projects.<path>.mcpServers
  invalid/broken.json           deliberately unparseable JSON
  empty/mcp.json                {"mcpServers": {}}
  vscode/mcp.json               VS Code shape: top-level "servers"
Examples: every examples/*.json parses, and every env value under a
KEY / TOKEN / SECRET / PASSWORD name is a FAKE-labelled value.
"""
import json
import re
import shutil
from pathlib import Path

from conftest import EXAMPLES, FAKE_SECRET_CANARIES, FIXTURES

SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|AUTH)", re.I)


def load(path):
    return json.loads(Path(path).read_text())


def servers_of(data):
    for key in ("mcpServers", "servers"):
        if isinstance(data.get(key), dict):
            return data[key]
    mcp = data.get("mcp")
    if isinstance(mcp, dict) and isinstance(mcp.get("servers"), dict):
        return mcp["servers"]
    return {}


def test_valid_fixtures_parse():
    for p in sorted(FIXTURES.rglob("*.json")):
        if "invalid" in p.parts:
            continue
        load(p)  # raises if broken


def test_invalid_fixture_really_is_invalid():
    try:
        load(FIXTURES / "invalid" / "broken.json")
    except json.JSONDecodeError:
        return
    raise AssertionError("invalid/broken.json unexpectedly parses")


def test_clean_fixture_is_genuinely_clean():
    servers = servers_of(load(FIXTURES / "clean" / "mcp.json"))
    assert list(servers) == ["docs-reader"]
    srv = servers["docs-reader"]
    assert srv["command"] == "python3"
    assert shutil.which("python3"), "python3 missing from this machine"
    assert "/" not in srv["args"], "clean fixture must not grant root"
    assert not any(SECRET_NAME.search(k) for k in srv.get("env", {}))


def test_messy_fixture_plants_each_finding():
    servers = servers_of(load(FIXTURES / "messy" / "mcp.json"))
    # Duplicate pair: two names, identical command + args.
    a, b = servers["filesystem-main"], servers["filesystem-copy"]
    assert (a["command"], a["args"]) == (b["command"], b["args"])
    # Broad permission: filesystem server granted the filesystem root.
    assert "/" in a["args"]
    # Missing command: planted name must really be absent.
    missing = servers["missing-tool"]["command"]
    assert missing == "ghostmcp-nonexistent-binary-9f3k"
    assert shutil.which(missing) is None
    # A shell server is present for broad-permission heuristics.
    assert servers["shell-server"]["command"] in ("bash", "sh")


def test_messy_fixture_secrets_are_fake_canaries_only():
    servers = servers_of(load(FIXTURES / "messy" / "mcp.json"))
    env = servers["secret-server"]["env"]
    for canary in FAKE_SECRET_CANARIES:
        assert canary in env.values(), canary
    for name, value in env.items():
        if SECRET_NAME.search(name):
            assert value.startswith("FAKE-"), (name, value)


def test_duplicates_across_files_fixture_really_duplicates():
    generic = servers_of(load(
        FIXTURES / "duplicates_across_files" / "mcp.json"))
    cursor = servers_of(load(
        FIXTURES / "duplicates_across_files" / ".cursor" / "mcp.json"))
    assert "shared-server" in generic and "shared-server" in cursor
    assert generic["shared-server"] == cursor["shared-server"]
    assert "generic-only" in generic and "cursor-only" in cursor


def test_duplicate_scopes_fixture_really_duplicates():
    data = load(FIXTURES / "duplicate_scopes" / "mcp.json")
    top = servers_of(data)
    nested = data["projects"]["/tmp/example-project"]["mcpServers"]
    assert "scoped-server" in top and "scoped-server" in nested
    assert top["scoped-server"] == nested["scoped-server"]


def test_messy_fixture_plants_a_missing_file():
    servers = servers_of(load(FIXTURES / "messy" / "mcp.json"))
    arg = servers["stale-script"]["args"][0]
    assert arg == "./definitely_missing_script_9f3k.py"
    assert not (FIXTURES / "messy" / arg).exists()


def test_empty_and_vscode_fixtures():
    assert servers_of(load(FIXTURES / "empty" / "mcp.json")) == {}
    vscode = load(FIXTURES / "vscode" / "mcp.json")
    assert "vscode-docs" in servers_of(vscode)


def test_examples_parse_and_carry_fake_values_only():
    files = sorted(EXAMPLES.glob("*.json"))
    assert files, "no example configs built yet"
    for p in files:
        data = load(p)
        for srv in servers_of(data).values():
            for name, value in (srv.get("env") or {}).items():
                if SECRET_NAME.search(name):
                    assert "FAKE" in str(value), (p.name, name, value)
                    assert "not-a-real-secret" in str(value) or \
                        "FAKE" in str(value)
