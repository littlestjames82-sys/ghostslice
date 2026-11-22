# Decisions

## D-001 (2026-01-10)
Decision: Use SQLite for all local storage in the widget service.
Reason: Zero-config, single file, and the service runs on one machine.
Supersedes: none
Status: current
Tags: storage

## D-002 (2026-01-20)
Decision: Never rename a public command once it has shipped.
Reason: Scripts in the wild depend on command names staying stable.
Supersedes: none
Status: current
Tags: rule, naming
