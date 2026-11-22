"""Referenced by the demo bundle.

Imports demo.rates, which the bundle does NOT reference: the
import closure is what brings rates.py into the fixture.
"""
from demo.rates import TAX_RATE


def price_with_tax(amount):
    return round(amount * (1 + TAX_RATE), 2)
