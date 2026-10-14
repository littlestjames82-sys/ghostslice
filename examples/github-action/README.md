# GhostSlice CI in GitHub Actions

`ghostslice-ci.yml` in this directory is a copy-paste workflow that
gates a repository's agent-context health on every pull request:
budget, lint, secrets, fit, and duplicates, in one
`ghostslice ci` run.

To use it:

1. Copy `ghostslice-ci.yml` to `.github/workflows/` in your repo.
2. Set `GHOSTSLICE_BUDGET` in the workflow's `env:` block. Size it
   from a local run: `ghostslice check-budget .` prints your
   current sliced total (estimated tokens); add headroom for
   growth. Or commit a `.ghostslice.json` with `budget_tokens`
   (`ghostslice init` generates one) and drop the `--budget` flag.
   With no budget anywhere, the budget and fit checks are skipped,
   not failed.
3. Push. The job fails when any check fails: an over-budget
   context, a lint error, a likely secret (findings fail by
   default; `--allow-secrets` downgrades them to a warning), or a
   budget the auto-fit ladder cannot reach. Duplicates and lint
   warnings only warn (add `--strict` to fail on lint warnings).

The workflow also uploads the machine-readable JSON payload and
the HTML report as build artifacts, and can post the
`--pr-comment` Markdown summary to the PR (that step needs the
`pull-requests: write` permission already declared in the sample;
it uses only the built-in `GITHUB_TOKEN`).

Install note: GhostSlice is not published on PyPI. The sample
installs it from its GitHub repository
(`pip install git+https://github.com/littlestjames82-sys/ghostslice`);
it has zero dependencies and needs Python 3.10+. Pin the ref to a
release tag (for example `@v1.0.0`) for reproducible installs.

This repository dogfoods the same command in
`.github/workflows/ghostslice-ci.yml`; that variant runs the
checked-out source tree directly instead of installing, because
its job is to test this repo's own code.
