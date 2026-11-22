"""Example mini project for GhostEnv. Names only matter here.

Every name used below is listed in the sibling .env.example with
an empty placeholder value. There is no real .env in examples/
on purpose: examples ship, secrets do not.
"""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
DEMO_API_KEY = os.getenv("DEMO_API_KEY")
CACHE_TTL = os.environ.get("CACHE_TTL_SECONDS", "300")
