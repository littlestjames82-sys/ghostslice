"""Polish-round regression tests (Oct 14, 2026).

Two audit findings from the documented v0.1 limits, each pinned here
against the fixed core:

1. Leading-zero digit strings (ZIP codes, padded ids) classified as
   integer, with int() silently dropping the zeros and inventing a
   numeric range (a column of 00501/07001/01234 reported min 501).
   A digit string with a leading zero is a code, not a quantity, and
   now classifies as string. A lone "0" and plain integers are
   unaffected.

2. Value-shape checks ran on string values only, so a payment card
   number stored as a native JSON number in an innocuously named
   field was never shape-redacted (and its min/max printed the card
   numbers). Native JSON integers now get the card shape check (the
   only shape that can apply to a bare integer), while Luhn-failing
   big integers stay unredacted.

The card literals below are the public Visa/Mastercard test numbers
and a one-digit-off control; none is a real credential.
"""
from __future__ import annotations

import json

from conftest import (assert_no_canaries_in_tree, column, requires_core,
                      run_schema, run_pack)

CARD_VISA = "4111111111111111"      # Luhn-valid test number
CARD_MC = "5500005555555559"        # Luhn-valid test number
NOT_A_CARD = "4111111111111112"     # one digit off: Luhn fails


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@requires_core
def test_leading_zero_column_types_as_string(tmp_path):
    path = _write(tmp_path, "zips.csv",
                  "zip,qty\n00501,3\n07001,5\n01234,2\n")
    out = run_schema(path)
    col = column(out, "zip")
    assert col["type"] == "string"
    assert col["types_seen"] == {"string": 3}
    # no fabricated numeric range over zero-padded codes
    assert col.get("min") is None and col.get("max") is None
    assert col["min_length"] == 5 and col["max_length"] == 5
    # the plain integer column next to it is untouched
    qty = column(out, "qty")
    assert qty["type"] == "integer" and qty["min"] == 2 and qty["max"] == 5


@requires_core
def test_leading_zero_sample_keeps_the_zeros(tmp_path):
    path = _write(tmp_path, "zips.csv", "zip\n00501\n07001\n01234\n")
    proc, manifest = run_pack(path, tmp_path / "pack")
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    assert "00501" in sample_text and "07001" in sample_text


@requires_core
def test_mixed_padded_and_plain_column_reports_mixed(tmp_path):
    # One padded and one unpadded value: the honest answer is mixed,
    # and the numeric range covers only the true integer.
    path = _write(tmp_path, "codes.csv", "code\n00501\n10001\n")
    out = run_schema(path)
    col = column(out, "code")
    assert col["type"] == "mixed"
    assert col["types_seen"] == {"integer": 1, "string": 1}
    assert col["min"] == 10001 and col["max"] == 10001


@requires_core
def test_lone_zero_and_plain_ints_still_integer(tmp_path):
    path = _write(tmp_path, "counts.csv", "n\n0\n42\n7\n")
    out = run_schema(path)
    col = column(out, "n")
    assert col["type"] == "integer"
    assert col["min"] == 0 and col["max"] == 42


def _cards_jsonl(tmp_path):
    rows = [
        {"acct_ref": int(CARD_VISA), "batch_no": int(NOT_A_CARD)},
        {"acct_ref": int(CARD_MC), "batch_no": int(NOT_A_CARD)},
        {"acct_ref": int(CARD_VISA), "batch_no": int(NOT_A_CARD)},
    ]
    return _write(tmp_path, "cards.jsonl",
                  "".join(json.dumps(r) + "\n" for r in rows))


@requires_core
def test_native_json_int_card_is_redacted(tmp_path):
    path = _cards_jsonl(tmp_path)
    proc, manifest = run_pack(path, tmp_path / "pack")
    col = column(manifest, "acct_ref")
    assert col["redacted"] is True
    assert "card" in col["redaction_reason"].lower()
    assert col["min"] is None and col["max"] is None
    # neither planted card number appears anywhere in the pack or in
    # command output (the Visa number is also a conftest canary)
    assert CARD_MC not in proc.stdout and CARD_MC not in proc.stderr
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    for f in (tmp_path / "pack").rglob("*"):
        if f.is_file():
            assert CARD_MC not in f.read_text(
                encoding="utf-8", errors="replace"), str(f)


@requires_core
def test_native_int_card_reason_counts_all_values(tmp_path):
    out = run_schema(_cards_jsonl(tmp_path))
    col = column(out, "acct_ref")
    assert col["redacted"] is True
    assert col["redaction_reason"] == (
        "values match card shape (3 of 3 checked)")


@requires_core
def test_luhn_failing_big_ints_are_not_redacted(tmp_path):
    # The control column: big integers that fail Luhn are ordinary
    # numeric data and must stay visible, typed, and ranged.
    path = _cards_jsonl(tmp_path)
    proc, manifest = run_pack(path, tmp_path / "pack")
    col = column(manifest, "batch_no")
    assert col["redacted"] is False
    assert col["type"] == "integer"
    assert col["min"] == int(NOT_A_CARD) and col["max"] == int(NOT_A_CARD)
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    assert NOT_A_CARD in sample_text
