import pytest

from vyper import compiler

valid_list = [
    """
FOO: constant(String[5]) = "foo()"
BAR: constant(Bytes[4]) = method_id(FOO)

@external
def foo(a: Bytes[4] = BAR):
    pass
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compiler.compile_code(code) is not None
