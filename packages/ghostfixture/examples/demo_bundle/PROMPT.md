# File: demo/pricing.py (mode: full)
"""Referenced by the demo bundle.

Imports demo.rates, which the bundle does NOT reference: the
import closure is what brings rates.py into the fixture.
"""
from demo.rates import TAX_RATE


def price_with_tax(amount):
    return round(amount * (1 + TAX_RATE), 2)

# File: demo/keys.py (mode: full)
"""Referenced by the demo bundle, but flagged and excluded.

The value below is a FAKE, example-only literal in a secret
shape, planted so the walkthrough can show the exclusion. It is
not, and has never been, a real credential.
"""

API_KEY = "sk_live_EXAMPLEONLY0000000000"
