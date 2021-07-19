import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import CallViolation
from vyper.semantics.validation.module import ModuleNodeVisitor


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
            ModuleNodeVisitor(vyper_module, {}, namespace)


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
            ModuleNodeVisitor(vyper_module, {}, namespace)
