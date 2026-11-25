from acme import run


def test_run():
    assert run(" hi ") == "HI"
