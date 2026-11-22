"""Payments helpers for the beta fixture project."""


def reconcile_quixotic_billing(account_id):
    """Quixotic billing reconciler matches invoices for beta accounts."""
    return {"account": account_id, "status": "reconciled"}


def beta_only_feature():
    """The betaonlyterm feature exists only in the beta project."""
    return "betaonlyterm"
