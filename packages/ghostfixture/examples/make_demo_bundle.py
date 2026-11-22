"""Regenerate the demo GhostSlice-shaped bundle.

Run from anywhere:

    python3 examples/make_demo_bundle.py

Writes examples/demo_bundle/ (manifest.json, PROMPT.md, files/)
for examples/demo_project/, referencing demo/pricing.py and
demo/keys.py at mode full. demo/rates.py is deliberately NOT
referenced: the walkthrough shows the import closure pulling
it in. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "demo_project"
OUT = HERE / "demo_bundle"
ENTRIES = [("demo/pricing.py", "full"), ("demo/keys.py", "full")]


def main() -> None:
    files_dir = OUT / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    prompt_parts = []
    total = 0
    for rel, mode in ENTRIES:
        text = (PROJECT / rel).read_text(encoding="utf-8")
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        tokens = max(1, (len(text) + 3) // 4)
        total += tokens
        manifest_files.append({
            "path": rel,
            "mode": mode,
            "language": "python",
            "package": None,
            "original_tokens": tokens,
            "sliced_tokens": tokens,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
        prompt_parts.append(f"# File: {rel} (mode: {mode})\n{text}")
    manifest = {
        "tool": "ghostslice",
        "version": "1.0.6",
        "generated_at": "2026-10-14T00:00:00+00:00",
        "root": str(PROJECT),
        "token_method": "example estimate (chars/4), demo bundle only",
        "files": manifest_files,
        "total_original_tokens": total,
        "total_sliced_tokens": total,
        "total_saved_tokens": 0,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "PROMPT.md").write_text(
        "\n".join(prompt_parts), encoding="utf-8")
    print(f"demo bundle written to {OUT}")


if __name__ == "__main__":
    main()
