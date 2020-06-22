import pytest

from vyper.context import environment
from vyper.context.namespace import get_namespace
from vyper.context.types import get_types
from vyper.exceptions import (
    CompilerPanic,
    NamespaceCollision,
    UndeclaredDefinition,
)


def test_get_namespace(namespace):
    ns = get_namespace()
    ns2 = get_namespace()
    assert ns == ns2 == namespace


def test_clear(namespace):
    namespace["foo"] = 42
    assert "foo" in namespace

    namespace.clear()
    assert "foo" not in namespace


def test_builtin_context_manager(namespace):
    namespace["foo"] = 42
    with namespace.enter_builtin_scope():
        namespace["bar"] = 1337

    assert namespace["foo"] == 42
    assert "bar" not in namespace


def test_builtin_context_manager_types(namespace):
    with namespace.enter_builtin_scope():
        for key, value in get_types().items():
            assert namespace[key] == value

    for key, value in get_types().items():
        assert namespace[key] == value


def test_builtin_context_manager_conamespacetant_vars(namespace):
    with namespace.enter_builtin_scope():
        for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
            assert key in namespace

    for key in environment.CONSTANT_ENVIRONMENT_VARS.keys():
        assert key in namespace


def test_builtin_context_manager_mutable_vars(namespace):
    with namespace.enter_builtin_scope():
        for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
            assert key in namespace

    for key in environment.MUTABLE_ENVIRONMENT_VARS.keys():
        assert key not in namespace


def test_builtin_context_manager_wrong_sequence(namespace):
    with namespace.enter_builtin_scope():
        # fails because builtin scope may only be entered once
        with pytest.raises(CompilerPanic):
            with namespace.enter_builtin_scope():
                pass


def test_context_manager(namespace):
    with namespace.enter_builtin_scope():
        namespace["foo"] = 42
        with namespace.enter_scope():
            namespace["bar"] = 1337

        assert namespace["foo"] == 42
        assert "bar" not in namespace

    assert "foo" not in namespace


def test_context_manager_wrong_sequence(namespace):
    with pytest.raises(CompilerPanic):
        with namespace.enter_scope():
            pass


def test_incorrect_context_invokation(namespace):
    with pytest.raises(CompilerPanic):
        with namespace:
            pass


def test_namespace_collision(namespace):
    namespace["foo"] = 42
    with pytest.raises(NamespaceCollision):
        namespace["foo"] = 1337


def test_namespace_collision_across_scopes(namespace):
    with namespace.enter_builtin_scope():
        namespace["foo"] = 42
        with namespace.enter_scope():
            with pytest.raises(NamespaceCollision):
                namespace["foo"] = 1337


def test_undeclared_definition(namespace):
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]


def test_undeclared_definition_across_scopes(namespace):
    with namespace.enter_builtin_scope():
        with namespace.enter_scope():
            namespace["foo"] = 42
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]
