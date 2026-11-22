"""Entry point for ``python -m ghostexposure``.

Delegates to :func:`ghostexposure.cli.main` and exits with its return
code. Equivalent to the installed ``ghostexposure`` command.
"""
from .cli import main
import sys
sys.exit(main())
