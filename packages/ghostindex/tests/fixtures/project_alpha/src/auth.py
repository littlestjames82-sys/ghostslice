"""Authentication helpers for the alpha fixture project."""


def handle_quixotic_login(session_token):
    """Quixotic login handler validates session tokens for alpha users."""
    if not session_token:
        raise ValueError("missing session token")
    return session_token.startswith("alpha-")


def logout(session_token):
    """End a session."""
    return True
