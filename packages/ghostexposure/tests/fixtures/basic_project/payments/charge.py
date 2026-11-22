"""Fixture: payments surface file (import pattern fires)."""
import stripe


def charge_card(token, amount_cents):
    return stripe.Charge.create(source=token, amount=amount_cents)
