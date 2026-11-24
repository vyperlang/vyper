import pytest

from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.namespace import Namespace, get_namespace
from vyper.semantics.types import PRIMITIVE_TYPES
from vyper.semantics.types.shortcuts import INT128_T, UINT256_T

FOO = VarInfo(UINT256_T)
BAR = VarInfo(INT128_T)


def test_get_namespace():
    ns = get_namespace()
    ns2 = get_namespace()
    assert ns == ns2


def test_builtin_context_manager(namespace):
    namespace["foo"] = FOO
    with namespace.enter_scope():
        namespace["bar"] = BAR

    assert namespace["foo"] == FOO
    assert "bar" not in namespace


def test_copy(namespace):
    with namespace.enter_scope():
        namespace["foo"] = FOO
        ns2 = namespace.copy()

        assert isinstance(ns2, Namespace)
        # note: `Namespace.__eq__` is identity, so compare as plain dicts
        assert dict(ns2) == dict(namespace)
        assert ns2._scopes == namespace._scopes

        # mutating the copy does not touch the original
        ns2["bar"] = BAR
        assert "bar" not in namespace
        assert "bar" not in namespace._scopes[-1]

        # the copy still validates
        with pytest.raises(NamespaceCollision):
            ns2["foo"] = BAR


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
        namespace["foo"] = FOO
        with namespace.enter_scope():
            namespace["bar"] = BAR

        assert namespace["foo"] == FOO
        assert "bar" not in namespace

    assert "foo" not in namespace


def test_incorrect_context_invocation(namespace):
    with pytest.raises(CompilerPanic):
        with namespace:
            pass


def test_namespace_collision(namespace):
    with namespace.enter_scope():
        namespace["foo"] = FOO
        with pytest.raises(NamespaceCollision):
            namespace["foo"] = BAR


def test_namespace_collision_across_scopes(namespace):
    with namespace.enter_scope():
        namespace["foo"] = FOO
        with namespace.enter_scope():
            with pytest.raises(NamespaceCollision):
                namespace["foo"] = BAR


def test_undeclared_definition(namespace):
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]


def test_undeclared_definition_across_scopes(namespace):
    with namespace.enter_scope():
        with namespace.enter_scope():
            namespace["foo"] = FOO
    with pytest.raises(UndeclaredDefinition):
        namespace["foo"]
