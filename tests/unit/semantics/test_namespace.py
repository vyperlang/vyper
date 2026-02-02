import pytest

import vyper.semantics.namespace as namespace
from vyper.exceptions import NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.namespace import namespace_builder_context
from vyper.semantics.types import PRIMITIVE_TYPES


def test_builtin_context_manager(fresh_namespace):
    namespace_builder_context.get()["foo"] = 42
    with namespace.sub_scope():
        namespace_builder_context.get()["bar"] = 1337

    assert namespace_builder_context.get()["foo"] == 42
    assert "bar" not in namespace_builder_context.get()


def test_builtin_types(fresh_namespace):
    for key, value in PRIMITIVE_TYPES.items():
        assert namespace_builder_context.get()[key] == value


def test_builtin_types_persist_after_clear(fresh_namespace):
    namespace_builder_context.get().clear()
    for key, value in PRIMITIVE_TYPES.items():
        assert namespace_builder_context.get()[key] == value


def test_context_manager_constant_vars(fresh_namespace):
    with namespace.sub_scope():
        for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
            assert key in namespace_builder_context.get()

    for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
        assert key in namespace_builder_context.get()


def test_context_manager_mutable_vars(fresh_namespace):
    with namespace.sub_scope():
        for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
            assert key in namespace_builder_context.get()

    for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
        assert key in namespace_builder_context.get()


def test_context_manager(fresh_namespace):
    with namespace.sub_scope():
        namespace_builder_context.get()["foo"] = 42
        with namespace.sub_scope():
            namespace_builder_context.get()["bar"] = 1337

        assert namespace_builder_context.get()["foo"] == 42
        assert "bar" not in namespace_builder_context.get()

    assert "foo" not in namespace_builder_context.get()


def test_namespace_collision(fresh_namespace):
    with namespace.sub_scope():
        namespace_builder_context.get()["foo"] = 42
        with pytest.raises(NamespaceCollision):
            namespace_builder_context.get()["foo"] = 1337


def test_namespace_collision_across_scopes(fresh_namespace):
    with namespace.sub_scope():
        namespace_builder_context.get()["foo"] = 42
        with namespace.sub_scope():
            with pytest.raises(NamespaceCollision):
                namespace_builder_context.get()["foo"] = 1337


def test_undeclared_definition(fresh_namespace):
    with pytest.raises(UndeclaredDefinition):
        namespace_builder_context.get()["foo"]


def test_undeclared_definition_across_scopes(fresh_namespace):
    with namespace.sub_scope():
        with namespace.sub_scope():
            namespace_builder_context.get()["foo"] = 42
    with pytest.raises(UndeclaredDefinition):
        namespace_builder_context.get()["foo"]
