from vyper.exceptions import StructureException
from pytest import raises


def test_semicolon_prohibited(get_contract):
    code = """@public
def test() -> int128:
    a: int128 = 1; b: int128 = 2
    return a + b
    """

    with raises(StructureException):
        get_contract(code)


def test_valid_semicolons(get_contract):
    code = """
@public
def test() -> int128:
    a: int128 = 1
    b: int128 = 2
    s: bytes[300] = "this should not be a problem; because it is in a string"
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
@public
def bar() -> int128:
    return 1
    """

    contract_2 = """
contract Bar():
    def bar() -> int128: modifying

bar_contract: Bar

@public
def foo(contract_address: address) -> int128:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c2.foo(c1.address) == 1


def test_version_pragma(get_contract):
    from vyper import __version__
    code = """
# @version {}

@public
def test():
    pass
    """.format(__version__)
    assert get_contract(code)


def test_version_empty_version(assert_compile_failed, get_contract):
    code = """
#@version

@public
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_version_empty_version_mismatch(assert_compile_failed, get_contract):
    code = """
# @version 9.9.9

@public
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_version_empty_invalid_version_string(assert_compile_failed, get_contract):
    code = """
# @version hello

@public
def test():
    pass
    """
    assert_compile_failed(lambda: get_contract(code))


def test_unbalanced_parens(assert_compile_failed, get_contract):
    code = """
@public
def foo():
    convert(
    """

    with raises(StructureException):
        get_contract(code)
