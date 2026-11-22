"""GhostConsole web app: the local front end for the Ghost ecosystem.

The app is a thin local shell. It keeps a registry of the user's own
project directories, starts `ghostworkflow run` as a subprocess when
asked, and renders what the workflow already wrote to disk
(workflow-report.json and the GhostConsole board.html). It never runs
an engine directly and never edits an engine report.
"""

__version__ = "0.1.0"
