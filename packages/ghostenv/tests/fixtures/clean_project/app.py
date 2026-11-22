"""Clean fixture app: every env name used here is documented.

All values in the sibling .env / .env.example are FAKE placeholders
for tests only. They are not, and have never been, real credentials.
"""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY = os.getenv("DEMO_API_KEY")
DEBUG = os.environ.get("APP_DEBUG", "false")
PORT = int(os.environ.get("APP_PORT", "8000"))


def describe():
    return {"db_set": bool(DATABASE_URL), "debug": DEBUG, "port": PORT}
