import pytest

from vyper.ast import parse_to_ast
from vyper.context.validation.module import ModuleNodeVisitor
from vyper.exceptions import CallViolation


def test_cyclic_function_call(namespace):
    code = """
@private
def foo():
    self.bar()

@private
def bar():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with namespace.enter_builtin_scope():
        with pytest.raises(CallViolation):
            ModuleNodeVisitor(vyper_module, {}, namespace)


def test_multi_cyclic_function_call(namespace):
    code = """
@private
def foo():
    self.bar()

@private
def bar():
    self.baz()

@private
def baz():
    self.potato()

@private
def potato():
    self.foo()
    """
    vyper_module = parse_to_ast(code)
    with namespace.enter_builtin_scope():
        with pytest.raises(CallViolation):
            ModuleNodeVisitor(vyper_module, {}, namespace)
