"""A planted secret-shaped literal never appears in any output: not in
the pack, not in the manifest, not on stdout or stderr. The redaction
must be visible as a fact (a note or a count), never the value. Two
canaries: a GitHub-token shape on a routine line, and an AWS key shape
inside an ERROR window (the plan's own planted-secret bar)."""
from conftest import (
    AWS_CANARY,
    CANARY,
    build_pack,
    all_output_text,
    load_manifest,
)


def test_canary_absent_from_every_output(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    assert CANARY not in everything, "planted secret-shaped literal leaked into output"
    # also no long fragment of it
    assert CANARY[4:20] not in everything


def test_window_secret_absent_and_shape_recorded_in_manifest(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    assert AWS_CANARY not in everything, (
        "secret-shaped literal from inside an error window leaked into output"
    )
    assert AWS_CANARY[4:16] not in everything
    manifest_text = (out / "manifest.json").read_text()
    assert "aws-access-key" in manifest_text, (
        "manifest does not record the redacted shape name (aws-access-key) "
        "as the plan requires"
    )


def test_redaction_is_recorded_as_a_fact(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    manifest_text = (out / "manifest.json").read_text().lower()
    everything = all_output_text(out, proc).lower()
    assert "redact" in manifest_text or "redact" in everything, (
        "no redaction recorded anywhere: the pack should state that a "
        "secret-shaped literal was redacted (type/count only)"
    )


def test_canary_line_context_is_not_silently_kept_verbatim(log_copy, tmp_path):
    """The line that carried the canary may survive only in redacted
    form: its surrounding text can appear, the secret cannot (covered
    above), and a redaction marker should stand where the value was if
    the line is kept at all."""
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    if "upstream auth" in everything:
        assert "redacted" in everything.lower(), (
            "canary-bearing line kept without any redaction marker"
        )
