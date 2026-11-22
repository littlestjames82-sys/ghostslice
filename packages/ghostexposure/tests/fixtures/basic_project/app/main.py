"""Fixture: graph neighbour. Calls the auth surface, owns nothing sensitive."""
from auth.login import login


def main(user, candidate):
    return login(user, candidate)
