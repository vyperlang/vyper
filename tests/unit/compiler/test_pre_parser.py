import pytest

from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import StructureException, SyntaxException


def test_semicolon_prohibited(get_contract):
    code = """@external
def test() -> int128:
    a: int128 = 1; b: int128 = 2
    return a + b
    """

    with pytest.raises(SyntaxException):
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
    return extcall self.bar_contract.bar()
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


def test_version_pragma2(get_contract):
    # new, `#pragma` way of doing things
    from vyper import __version__

    installed_version = ".".join(__version__.split(".")[:3])

    code = f"""
#pragma version {installed_version}

@external
def test():
    pass
    """
    assert get_contract(code)


def test_evm_version_check(assert_compile_failed):
    code = """
#pragma evm-version london
    """
    assert compile_code(code, settings=Settings(evm_version=None)) is not None
    assert compile_code(code, settings=Settings(evm_version="london")) is not None
    # should fail if compile options indicate different evm version
    # from source pragma
    with pytest.raises(StructureException):
        compile_code(code, settings=Settings(evm_version="shanghai"))


def test_optimization_mode_check():
    code = """
#pragma optimize codesize
    """
    assert compile_code(code, settings=Settings(optimize=None))
    # should fail if compile options indicate different optimization mode
    # from source pragma
    with pytest.raises(StructureException):
        compile_code(code, settings=Settings(optimize=OptimizationLevel.GAS))
    with pytest.raises(StructureException):
        compile_code(code, settings=Settings(optimize=OptimizationLevel.NONE))


def test_optimization_mode_check_none():
    code = """
#pragma optimize none
    """
    assert compile_code(code, settings=Settings(optimize=None))
    # "none" conflicts with "gas"
    with pytest.raises(StructureException):
        compile_code(code, settings=Settings(optimize=OptimizationLevel.GAS))


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

    with pytest.raises(SyntaxException):
        get_contract(code)
