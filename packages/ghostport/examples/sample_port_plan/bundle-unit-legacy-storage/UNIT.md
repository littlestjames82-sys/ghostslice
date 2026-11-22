# Unit unit-legacy-storage - SAMPLE CHECKLIST (illustrative, not generated)

Files: legacy/storage.py (full)
Patterns to fix:
- PYUP006 configparser.SafeConfigParser at legacy/storage.py - the
  SafeConfigParser class was removed in Python 3.12; the supported class
  is ConfigParser. (Port lists the fix direction; it does not apply it.)

Contract notes:
- Callers at signatures (must keep working): legacy/report.py imports
  load_settings from this unit.
- Already-ported dependencies in this bundle: none (leaf unit).

Test command (from profile, if any): none configured.
Covering tests (method: unit's own test files): none found in the demo.

State (filled by the GhostVerify step, never by hand):
- [ ] planned
- [ ] bundled
- [ ] ported-claimed (a claim, not verification)
- [ ] verified (requires a GhostVerify post report in the ledger)
