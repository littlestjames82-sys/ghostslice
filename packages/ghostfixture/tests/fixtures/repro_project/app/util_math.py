"""Second-level local dependency: helper.py imports this module.

Not referenced by the fixture bundle and not imported by any
referenced file directly. Only a recursive import closure
(main.py -> helper.py -> util_math.py) brings it into the
fixture, as the plan's verification bar requires.
"""


def add_all(values):
    total = 0
    for value in values:
        total += value
    return total
