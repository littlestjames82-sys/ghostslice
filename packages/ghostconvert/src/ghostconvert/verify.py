"""Verify a converted output directory against its source bundle.

GhostConvert already guarantees its own writes in its test suite, but
once an artifact leaves the tool (copied, committed, edited, merged,
regenerated from a different bundle) nothing checked it again. This
module is that check: it re-renders the expected artifacts in memory
with the existing renderers and compares them to what is on disk.

Verify makes no slicing decisions and judges only conversion fidelity,
not bundle sufficiency (that is GhostVerify's job). It writes nothing:
neither the bundle nor the output directory is modified, whether the
check passes or fails.

When bytes differ, verify does not stop at "different": it drills
into the artifact and names the concrete divergence (a missing
section header, a body that is no longer verbatim, sections out of
manifest order, an excluded file's section leaking in, a stale
LOSSES.md, or a stale extra Cursor rule file), so the user can tell
a hand edit from a truncated copy from a conversion of another
bundle.
"""
from __future__ import annotations

from pathlib import Path

from .bundle import Bundle
from .convert import convert


def _structural_issues(bundle: Bundle, target: str,
                       actual_by_rel: dict[str, str]) -> list[str]:
    """Concrete divergences inside the non-LOSSES artifacts present.

    For single-file targets the one artifact is inspected. For cursor,
    sections live one-per-group across rule files, so the present rule
    files are inspected together and a file is counted across all of
    them."""
    if target == "cursor":
        texts = [text for rel, text in actual_by_rel.items()
                 if rel.endswith(".mdc")]
    else:
        texts = [text for rel, text in actual_by_rel.items()
                 if rel != "LOSSES.md"]
    if not texts:
        return []
    issues: list[str] = []
    joined = "\n".join(texts)

    # Excluded files must never appear as sections in any artifact.
    # (LOSSES.md names them on purpose; it is not inspected here.)
    for f in bundle.excluded:
        if f"File: {f.path} " in joined or f"File: {f.path} (" in joined:
            issues.append(
                f"excluded file appears as a section: {f.path} "
                f"(GhostSlice excluded it; no target may carry it)")

    positions: list[tuple[str, int]] = []
    for f in bundle.included:
        if f.body is None:
            continue
        header = f"File: {f.path} (mode: {f.mode_label})"
        count = joined.count(header)
        if count == 0:
            issues.append(f"missing section: {f.path} "
                          f"(mode: {f.mode_label})")
            continue
        if count > 1:
            issues.append(f"duplicated section: {f.path} appears "
                          f"{count} times")
        if f.body not in joined:
            issues.append(f"body not present verbatim: {f.path}")
        positions.append((f.path, joined.find(header)))
    ordered = [p for _, p in positions]
    if ordered != sorted(ordered):
        issues.append(
            "sections out of manifest order: "
            + ", ".join(path for path, _ in positions))
    return issues


def verify_target(bundle: Bundle, target: str,
                  outdir: Path) -> list[str]:
    """Issues for one target's output directory; [] means verified.

    Expected artifacts are re-rendered in memory; nothing is written.
    """
    expected, _losses = convert(bundle, target)
    if not outdir.is_dir():
        return [f"output directory not found: {outdir}"]

    issues: list[str] = []
    actual_by_rel: dict[str, str] = {}
    for rel, text in expected.items():
        dest = outdir / rel
        if not dest.is_file():
            issues.append(f"missing artifact: {rel}")
            continue
        actual_bytes = dest.read_bytes()
        actual_by_rel[rel] = actual_bytes.decode("utf-8",
                                                 errors="replace")
        if actual_bytes != text.encode("utf-8"):
            if rel == "LOSSES.md":
                issues.append(
                    "LOSSES.md does not match the losses computed "
                    "from the manifest (stale or edited losses note)")
            else:
                issues.append(
                    f"artifact does not match a fresh conversion: {rel}")

    if target == "cursor":
        rules_dir = outdir / ".cursor" / "rules"
        if rules_dir.is_dir():
            for rule in sorted(rules_dir.glob("*.mdc")):
                rel = str(rule.relative_to(outdir))
                if rel not in expected:
                    issues.append(
                        f"unexpected cursor rule file: {rel} "
                        f"(not produced by converting this bundle)")

    # Only drill in when something already mismatched: on a byte-exact
    # match the structural properties hold by construction.
    if issues:
        issues.extend(_structural_issues(bundle, target, actual_by_rel))
    return issues
