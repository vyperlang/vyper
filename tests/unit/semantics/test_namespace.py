import pytest

from vyper.exceptions import NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.namespace import Namespace
from vyper.semantics.types import PRIMITIVE_TYPES


def test_builtin_context_manager(fresh_namespace):
    Namespace.add("foo", 42)
    with Namespace.enter_sub_scope():
        Namespace.add("bar", 1337)

    assert Namespace.context.get()["foo"] == 42
    assert "bar" not in Namespace.context.get()


def test_builtin_types(fresh_namespace):
    for key, value in PRIMITIVE_TYPES.items():
        assert Namespace.context.get()[key] == value


def test_context_manager_constant_vars(fresh_namespace):
    with Namespace.enter_sub_scope():
        for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
            assert key in Namespace.context.get()

    for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
        assert key in Namespace.context.get()


def test_context_manager_mutable_vars(fresh_namespace):
    with Namespace.enter_sub_scope():
        for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
            assert key in Namespace.context.get()

    for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
        assert key in Namespace.context.get()


def test_context_manager(fresh_namespace):
    with Namespace.enter_sub_scope():
        Namespace.add("foo", 42)
        with Namespace.enter_sub_scope():
            Namespace.add("bar", 1337)

        assert Namespace.context.get()["foo"] == 42
        assert "bar" not in Namespace.context.get()

    assert "foo" not in Namespace.context.get()


def test_namespace_collision(fresh_namespace):
    with Namespace.enter_sub_scope():
        Namespace.add("foo", 42)
        with pytest.raises(NamespaceCollision):
            Namespace.add("foo", 1337)


def test_namespace_collision_across_scopes(fresh_namespace):
    with Namespace.enter_sub_scope():
        Namespace.add("foo", 42)
        with Namespace.enter_sub_scope():
            with pytest.raises(NamespaceCollision):
                Namespace.add("foo", 1337)


def test_undeclared_definition(fresh_namespace):
    with pytest.raises(UndeclaredDefinition):
        Namespace.context.get()["foo"]


def test_undeclared_definition_across_scopes(fresh_namespace):
    with Namespace.enter_sub_scope():
        with Namespace.enter_sub_scope():
            Namespace.add("foo", 42)
    with pytest.raises(UndeclaredDefinition):
        Namespace.context.get()["foo"]
