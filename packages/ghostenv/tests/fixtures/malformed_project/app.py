"""Malformed fixture: code is fine; the .env file is not."""
import os

WELL_FORMED = os.environ.get("WELL_FORMED", "x")
DUPLICATED_NAME = os.environ.get("DUPLICATED_NAME", "y")
