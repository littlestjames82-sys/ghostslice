"""Example surface file: matches the auth/** glob in the example pack."""


def verify_password(stored_hash, candidate):
    return stored_hash == candidate


def login(user, candidate):
    return user is not None and verify_password(user.password_hash, candidate)
