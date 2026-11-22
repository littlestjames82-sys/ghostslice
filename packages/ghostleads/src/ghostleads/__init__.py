"""GhostLeads: offline lead manager and scorer for local businesses.

Quick use (from the project folder)::

    PYTHONPATH=src python3 -m ghostleads import leads.csv --store leads.json
    PYTHONPATH=src python3 -m ghostleads score --store leads.json
    PYTHONPATH=src python3 -m ghostleads pack --store leads.json --out packs/

Zero-dependency Python stdlib only. Local only, no network.
No scraping, no sending: drafts only, sending is Ryan's manual gate.
Unknown fields stay blank, details are never invented.
See README.md for the input format and the scoring table.
"""

__version__ = "0.1.0"
