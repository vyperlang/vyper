from typing import Any, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
)
from vyper.parser.function_definitions import (
    is_default_func,
    is_initializer,
    parse_function,
)
from vyper.parser.global_context import GlobalContext
from vyper.parser.lll_node import LLLnode
from vyper.signatures import sig_utils
from vyper.signatures.event_signature import EventSignature
from vyper.signatures.function_signature import FunctionSignature
from vyper.signatures.interface import check_valid_contract_interface
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


def parse_events(sigs, global_ctx):
    for event in global_ctx._events:
        sigs[event.name] = EventSignature.from_declaration(event, global_ctx)
    return sigs


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


def parse_other_functions(
    o,
    otherfuncs,
    sigs,
    external_interfaces,
    origcode,
    global_ctx,
    default_function,
    is_contract_payable,
):
    sub = ["seq", func_init_lll()]
    add_gas = func_init_lll().gas

    for _def in otherfuncs:
        sub.append(
            parse_function(
                _def,
                {**{"self": sigs}, **external_interfaces},
                origcode,
                global_ctx,
                is_contract_payable,
            )
        )
        sub[-1].total_gas += add_gas
        add_gas += 30
        for sig in sig_utils.generate_default_arg_sigs(_def, external_interfaces, global_ctx):
            sig.gas = sub[-1].total_gas
            sigs[sig.sig] = sig

    # Add fallback function
    if default_function:
        default_func = parse_function(
            default_function[0],
            {**{"self": sigs}, **external_interfaces},
            origcode,
            global_ctx,
            is_contract_payable,
        )
        fallback = default_func
    else:
        fallback = LLLnode.from_list(["revert", 0, 0], typ=None, annotation="Default function")
    sub.append(["seq_unchecked", ["label", "fallback"], fallback])
    o.append(["return", 0, ["lll", sub, 0]])
    return o, sub


# Main python parse tree => LLL method
def parse_tree_to_lll(source_code: str, global_ctx: GlobalContext) -> Tuple[LLLnode, LLLnode]:
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
    defaultfunc = [_def for _def in global_ctx._defs if is_default_func(_def)]
    # Regular functions
    otherfuncs = [
        _def for _def in global_ctx._defs if not is_initializer(_def) and not is_default_func(_def)
    ]

    # check if any functions in the contract are payable - if not, we do a single
    # ASSERT CALLVALUE ISZERO at the start of the bytecode rather than at the start
    # of each function
    is_contract_payable = next(
        (
            True
            for i in global_ctx._defs
            if FunctionSignature.from_definition(i, custom_structs=global_ctx._structs).mutability
            == "payable"
        ),
        False,
    )

    sigs: dict = {}
    external_interfaces: dict = {}
    # Create the main statement
    o = ["seq"]
    if global_ctx._events:
        sigs = parse_events(sigs, global_ctx)
    if global_ctx._contracts or global_ctx._interfaces:
        external_interfaces = parse_external_interfaces(external_interfaces, global_ctx)
    # If there is an init func...
    if initfunc:
        o.append(init_func_init_lll())
        o.append(
            parse_function(
                initfunc[0],
                {**{"self": sigs}, **external_interfaces},
                source_code,
                global_ctx,
                False,
            )
        )

    # If there are regular functions...
    if otherfuncs or defaultfunc:
        o, runtime = parse_other_functions(
            o,
            otherfuncs,
            sigs,
            external_interfaces,
            source_code,
            global_ctx,
            defaultfunc,
            is_contract_payable,
        )
    else:
        runtime = o.copy()

    if not is_contract_payable:
        # if no functions in the contract are payable, assert that callvalue is
        # zero at the beginning of the bytecode
        runtime.insert(1, ["assert", ["iszero", "callvalue"]])

    # Check if interface of contract is correct.
    check_valid_contract_interface(global_ctx, sigs)

    return LLLnode.from_list(o, typ=None), LLLnode.from_list(runtime, typ=None)


def parse_to_lll(
    source_code: str, runtime_only: bool = False, interface_codes: Optional[InterfaceImports] = None
) -> LLLnode:
    vyper_module = vy_ast.parse_to_ast(source_code)
    global_ctx = GlobalContext.get_global_context(vyper_module, interface_codes=interface_codes)
    lll_nodes, lll_runtime = parse_tree_to_lll(source_code, global_ctx)

    if runtime_only:
        return lll_runtime
    else:
        return lll_nodes
