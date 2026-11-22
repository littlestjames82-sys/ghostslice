"""Demo shop helpers (example code for the combined bundle)."""

CUTOFF_HOUR = 16  # 4pm shipping cutoff, see DECISIONS.md D-001


def ships_today(hour):
    return hour < CUTOFF_HOUR


def refund_needs_manager(amount_dollars):
    # D-002: refunds under twenty dollars need no manager.
    return amount_dollars >= 20
