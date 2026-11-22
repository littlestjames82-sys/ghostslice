# GhostData examples

Two small data files and the packs GhostData builds from them. Every
value in these files is fake and made up for the example.

## customers.csv and customers-pack/

A six-row CSV export. The `email` column is redacted by name, so the
pack shows the shape of the data without a single address:

    python3 -m ghostdata pack examples/customers.csv -o examples/customers-pack
    python3 -m ghostdata check examples/customers-pack

Open `customers-pack/PROMPT.md` to see the schema table and the
sample as an agent would receive it, and `customers-pack/manifest.json`
for the full counts, the redaction record, and the sample hash.

## events.jsonl and events-pack/

A five-line JSONL event log. The `api_token` column is redacted by
name; the token values in the source are example-only strings and
none of them appear anywhere in the pack:

    python3 -m ghostdata pack examples/events.jsonl -o examples/events-pack
    python3 -m ghostdata check examples/events-pack

## Try the schema command

    python3 -m ghostdata schema examples/customers.csv

That prints the inferred schema as JSON without writing a pack. Read
it top to bottom: `format` says how the file was read, `counts`
gives the true row counts (parsed, malformed, total), and each entry
in `columns` gives one field's inferred type, null count and rate,
distinct count, and range. The `email` entry carries
`"redacted": true` with the reason `column name matches email`, and
its `min` and `max` are null: ranges are suppressed for redacted
columns so no sensitive value leaks through a bound.

Add `--no-redact` to either command only for files you own and
trust; a pack built that way records in its manifest that redaction
was disabled.

## Regenerating the packs

The two `pack` commands above rewrite the checked-in packs in place.
The packs are deterministic apart from the `generated_at` timestamp
in `manifest.json` and the token estimates, whose method is stamped
in the manifest and which vary with the estimator available on the
machine. After regenerating, `ghostdata check` on each pack is the
verification step: exit code 0 means the sample file still hashes to
the value in its manifest.

## Other shapes to try

The same three commands work on the other supported shapes, with no
extra flags when the extension is recognised:

- a `.tsv` file reads as tab-delimited;
- a `.json` file holding an array of objects streams like JSONL;
- a `.json` file holding one top-level object (a config file, say)
  is treated as a single record: its keys are the schema, the sample
  is the object itself under structural bounds, and the manifest
  records the object's key counts and depth under `structure`;
- a `.jsonl` file whose lines are bare values (numbers, strings)
  gets a single `value` column.

A top-level JSON scalar (a bare number or string on its own) is
refused with an error, because it has no fields to describe.
