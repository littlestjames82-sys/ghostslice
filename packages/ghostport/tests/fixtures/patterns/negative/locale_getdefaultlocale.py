"""Look-alike negative: locale.getlocale is the supported call."""
import locale


def current():
    return locale.getlocale()
