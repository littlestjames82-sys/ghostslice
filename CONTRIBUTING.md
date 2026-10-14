# Contributing

1. Fork and create a branch.
2. Run the tests (Python 3.10+):
   ```
   python -m pip install pytest
   PYTHONPATH=src python -m pytest tests -q
   ```
3. Keep the project dependency-free (standard library only).
4. Add tests and a `CHANGELOG.md` entry for user-visible changes.
5. Open a PR using the template; CI must pass on 3.10, 3.11 and 3.12.

Security issues: see [SECURITY.md](SECURITY.md).
