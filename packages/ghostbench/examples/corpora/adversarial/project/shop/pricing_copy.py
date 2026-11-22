"""Pricing rules for the adversarial fixture shop."""

TAX_RATE = 0.07
BULK_THRESHOLD = 10
BULK_DISCOUNT = 0.05


def price_order(items):
    subtotal = sum(item["price"] * item["qty"] for item in items)
    qty = sum(item["qty"] for item in items)
    total = subtotal
    if qty >= BULK_THRESHOLD:
        total = total * (1 - BULK_DISCOUNT)
    return round(total * (1 + TAX_RATE), 2)
