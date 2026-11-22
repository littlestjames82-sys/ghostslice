"""GhostDeps: dependency context pack from local evidence only.

Parses project manifests and lockfiles present in the tree and
cross-references declared dependencies against what the code actually
imports. No network, no verdicts on any dependency, no version
judgements: versions are reported as recorded in local files.

Command line: ``ghostdeps pack PROJECT [-o OUT]`` writes ``DEPS.md``
and ``deps-manifest.json``; ``ghostdeps doctor PROJECT`` reports what
was found without writing a pack. See ``ghostdeps --help``.
"""

__version__ = "0.1.0"
