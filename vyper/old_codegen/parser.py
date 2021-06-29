from typing import Any, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.signatures import sig_utils
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
)
from vyper.old_codegen.function_definitions import (
    is_default_func,
    is_initializer,
    parse_function,
)
from vyper.old_codegen.global_context import GlobalContext
from vyper.old_codegen.lll_node import LLLnode
from vyper.semantics.types.function import FunctionVisibility, StateMutability
from vyper.typing import InterfaceImports
from vyper.utils import LOADED_LIMITS

# TODO remove this check
if not hasattr(vy_ast, "AnnAssign"):
    raise Exception("Requires python 3.6 or higher for annotation support")

# Header code
STORE_CALLDATA: List[Any] = [
    "seq",
    # check that calldatasize is at least 4, otherwise
    # calldataload will load zeros (cf. yellow paper).
    ["if", ["lt", "calldatasize", 4], ["goto", "fallback"]],
    ["mstore", 28, ["calldataload", 0]],
]
# Store limit constants at fixed addresses in memory.
LIMIT_MEMORY_SET: List[Any] = [
    ["mstore", pos, limit_size] for pos, limit_size in LOADED_LIMITS.items()
]


def func_init_lll():
    return LLLnode.from_list(STORE_CALLDATA + LIMIT_MEMORY_SET, typ=None)


def init_func_init_lll():
    return LLLnode.from_list(["seq"] + LIMIT_MEMORY_SET, typ=None)


def parse_external_interfaces(external_interfaces, global_ctx):
    for _interfacename in global_ctx._contracts:
        _interface_defs = global_ctx._contracts[_interfacename]
        _defnames = [_def.name for _def in _interface_defs]
        interface = {}
        if len(set(_defnames)) < len(_interface_defs):
            raise FunctionDeclarationException(
                "Duplicate function name: "
                f"{[name for name in _defnames if _defnames.count(name) > 1][0]}"
            )

        for _def in _interface_defs:
            constant = False
            # test for valid call type keyword.
            if (
                len(_def.body) == 1
                and isinstance(_def.body[0], vy_ast.Expr)
                and isinstance(_def.body[0].value, vy_ast.Name)
                # NOTE: Can't import enums here because of circular import
                and _def.body[0].value.id in ("pure", "view", "nonpayable", "payable")
            ):
                constant = True if _def.body[0].value.id in ("view", "pure") else False
            else:
                raise StructureException("state mutability of call type must be specified", _def)
            # Recognizes already-defined structs
            sig = FunctionSignature.from_definition(
                _def,
                interface_def=True,
                constant_override=constant,
                custom_structs=global_ctx._structs,
            )
            interface[sig.name] = sig
        external_interfaces[_interfacename] = interface

    for interface_name, interface in global_ctx._interfaces.items():
        external_interfaces[interface_name] = {
            sig.name: sig for sig in interface if isinstance(sig, FunctionSignature)
        }

    return external_interfaces


def parse_other_functions(o, otherfuncs, sigs, external_interfaces, global_ctx, default_function):
    # check for payable/nonpayable external functions to optimize nonpayable assertions
    func_types = [i._metadata["type"] for i in global_ctx._defs]
    mutabilities = [i.mutability for i in func_types if i.visibility == FunctionVisibility.EXTERNAL]
    has_payable = next((True for i in mutabilities if i == StateMutability.PAYABLE), False)
    has_nonpayable = next((True for i in mutabilities if i != StateMutability.PAYABLE), False)
    is_default_payable = (
        default_function is not None
        and default_function._metadata["type"].mutability == StateMutability.PAYABLE
    )
    # when a contract has a payable default function and at least one nonpayable
    # external function, we must perform the nonpayable check on every function
    check_per_function = is_default_payable and has_nonpayable

    # generate LLL for regular functions
    payable_func_sub = ["seq"]
    external_func_sub = ["seq"]
    internal_func_sub = ["seq"]
    add_gas = func_init_lll().gas

    for func_node in otherfuncs:
        func_type = func_node._metadata["type"]
        func_lll = parse_function(
            func_node, {**{"self": sigs}, **external_interfaces}, global_ctx, check_per_function
        )
        if func_type.visibility == FunctionVisibility.INTERNAL:
            internal_func_sub.append(func_lll)
        elif func_type.mutability == StateMutability.PAYABLE:
            add_gas += 30
            payable_func_sub.append(func_lll)
        else:
            external_func_sub.append(func_lll)
            add_gas += 30
        func_lll.total_gas += add_gas
        for sig in sig_utils.generate_default_arg_sigs(func_node, external_interfaces, global_ctx):
            sig.gas = func_lll.total_gas
            sigs[sig.sig] = sig

    # generate LLL for fallback function
    if default_function:
        fallback_lll = parse_function(
            default_function,
            {**{"self": sigs}, **external_interfaces},
            global_ctx,
            # include a nonpayble check here if the contract only has a default function
            check_per_function or not otherfuncs,
        )
    else:
        fallback_lll = LLLnode.from_list(["revert", 0, 0], typ=None, annotation="Default function")

    if check_per_function:
        external_seq = ["seq", payable_func_sub, external_func_sub]
    else:
        # payable functions are placed prior to nonpayable functions
        # and seperated by a nonpayable assertion
        external_seq = ["seq"]
        if has_payable:
            external_seq.append(payable_func_sub)
        if has_nonpayable:
            external_seq.extend([["assert", ["iszero", "callvalue"]], external_func_sub])

    # bytecode is organized by: external functions, fallback fn, internal functions
    # this way we save gas and reduce bytecode by not jumping over internal functions
    main_seq = [
        "seq",
        func_init_lll(),
        ["with", "_func_sig", ["mload", 0], external_seq],
        ["seq_unchecked", ["label", "fallback"], fallback_lll],
        internal_func_sub,
    ]

    o.append(["return", 0, ["lll", main_seq, 0]])
    return o, main_seq


# Main python parse tree => LLL method
def parse_tree_to_lll(global_ctx: GlobalContext) -> Tuple[LLLnode, LLLnode]:
    _names_def = [_def.name for _def in global_ctx._defs]
    # Checks for duplicate function names
    if len(set(_names_def)) < len(_names_def):
        raise FunctionDeclarationException(
            "Duplicate function name: "
            f"{[name for name in _names_def if _names_def.count(name) > 1][0]}"
        )
    _names_events = [_event.name for _event in global_ctx._events]
    # Checks for duplicate event names
    if len(set(_names_events)) < len(_names_events):
        raise EventDeclarationException(
            f"""Duplicate event name:
            {[name for name in _names_events if _names_events.count(name) > 1][0]}"""
        )
    # Initialization function
    initfunc = [_def for _def in global_ctx._defs if is_initializer(_def)]
    # Default function
    defaultfunc = next((i for i in global_ctx._defs if is_default_func(i)), None)
    # Regular functions
    otherfuncs = [
        _def for _def in global_ctx._defs if not is_initializer(_def) and not is_default_func(_def)
    ]

    sigs: dict = {}
    external_interfaces: dict = {}
    # Create the main statement
    o = ["seq"]
    if global_ctx._contracts or global_ctx._interfaces:
        external_interfaces = parse_external_interfaces(external_interfaces, global_ctx)
    # If there is an init func...
    if initfunc:
        o.append(init_func_init_lll())
        o.append(
            parse_function(
                initfunc[0], {**{"self": sigs}, **external_interfaces}, global_ctx, False,
            )
        )

    # If there are regular functions...
    if otherfuncs or defaultfunc:
        o, runtime = parse_other_functions(
            o, otherfuncs, sigs, external_interfaces, global_ctx, defaultfunc,
        )
    else:
        runtime = o.copy()

    return LLLnode.from_list(o, typ=None), LLLnode.from_list(runtime, typ=None)


def parse_to_lll(
    source_code: str, runtime_only: bool = False, interface_codes: Optional[InterfaceImports] = None
) -> LLLnode:
    vyper_module = vy_ast.parse_to_ast(source_code)
    global_ctx = GlobalContext.get_global_context(vyper_module, interface_codes=interface_codes)
    lll_nodes, lll_runtime = parse_tree_to_lll(global_ctx)

    if runtime_only:
        return lll_runtime
    else:
        return lll_nodes
