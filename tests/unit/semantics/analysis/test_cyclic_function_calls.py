import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import CallViolation, StructureException
from vyper.semantics.analysis import analyze_module


def test_self_function_call():
    code = """
@internal
def foo():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation) as e:
        analyze_module(vyper_module)

    assert e.value.message == "Contract contains cyclic function call: foo -> foo"


def test_self_function_call2():
    code = """
@external
def foo():
    self.bar()

@internal
def bar():
    self.bar()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation) as e:
        analyze_module(vyper_module)

    assert e.value.message == "Contract contains cyclic function call: foo -> bar -> bar"


def test_cyclic_function_call():
    code = """
@internal
def foo():
    self.bar()

@internal
def bar():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation) as e:
        analyze_module(vyper_module)

    assert e.value.message == "Contract contains cyclic function call: foo -> bar -> foo"


def test_multi_cyclic_function_call():
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
    with pytest.raises(CallViolation) as e:
        analyze_module(vyper_module)

    expected_message = "Contract contains cyclic function call: foo -> bar -> baz -> potato -> foo"

    assert e.value.message == expected_message


def test_multi_cyclic_function_call2():
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
    self.bar()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(CallViolation) as e:
        analyze_module(vyper_module)

    expected_message = "Contract contains cyclic function call: foo -> bar -> baz -> potato -> bar"

    assert e.value.message == expected_message


def test_global_ann_assign_callable_no_crash():
    code = """
balanceOf: public(HashMap[address, uint256])

@internal
def foo(to : address):
    self.balanceOf(to)
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(StructureException) as excinfo:
        analyze_module(vyper_module)
    assert excinfo.value.message == "HashMap[address, uint256] is not callable"
