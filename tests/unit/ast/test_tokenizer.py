"""
Tests that the tokenizer / parser are passing correct source location
info to the AST
"""
import pytest

from vyper.ast.parse import parse_to_ast
from vyper.compiler import compile_code
from vyper.exceptions import UndeclaredDefinition


def test_log_token_aligned():
    # GH issue 3430
    code = """
event A:
    b: uint256

@external
def f():
    log A(b=d)
    """
    with pytest.raises(UndeclaredDefinition) as e:
        compile_code(code)

    expected = """
 'd' has not been declared.

  function "f", line 7:12 
       6 def f():
  ---> 7     log A(b=d)
  -------------------^
       8
    """  # noqa: W291
    assert expected.strip() == str(e.value).strip()


def test_log_token_aligned2():
    # GH issue 3059
    code = """
interface Contract:
    def foo(): nonpayable

event MyEvent:
    a: address

@external
def foo(c: Contract):
    log MyEvent(a=c.address)
    """
    compile_code(code)


def test_log_token_aligned3():
    # https://github.com/vyperlang/vyper/pull/3808#pullrequestreview-1900570163
    code = """
import ITest

implements: ITest

event Foo:
    a: address

@external
def foo(u: uint256):
    log Foo(empty(address))
    log i.Foo(empty(address))
    """
    # not semantically valid code, check we can at least parse it
    assert parse_to_ast(code) is not None


def test_log_token_aligned4():
    # GH issue 4139
    code = """
b: public(uint256)

event Transfer:
    random: indexed(uint256)
    shi: uint256

@external
def transfer():
    log Transfer(T(self).b(), 10)
    return
    """
    # not semantically valid code, check we can at least parse it
    assert parse_to_ast(code) is not None


def test_long_string_non_coding_token():
    # GH issue 2258
    code = '\r[[]]\ndef _(e:[],l:[]):\n    """"""""""""""""""""""""""""""""""""""""""""""""""""""\n    f.n()'  # noqa: E501
    # not valid code, but should at least parse
    assert parse_to_ast(code) is not None
