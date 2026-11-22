"""Fixture: surface file so the planted-key file is not the only input."""
from config.secrets_config import API_KEY


def login(user, candidate):
    return bool(user and candidate and API_KEY)
