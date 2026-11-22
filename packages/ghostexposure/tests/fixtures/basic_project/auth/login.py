"""Fixture: authentication surface file. Deliberately imports nothing
from the rest of the fixture, so util/format.py stays unrelated and OUT.
"""


def verify_password(stored_hash, candidate):
    return stored_hash == candidate


def login(user, candidate):
    if user and verify_password(user.password_hash, candidate):
        return user.name
    return None
