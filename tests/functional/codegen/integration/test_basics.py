def test_null_code(get_contract):
    null_code = """
@external
def foo():
    pass
    """
    c = get_contract(null_code)
    c.foo()


def test_basic_code(get_contract):
    basic_code = """
@external
def foo(x: int128) -> int128:
    return x * 2

    """
    c = get_contract(basic_code)
    assert c.foo(9) == 18
