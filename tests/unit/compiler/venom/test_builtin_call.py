from types import SimpleNamespace

import pytest

from vyper.builtins._signatures import ContextDefault
from vyper.builtins.functions import get_builtin_functions
from vyper.codegen.ir_node import IRnode
from vyper.codegen_venom.builtins import BUILTIN_HANDLERS, _merge_handlers, _validate_handler_result
from vyper.codegen_venom.builtins._call import BuiltinLowerer
from vyper.codegen_venom.call_args import (
    FOLDED,
    VALUE_LIST,
    DataViewKind,
    data_source,
    length_source,
)
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TYPE_T, BoolT, VyperType
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral


def _semantic_builtins_by_id():
    return {func_t._id: func_t for func_t in get_builtin_functions().values()}


def test_handler_registry_has_no_dead_or_missing_runtime_entries():
    semantic_ids = set(_semantic_builtins_by_id())
    handler_ids = set(BUILTIN_HANDLERS)

    assert handler_ids <= semantic_ids
    assert semantic_ids - handler_ids == {
        "method_id",  # mandatory fold
        "min_value",  # mandatory fold
        "max_value",  # mandatory fold
        "epsilon",  # mandatory fold
        "sqrt",  # removed builtin; semantic error
        "isqrt",  # removed builtin; semantic error
    }


def test_exceptional_argument_policy_map_is_exhaustive():
    expected = {
        "len": {"b": length_source(DataViewKind.CALLDATA)},
        "slice": {
            "b": data_source(
                DataViewKind.CALLDATA, DataViewKind.SELF_CODE, DataViewKind.EXTERNAL_CODE
            )
        },
        "raw_call": {
            "data": data_source(
                DataViewKind.CALLDATA, unsupported_message="unsupported raw_call payload"
            )
        },
        "raw_log": {"topics": VALUE_LIST},
        "as_wei_value": {"unit": FOLDED},
    }
    actual = {
        builtin_id: dict(lowerer.arg_policies)
        for builtin_id, lowerer in BUILTIN_HANDLERS.items()
        if lowerer.arg_policies
    }

    assert actual == expected


def test_policy_names_come_from_semantic_positional_signature():
    semantic = _semantic_builtins_by_id()
    for builtin_id, lowerer in BUILTIN_HANDLERS.items():
        declared_names = {name for name, _ in semantic[builtin_id]._inputs}
        assert set(lowerer.arg_policies) <= declared_names


def test_builtin_runtime_defaults_are_backend_neutral():
    for func_t in _semantic_builtins_by_id().values():
        for name, settings in func_t._kwargs.items():
            if TYPE_T.any().compare_type(settings.typ):
                assert isinstance(settings.default, VyperType), name
            elif settings.require_literal:
                assert not isinstance(settings.default, IRnode), name
            else:
                assert settings.default is ContextDefault.GAS or type(settings.default) is int, name


def test_registry_merge_rejects_duplicates():
    lowerer = BuiltinLowerer(lambda call: None)
    with pytest.raises(CompilerPanic, match="duplicate Venom builtin handlers: example"):
        _merge_handlers({"example": lowerer}, {"example": lowerer})


def test_handler_result_must_match_semantic_return_type():
    call = SimpleNamespace(func_t=SimpleNamespace(_id="example"), return_type=BoolT())
    result = VyperValue.from_stack_op(IRLiteral(0), UINT256_T)

    with pytest.raises(CompilerPanic, match="returned uint256, expected bool"):
        _validate_handler_result(call, result)
