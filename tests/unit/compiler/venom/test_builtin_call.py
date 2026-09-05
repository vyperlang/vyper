import pytest

from vyper.builtins._signatures import ContextDefault
from vyper.builtins.functions import get_builtin_functions
from vyper.codegen.ir_node import IRnode
from vyper.codegen_venom.builtins import BUILTIN_HANDLERS, _merge_handlers
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TYPE_T, VyperType


def test_handler_registry_covers_runtime_builtins():
    semantic_ids = {func_t._id for func_t in get_builtin_functions().values()}
    handler_ids = set(BUILTIN_HANDLERS)
    assert handler_ids <= semantic_ids
    assert semantic_ids - handler_ids == {
        "method_id",
        "sqrt",
        "isqrt",  # removed builtins; semantic errors
    }


def test_builtin_runtime_defaults_are_backend_neutral():
    for func_t in get_builtin_functions().values():
        for name, settings in func_t._kwargs.items():
            if TYPE_T.any().compare_type(settings.typ):
                assert isinstance(settings.default, VyperType), name
            elif settings.require_literal:
                assert not isinstance(settings.default, IRnode), name
            else:
                assert settings.default is ContextDefault.GAS or type(settings.default) is int, name


def test_registry_merge_rejects_duplicates():
    def handler(call):
        return None

    with pytest.raises(CompilerPanic, match="duplicate Venom builtin handlers"):
        _merge_handlers({"example": handler}, {"example": handler})
