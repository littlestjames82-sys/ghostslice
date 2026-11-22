"""Missing fixture: code uses names that .env / .env.example lack.

- REQUIRED_IN_CODE_ONLY: used in code, in neither .env nor .env.example
- IN_ENV_NOT_EXAMPLE: used in code, present in .env, absent from example
- SHARED_OK: used everywhere, should never be flagged
All .env values here are FAKE test placeholders, not real credentials.
"""
import os

REQUIRED_IN_CODE_ONLY = os.environ["REQUIRED_IN_CODE_ONLY"]
IN_ENV_NOT_EXAMPLE = os.getenv("IN_ENV_NOT_EXAMPLE")
SHARED_OK = os.environ.get("SHARED_OK", "x")
