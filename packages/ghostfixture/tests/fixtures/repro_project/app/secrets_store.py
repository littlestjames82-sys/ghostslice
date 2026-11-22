"""Referenced module that happens to hold a secret-shaped literal.

GhostFixture must exclude this file from the repro project and
name it path + type only in its output manifest. The value below
is a FAKE, test-only canary in a Stripe live-key shape. It is not,
and has never been, a real credential.
"""

STRIPE_KEY = "sk_live_FIXTURECANARY7d3f9a2b51"
