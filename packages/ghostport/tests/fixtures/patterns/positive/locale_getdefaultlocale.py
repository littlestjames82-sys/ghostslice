"""Positive: locale.getdefaultlocale is deprecated since 3.11, scheduled for removal."""
import locale


def current():
    return locale.getdefaultlocale()
