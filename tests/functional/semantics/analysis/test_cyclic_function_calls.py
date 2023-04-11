import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import CallViolation, StructureException
from vyper.semantics.analysis import validate_semantics
from vyper.semantics.analysis.module import ModuleAnalyzer


def test_self_function_call(namespace):
    code = """
@internal
def foo():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with namespace.enter_scope():
        with pytest.raises(CallViolation):
            ModuleAnalyzer(vyper_module, {}, namespace)


def test_cyclic_function_call(namespace):
    code = """
@internal
def foo():
    self.bar()

@internal
def bar():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with namespace.enter_scope():
        with pytest.raises(CallViolation):
            ModuleAnalyzer(vyper_module, {}, namespace)


def test_multi_cyclic_function_call(namespace):
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
    with namespace.enter_scope():
        with pytest.raises(CallViolation):
            ModuleAnalyzer(vyper_module, {}, namespace)


def test_global_ann_assign_callable_no_crash():
    code = """
balanceOf: public(HashMap[address, uint256])

@internal
def foo(to : address):
    self.balanceOf(to)
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(StructureException) as excinfo:
        validate_semantics(vyper_module, {})
    assert excinfo.value.message == "Value is not callable"
