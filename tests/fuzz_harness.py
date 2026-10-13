"""Deterministic fuzz corpus for GhostSlice (v0.21, G16).

A seeded pseudo-random corpus: a handful of small, real-shaped
source files (one per format) mutated by a fixed recipe book —
truncations, bit flips, NUL / invalid-UTF-8 injection, BOM and
line-ending shuffles, brace/quote unbalancing, chunk duplication.
No external corpora, no network, no wall-clock randomness: the
same seed builds the same corpus on every run and every machine,
so a failure reproduces by case name alone.

The corpus feeds tests/test_v21_fuzz.py, which drives every public
entry point over it under one invariant: no unhandled exception —
typed errors mapped to CLI exit codes are fine, tracebacks are
not, and whatever output IS produced must still validate.
"""
from __future__ import annotations

import random

SEED = 20261013  # the marathon date; bump only with a corpus review

# ---------------------------------------------------------------------------
# Seed files: small but real-shaped, one per format the tool reads.
# ---------------------------------------------------------------------------

_PY = '''"""Module docstring."""
import os
from collections import Counter

LIMIT = 10


class Store:
    """A store."""

    def __init__(self, name):
        self.name = name
        self.items = {}

    def total(self):
        return sum(self.items.values())


def helper(x):
    # café note with a unicode é
    if x > LIMIT:
        return {"a": [1, 2, {"b": "text"}]}
    return None
'''

_JS = '''// header comment
import { readFile } from "fs";

export class Api {
  constructor(name) {
    this.name = name;
  }
  async fetch(url) {
    const tpl = `path ${url} end`;
    return { ok: true, tpl };
  }
}

export function helper(x) {
  if (x && x > 2) { return "a}b"; }
  return null;
}
'''

_GO = '''package main

import "fmt"

type Store struct {
	Name  string
	Items map[string]int
}

func (s *Store) Total() int {
	total := 0
	for _, v := range s.Items {
		total += v
	}
	return total
}

func main() {
	fmt.Println(Store{}.Total())
}
'''

_JSON = '''{
  "name": "demo",
  "version": 3,
  "private": true,
  "config": {
    "nested": {"deep": [1, 2, {"x": "y"}]},
    "list": ["a", "b"]
  }
}
'''

_YAML = '''name: demo
version: 3
config:
  nested:
    deep:
      - a
      - b
  flag: true
items:
  - one
  - two
'''

_TOML = '''title = "demo"
version = 3

[owner]
name = "someone"

[server]
ports = [8000, 8001]
'''

_MD = '''# Title

Intro paragraph with *emphasis* and a [link](https://example.com).

## Section

- one
- two

```python
def fenced():
    return 1
```

### Sub

Closing text.
'''

_IPYNB = '''{
 "cells": [
  {"cell_type": "markdown", "source": ["# Notes\\n", "text"], "metadata": {}},
  {"cell_type": "code", "source": ["def f():\\n", "    return 1\\n"], "metadata": {}, "outputs": [], "execution_count": 1}
 ],
 "metadata": {"kernelspec": {"name": "python3"}},
 "nbformat": 4,
 "nbformat_minor": 5
}
'''

_RS = '''use std::collections::HashMap;

pub struct Store {
    name: String,
    items: HashMap<String, i32>,
}

impl Store {
    pub fn total(&self) -> i32 {
        self.items.values().sum()
    }
}

fn main() {
    println!("hi");
}
'''

SEED_FILES: dict[str, bytes] = {
    "mod.py": _PY.encode(),
    "api.js": _JS.encode(),
    "api.ts": _JS.replace("fs", "node:fs").encode(),
    "main.go": _GO.encode(),
    "data.json": _JSON.encode(),
    "conf.yaml": _YAML.encode(),
    "conf.toml": _TOML.encode(),
    "doc.md": _MD.encode(),
    "nb.ipynb": _IPYNB.encode(),
    "lib.rs": _RS.encode(),
}

# ---------------------------------------------------------------------------
# Mutation recipes. Each takes (rng, bytes) -> bytes and is applied
# once per seed file; the rng is re-seeded per (file, recipe) from
# the master seed, so corpus order and content are stable.
# ---------------------------------------------------------------------------


def _truncate(rng: random.Random, data: bytes) -> bytes:
    return data[: rng.randrange(0, len(data))]


def _bitflips(rng: random.Random, data: bytes) -> bytes:
    buf = bytearray(data)
    for _ in range(rng.randrange(1, 9)):
        i = rng.randrange(len(buf))
        buf[i] ^= 1 << rng.randrange(8)
    return bytes(buf)


def _nul_inject(rng: random.Random, data: bytes) -> bytes:
    buf = bytearray(data)
    for _ in range(rng.randrange(1, 6)):
        buf.insert(rng.randrange(len(buf) + 1), 0)
    return bytes(buf)


def _invalid_utf8(rng: random.Random, data: bytes) -> bytes:
    bad = [b"\x80", b"\xc3\x28", b"\xed\xa0\x80", b"\xf5\x88\x98",
           b"\xe2\x82", b"\xff", b"\xfe", b"\xc0\xaf"]
    buf = bytearray(data)
    for _ in range(rng.randrange(1, 5)):
        seq = rng.choice(bad)
        pos = rng.randrange(len(buf) + 1)
        buf[pos:pos] = seq
    return bytes(buf)


def _bom_shuffle(rng: random.Random, data: bytes) -> bytes:
    bom = rng.choice([b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff",
                      b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"])
    body = data
    if rng.random() < 0.5:
        # Re-encode the ASCII skeleton in the BOM's wide encoding.
        codec = {b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be",
                 b"\xff\xfe\x00\x00": "utf-32-le",
                 b"\x00\x00\xfe\xff": "utf-32-be"}.get(bom)
        if codec:
            body = body.decode("utf-8", errors="replace").encode(codec)
    return bom + body


def _eol_shuffle(rng: random.Random, data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    style = rng.choice(["\r\n", "\r", "\n\r\n", "\r\r"])
    return text.replace("\n", style).encode("utf-8", errors="replace")


def _unbalance(rng: random.Random, data: bytes) -> bytes:
    extra = rng.choice([b"{" * 37, b"}" * 41, b'"' * 13, b"(" * 29,
                        b"[" * 53, b"def broken(:\n", b"\x00" * 64])
    pos = rng.randrange(len(data) + 1)
    return data[:pos] + extra + data[pos:]


def _duplicate_chunk(rng: random.Random, data: bytes) -> bytes:
    if len(data) < 8:
        return data * 40
    a = rng.randrange(0, len(data) - 4)
    b = rng.randrange(a + 4, len(data))
    chunk = data[a:b]
    return data + chunk * rng.randrange(5, 40)


def _line_shuffle(rng: random.Random, data: bytes) -> bytes:
    lines = data.split(b"\n")
    rng.shuffle(lines)
    return b"\n".join(lines)


RECIPES = {
    "truncate": _truncate,
    "bitflips": _bitflips,
    "nul": _nul_inject,
    "badutf8": _invalid_utf8,
    "bom": _bom_shuffle,
    "eol": _eol_shuffle,
    "unbalance": _unbalance,
    "dup": _duplicate_chunk,
    "shuffle": _line_shuffle,
}


def mutated_corpus(seed: int = SEED) -> list[tuple[str, bytes]]:
    """[(case_name, bytes)]: every seed file raw + one mutation per
    recipe. Case names are `<file>/<recipe>` (raw: `<file>/raw`)."""
    cases: list[tuple[str, bytes]] = []
    for fname, data in sorted(SEED_FILES.items()):
        cases.append((f"{fname}/raw", data))
        for rname, fn in sorted(RECIPES.items()):
            rng = random.Random(f"{seed}:{fname}:{rname}")
            cases.append((f"{fname}/{rname}", fn(rng, data)))
    return cases


# ---------------------------------------------------------------------------
# Malformed-profile / manifest / ledger families.
# ---------------------------------------------------------------------------

PROFILE_CASES: dict[str, bytes] = {
    "valid": b'{"budget_tokens": 1000, "modes": {"*.log": "exclude"}}',
    "empty": b"",
    "truncated": b'{"budget_tokens": 100',
    "not-json": b"this is not json",
    "top-list": b"[1, 2, 3]",
    "top-string": b'"just a string"',
    "top-null": b"null",
    "ignore-int": b'{"ignore": 42}',
    "ignore-str": b'{"ignore": "vendor/**"}',
    "ignore-mixed": b'{"ignore": ["ok", 7]}',
    "modes-list": b'{"modes": ["full"]}',
    "modes-int-value": b'{"modes": {"*.py": 3}}',
    "budget-str": b'{"budget_tokens": "abc"}',
    "budget-bool": b'{"budget_tokens": true}',
    "budget-list": b'{"budget_tokens": [100]}',
    "model-int": b'{"model": 7}',
    "entry-mixed": b'{"entry_points": ["a.py", null]}',
    "bad-utf8": b'{"model": "caf\xe9"}',
    "preset-bad": b'{"preset": "nope"}',
    "lint-bad": b'{"lint": {"L999": {"severity": "error"}}}',
}

LEDGER_CASES: dict[str, bytes] = {
    "valid": b'{"kind": "export", "before_tokens": 10, "after_tokens": 4, "at": "2026-10-13T00:00:00Z"}\n',
    "empty": b"",
    "garbage-lines": b"not json\n[1,2]\nnull\ntrue\n",
    "truncated-line": b'{"kind": "export", "before_tokens": 1',
    "wrong-types": b'{"kind": 5, "before_tokens": "x", "after_tokens": null}\n',
    "huge-numbers": b'{"kind": "export", "before_tokens": 99999999999999999999, "after_tokens": 1}\n',
    "nul-bytes": b'{"kind": "export"}\n\x00\x00\n',
    "bad-utf8": b'{"kind": "caf\xe9"}\n',
}


def manifest_mutations(valid_manifest: bytes) -> dict[str, bytes]:
    """Named corruptions of a real manifest.json's bytes."""
    import json as _json
    data = _json.loads(valid_manifest)
    cases = {
        "truncated": valid_manifest[: len(valid_manifest) // 2],
        "not-json": b"{oops",
        "top-list": b"[1, 2]",
        "top-string": b'"manifest"',
        "empty-object": b"{}",
        "files-dict": _json.dumps({**data, "files": {"a.py": {}}}).encode(),
        "files-null": _json.dumps({**data, "files": None}).encode(),
        "entry-string": _json.dumps({**data, "files": ["a.py"]}).encode(),
        "entry-missing-keys": _json.dumps(
            {**data, "files": [{"path": "a.py"}]}).encode(),
        "totals-string": _json.dumps(
            {**data, "total_sliced_tokens": "many",
             "total_original_tokens": "lots"}).encode(),
        "no-totals": _json.dumps(
            {k: v for k, v in data.items()
             if not k.startswith("total_")}).encode(),
        "bad-utf8": valid_manifest.replace(b'"', b'"\xe9', 1),
    }
    return cases
