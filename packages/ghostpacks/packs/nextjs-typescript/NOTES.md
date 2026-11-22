# Next.js TypeScript pack - tuning notes

Status: unscored. No GhostBench report backs this pack yet, so its
savings are unmeasured. The PLAN verification target for this pack is
a Bench Tier A comparison against a generic ghostslice init profile on
a real reference project; until that report exists in this folder and
is named in pack.json, show and list must label it unscored.

Choices:
- app/**, src/**, components/** at signatures: route and component
  surfaces first, bodies on demand per task.
- Test and spec files at strip-tests, story files excluded: stories
  duplicate component usage at full token cost.
- public/** excluded: static assets are not code context.
- Build and framework output ignored: .next, out, .vercel, .turbo,
  coverage, tsbuildinfo, and the generated next-env.d.ts.
- Docs at headings for orientation.
- Budget is a default suggestion (80000), not a measured finding.
