import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import CallViolation, StructureException
from vyper.semantics.analysis import analyze_module


def test_self_function_call(dummy_input_bundle):
    code = """
@internal
def foo():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation):
        analyze_module(vyper_module, dummy_input_bundle)


def test_cyclic_function_call(dummy_input_bundle):
    code = """
@internal
def foo():
    self.bar()

@internal
def bar():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation):
        analyze_module(vyper_module, dummy_input_bundle)


def test_multi_cyclic_function_call(dummy_input_bundle):
    code = """
@internal
def foo():
    self.bar()

@internal
def bar():
    self.baz()

@internal
def baz():
    self.potato()

@internal
def potato():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation):
        analyze_module(vyper_module, dummy_input_bundle)


def test_global_ann_assign_callable_no_crash(dummy_input_bundle):
    code = """
balanceOf: public(HashMap[address, uint256])

@internal
def foo(to : address):
    self.balanceOf(to)
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(StructureException) as excinfo:
        analyze_module(vyper_module, dummy_input_bundle)
    assert excinfo.value.message == "HashMap[address, uint256] is not callable"
