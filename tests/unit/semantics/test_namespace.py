import pytest

from vyper.exceptions import NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.namespace import Namespace
from vyper.semantics.types import PRIMITIVE_TYPES


def test_builtin_context_manager(fresh_namespace):
    Namespace.builder_context.get()["foo"] = 42
    with Namespace.sub_scope():
        Namespace.builder_context.get()["bar"] = 1337

    assert Namespace.builder_context.get()["foo"] == 42
    assert "bar" not in Namespace.builder_context.get()


def test_builtin_types(fresh_namespace):
    for key, value in PRIMITIVE_TYPES.items():
        assert Namespace.builder_context.get()[key] == value


def test_builtin_types_persist_after_clear(fresh_namespace):
    Namespace.builder_context.get().clear()
    for key, value in PRIMITIVE_TYPES.items():
        assert Namespace.builder_context.get()[key] == value


def test_context_manager_constant_vars(fresh_namespace):
    with Namespace.sub_scope():
        for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
            assert key in Namespace.builder_context.get()

    for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
        assert key in Namespace.builder_context.get()


def test_context_manager_mutable_vars(fresh_namespace):
    with Namespace.sub_scope():
        for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
            assert key in Namespace.builder_context.get()

    for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
        assert key in Namespace.builder_context.get()


def test_context_manager(fresh_namespace):
    with Namespace.sub_scope():
        Namespace.builder_context.get()["foo"] = 42
        with Namespace.sub_scope():
            Namespace.builder_context.get()["bar"] = 1337

        assert Namespace.builder_context.get()["foo"] == 42
        assert "bar" not in Namespace.builder_context.get()

    assert "foo" not in Namespace.builder_context.get()


def test_namespace_collision(fresh_namespace):
    with Namespace.sub_scope():
        Namespace.builder_context.get()["foo"] = 42
        with pytest.raises(NamespaceCollision):
            Namespace.builder_context.get()["foo"] = 1337


def test_namespace_collision_across_scopes(fresh_namespace):
    with Namespace.sub_scope():
        Namespace.builder_context.get()["foo"] = 42
        with Namespace.sub_scope():
            with pytest.raises(NamespaceCollision):
                Namespace.builder_context.get()["foo"] = 1337


def test_undeclared_definition(fresh_namespace):
    with pytest.raises(UndeclaredDefinition):
        Namespace.builder_context.get()["foo"]


def test_undeclared_definition_across_scopes(fresh_namespace):
    with Namespace.sub_scope():
        with Namespace.sub_scope():
            Namespace.builder_context.get()["foo"] = 42
    with pytest.raises(UndeclaredDefinition):
        Namespace.builder_context.get()["foo"]
