from pytest import raises

from vyper.exceptions import SyntaxException


def test_semicolon_prohibited(get_contract):
    code = """@external
def test() -> int128:
    a: int128 = 1; b: int128 = 2
    return a + b
    """

    with raises(SyntaxException):
        get_contract(code)


def test_valid_semicolons(get_contract):
    code = """
@external
def test() -> int128:
    a: int128 = 1
    b: int128 = 2
    s: String[300] = "this should not be a problem; because it is in a string"
    s = \"\"\"this should not be a problem; because it's in a string\"\"\"
    s = 'this should not be a problem;;; because it\\\'s in a string'
    s = '''this should not ; \'cause it\'s in a string'''
    s = "this should not be \\\"; because it's in a ;\\\"string;\\\";"
    return a + b
    """
    c = get_contract(code)
    assert c.test() == 3


def test_external_contract_definition_alias(get_contract):
    contract_1 = """
@external
def bar() -> int128:
    return 1
    """

    contract_2 = """
interface Bar:
    def bar() -> int128: nonpayable

bar_contract: Bar

@external
def foo(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c2.foo(c1.address) == 1


def test_version_pragma(get_contract):
    from vyper import __version__

    installed_version = ".".join(__version__.split(".")[:3])

    code = f"""
# @version {installed_version}

@external
def test():
    pass
    """
    assert get_contract(code)


def test_version_empty_version(assert_compile_failed, get_contract):
    code = """
#@version

@external
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_version_empty_version_mismatch(assert_compile_failed, get_contract):
    code = """
# @version 9.9.9

@external
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_version_empty_invalid_version_string(assert_compile_failed, get_contract):
    code = """
# @version hello

@external
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_unbalanced_parens(assert_compile_failed, get_contract):
    code = """
@external
def foo():
    convert(
    """

    with raises(SyntaxException):
        get_contract(code)
