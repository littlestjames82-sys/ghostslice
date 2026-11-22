"""Canary fixture: code uses CANARY_API_KEY and PLAIN_SETTING.

The sibling .env holds a unique FAKE canary value for CANARY_API_KEY.
That value must never appear in any GhostEnv output, report, or
generated file. It exists only so the leak test can prove the
names-only rule: if the canary shows up anywhere else, the tool
printed a value, and the test fails.
"""
import os

CANARY_API_KEY = os.environ["CANARY_API_KEY"]
PLAIN_SETTING = os.getenv("PLAIN_SETTING", "default")
WITH_DEFAULT = os.getenv("WITH_DEFAULT", "CANARY_DEFAULT_VALUE_do_not_print")
