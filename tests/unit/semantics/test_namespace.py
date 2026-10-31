import pytest

from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types import PRIMITIVE_TYPES


def test_get_namespace():
    ns = get_namespace()
    ns2 = get_namespace()
    assert ns == ns2


def test_builtin_context_manager(namespace):
    namespace["foo"] = 42
    with namespace.enter_scope():
        namespace["bar"] = 1337

    assert namespace["foo"] == 42
    assert "bar" not in namespace


def test_builtin_types(namespace):
    for key, value in PRIMITIVE_TYPES.items():
        assert namespace[key] == value


def test_builtin_types_persist_after_clear(namespace):
    namespace.clear()
    for key, value in PRIMITIVE_TYPES.items():
        assert namespace[key] == value


def test_context_manager_constant_vars(namespace):
    with namespace.enter_scope():
        for key in environment.CONSTANT_ENVIRONMENT_VARS:
            assert key in namespace

    for key in environment.CONSTANT_ENVIRONMENT_VARS:
        assert key in namespace


def test_context_manager_mutable_vars(namespace):
    with namespace.enter_scope():
        for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
            assert key in namespace

    for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
        assert key not in namespace


def test_context_manager(namespace):
    with namespace.enter_scope():
        namespace["foo"] = 42
        with namespace.enter_scope():
            namespace["bar"] = 1337

        assert namespace["foo"] == 42
        assert "bar" not in namespace

    assert "foo" not in namespace


def test_incorrect_context_invocation(namespace):
    with pytest.raises(CompilerPanic):
        with namespace:
            pass


def test_namespace_collision(namespace):
    with namespace.enter_scope():
        namespace["foo"] = 42
        with pytest.raises(NamespaceCollision):
            namespace["foo"] = 1337


def test_namespace_collision_across_scopes(namespace):
    with namespace.enter_scope():
        namespace["foo"] = 42
        with namespace.enter_scope():
            with pytest.raises(NamespaceCollision):
                namespace["foo"] = 1337


def test_undeclared_definition(namespace):
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]


def test_undeclared_definition_across_scopes(namespace):
    with namespace.enter_scope():
        with namespace.enter_scope():
            namespace["foo"] = 42
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]


def test_namespace_collision_module_info_message(namespace):
    """Module import collision should give a clear, actionable error message."""
    from unittest.mock import MagicMock

    # Simulate a ModuleInfo-like object: has module_t but no decl_node
    mock_module_t = MagicMock()
    mock_module_t._id = "snekmate/utils/math.vy"
    mock_module_info = MagicMock()
    mock_module_info.module_t = mock_module_t
    mock_module_info.decl_node = None
    del mock_module_info.decl_node  # ensure getattr returns None

    with namespace.enter_scope():
        # Directly set without triggering validate_assignment
        super(type(namespace), namespace).__setitem__("math", mock_module_info)

        with pytest.raises(NamespaceCollision) as excinfo:
            namespace["math"] = 42

    msg = str(excinfo.value)
    assert "already imported as a module" in msg
    # source path now shown via context arrows, not in main message
    assert "snekmate/utils/math.vy" not in msg
    # hint uses the later import (attr) with valid alias syntax
    assert "import math as math_m" in msg
