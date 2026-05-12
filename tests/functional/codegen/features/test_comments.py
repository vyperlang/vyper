def test_comment_test(get_contract):
    comment_test = """
@external
def foo() -> int128:
    # Returns 3
    return 3
    """

    c = get_contract(comment_test)
    assert c.foo() == 3
    print("Passed comment test")


def test_docstring_only_function_body(get_contract):
    # a function whose body is only a docstring should compile (not IndexError)
    code = """
@external
def foo():
    "notice me"

@external
def bar() -> int128:
    "another docstring"
    return 3
    """

    c = get_contract(code)
    assert c.bar() == 3
