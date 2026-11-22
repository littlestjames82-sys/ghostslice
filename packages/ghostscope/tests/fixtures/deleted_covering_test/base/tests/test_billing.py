from billing import charge


def test_charge():
    assert charge(10) == 1000
