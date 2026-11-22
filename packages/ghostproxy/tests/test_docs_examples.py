"""Documentation and examples contract tests.

These run without the proxy core: they pin the plain-words trust
language the PLAN requires in the README and keep the shipped
examples honest (valid JSON, a working undo path, clearly fake
example secrets). If a future edit softens the trust wording, one
of these fails on purpose.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
EXAMPLES = ROOT / "examples"


def test_readme_states_the_trust_rules_in_plain_words():
    lowered = README.lower()
    for phrase in (
        "never stores your api key",
        "never logs your api key",
        "127.0.0.1",
        "fail-open",
        "your own machine",
    ):
        assert phrase in lowered, f"README is missing the plain-words rule: {phrase!r}"


def test_readme_documents_setup_and_one_command_undo():
    assert "ANTHROPIC_BASE_URL" in README
    assert "undo" in README.lower()
    setup = (EXAMPLES / "setup-claude-code.sh").read_text()
    undo = (EXAMPLES / "undo-claude-code.sh").read_text()
    assert "ANTHROPIC_BASE_URL" in setup and "127.0.0.1" in setup
    assert "unset ANTHROPIC_BASE_URL" in undo or "ANTHROPIC_BASE_URL=" in undo


def test_readme_states_the_secrets_exclusion_rule():
    lowered = README.lower()
    assert "secret" in lowered and "excluded" in lowered and "not sent" in lowered, \
        "README must say plainly: a file the secrets guard flags is excluded and not sent"


def test_example_json_files_are_valid():
    for name in ("profile.example.json", "request.example.json",
                 "expected-transform-map.example.json"):
        json.loads((EXAMPLES / name).read_text())


def test_example_profile_keeps_body_logging_off():
    profile = json.loads((EXAMPLES / "profile.example.json").read_text())
    proxy = profile["proxy"]
    assert proxy["host"] == "127.0.0.1"
    assert proxy.get("log_bodies", False) is False


def test_sample_project_secret_is_a_labelled_fake():
    secret_file = (EXAMPLES / "sample-project" / "local_secrets.py").read_text()
    assert "CANARY" in secret_file and "NOT-A-REAL-SECRET" in secret_file
