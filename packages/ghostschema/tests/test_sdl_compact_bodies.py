"""SDL compact-body tests (polish round, Oct 14, 2026).

The v0.1 SDL parser scanned definition bodies line by line, so any
field or enum value declared after the first on the same line was
missed, and reachability then dropped types that were only named by
those missed fields. These tests pin the token-scan behaviour: every
field/value in a body is found wherever it is declared on the line,
directives and default values never masquerade as fields or args,
and a multi-line default object contributes no pseudo-fields.
"""

from __future__ import annotations

from conftest import requires_cli
from helpers import combined, load_json, manifest_lists, run_cli

ONE_LINE = """\
# Compact style: several fields and values per line.
scalar DateTime

type Query { pet: Pet health: String }

type Pet { id: ID! name: String! status: PetStatus tag: Tag friend: Pet }

type Tag { id: ID! label: String! }

enum PetStatus { AVAILABLE PENDING SOLD }

type Unused { id: ID! note: String }
"""

DIRECTIVES_AND_DEFAULTS = """\
type Query { pet: Pet }

type Pet {
  name: String @deprecated(reason: "use title") title: String
  bestFriend(filter: FriendFilter = {statusIn: [AVAILABLE]}): Pet
}

input FriendFilter { statusIn: [PetStatus!] }

enum PetStatus { AVAILABLE PENDING @deprecated(reason: "gone") SOLD }
"""

MULTILINE_DEFAULT = """\
schema { query: Query mutation: Mutation }

type Query { pets: [Pet!]! }

type Mutation { adopt(range: RangeFilter): Pet }

type Pet { id: ID! }

input RangeFilter {
  range: Range = {
    min: 0
    max: 10
  }
  status: String
}

input Range { min: Int max: Int }
"""


def write_sdl(tmp_path, text, name="compact.graphql"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def slice_sdl(tmp_path, spec, *extra):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "-o", out, *extra])
    return proc, out


def types_by_name(outline):
    return {t["name"]: t for t in outline.get("types", [])}


def field_names(entry):
    return [f["name"] for f in entry.get("fields", [])]


@requires_cli
def test_fields_on_one_line_all_found(tmp_path):
    spec = write_sdl(tmp_path, ONE_LINE)
    proc, out = slice_sdl(tmp_path, spec, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    by_name = types_by_name(load_json(out / "outline.json"))
    assert field_names(by_name["Pet"]) == [
        "id", "name", "status", "tag", "friend"], by_name["Pet"]
    assert field_names(by_name["Tag"]) == ["id", "label"]


@requires_cli
def test_types_reachable_only_via_same_line_fields_are_kept(tmp_path):
    spec = write_sdl(tmp_path, ONE_LINE)
    proc, out = slice_sdl(tmp_path, spec, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    outline = load_json(out / "outline.json")
    kept = set(types_by_name(outline))
    # Tag and PetStatus are named only by fields declared after the
    # first field on Pet's single body line; both must be kept.
    assert {"Pet", "Tag", "PetStatus"} <= kept, kept
    assert "Unused" not in kept
    lists = manifest_lists(load_json(out / "manifest.json"))
    from helpers import any_entry_mentions
    assert any_entry_mentions(lists["dropped"], "Unused"), lists["dropped"]


@requires_cli
def test_enum_values_on_one_line_all_listed(tmp_path):
    spec = write_sdl(tmp_path, ONE_LINE)
    proc, out = slice_sdl(tmp_path, spec, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    by_name = types_by_name(load_json(out / "outline.json"))
    assert by_name["PetStatus"]["values"] == [
        "AVAILABLE", "PENDING", "SOLD"], by_name["PetStatus"]


@requires_cli
def test_directive_after_type_does_not_swallow_next_field(tmp_path):
    spec = write_sdl(tmp_path, DIRECTIVES_AND_DEFAULTS)
    proc, out = slice_sdl(tmp_path, spec, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    by_name = types_by_name(load_json(out / "outline.json"))
    assert field_names(by_name["Pet"]) == [
        "name", "title", "bestFriend"], by_name["Pet"]
    # A deprecated enum value on the same line as its neighbours is
    # still a value, and the directive adds none.
    assert by_name["PetStatus"]["values"] == [
        "AVAILABLE", "PENDING", "SOLD"], by_name["PetStatus"]


@requires_cli
def test_arg_default_object_is_not_mistaken_for_arguments(tmp_path):
    spec = write_sdl(tmp_path, DIRECTIVES_AND_DEFAULTS)
    proc, out = slice_sdl(tmp_path, spec, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    by_name = types_by_name(load_json(out / "outline.json"))
    pet_fields = {f["name"]: f for f in by_name["Pet"]["fields"]}
    args = pet_fields["bestFriend"]["args"]
    assert [(a["name"], a["type"]) for a in args] == [
        ("filter", "FriendFilter")], args


@requires_cli
def test_multiline_default_object_adds_no_pseudo_fields(tmp_path):
    spec = write_sdl(tmp_path, MULTILINE_DEFAULT)
    proc, out = slice_sdl(tmp_path, spec, "--all")
    assert proc.returncode == 0, combined(proc)
    by_name = types_by_name(load_json(out / "outline.json"))
    # The Range default object spans lines; its min/max keys belong
    # to the default, not to RangeFilter's field list.
    assert field_names(by_name["RangeFilter"]) == [
        "range", "status"], by_name["RangeFilter"]
    # ...while the same names declared as real fields on one line
    # inside Range are both found.
    assert field_names(by_name["Range"]) == ["min", "max"]
    # A one-line schema block lists both root operations.
    assert field_names(by_name["schema"]) == ["query", "mutation"]
