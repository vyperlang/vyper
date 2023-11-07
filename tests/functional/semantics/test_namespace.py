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
        for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
            assert key in namespace

    for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
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
