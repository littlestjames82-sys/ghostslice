# Storage notes

The widget service stores its state in a local SQLite database file.
Backups are plain file copies of that database, taken nightly.

## Indexing

Lookups by widget name are the hot path, so the name column is indexed.
Full table scans only happen in the nightly report.
