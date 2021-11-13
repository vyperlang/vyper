from typing import Any, List, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
)
from vyper.old_codegen.function_definitions import (
    generate_lll_for_function,
    is_default_func,
    is_initializer,
)
from vyper.old_codegen.global_context import GlobalContext
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import make_setter
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
    ["calldatacopy", 28, 0, 4],
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
        # TODO factor me into helper function
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


def parse_regular_functions(
    o, regular_functions, sigs, external_interfaces, global_ctx, default_function
):
    # check for payable/nonpayable external functions to optimize nonpayable assertions
    func_types = [i._metadata["type"] for i in global_ctx._defs]
    mutabilities = [i.mutability for i in func_types if i.visibility == FunctionVisibility.EXTERNAL]
    has_payable = any(i == StateMutability.PAYABLE for i in mutabilities)
    has_nonpayable = any(i != StateMutability.PAYABLE for i in mutabilities)

    is_default_payable = (
        default_function is not None
        and default_function._metadata["type"].mutability == StateMutability.PAYABLE
    )

    # TODO streamline the nonpayable check logic

    # when a contract has a payable default function and at least one nonpayable
    # external function, we must perform the nonpayable check on every function
    check_per_function = is_default_payable and has_nonpayable

    # generate LLL for regular functions
    payable_funcs = []
    nonpayable_funcs = []
    internal_funcs = []
    add_gas = func_init_lll().gas

    for func_node in regular_functions:
        func_type = func_node._metadata["type"]
        func_lll, frame_start, frame_size = generate_lll_for_function(
            func_node, {**{"self": sigs}, **external_interfaces}, global_ctx, check_per_function
        )

        if func_type.visibility == FunctionVisibility.INTERNAL:
            internal_funcs.append(func_lll)

        elif func_type.mutability == StateMutability.PAYABLE:
            add_gas += 30  # CMC 20210910 why?
            payable_funcs.append(func_lll)

        else:
            add_gas += 30  # CMC 20210910 why?
            nonpayable_funcs.append(func_lll)

        func_lll.total_gas += add_gas

        # update sigs with metadata gathered from compiling the function so that
        # we can handle calls to self
        # TODO we only need to do this for internal functions; external functions
        # cannot be called via `self`
        sig = FunctionSignature.from_definition(func_node, external_interfaces, global_ctx._structs)
        sig.gas = func_lll.total_gas
        sig.frame_start = frame_start
        sig.frame_size = frame_size
        sigs[sig.name] = sig

    # generate LLL for fallback function
    if default_function:
        fallback_lll, _frame_start, _frame_size = generate_lll_for_function(
            default_function,
            {**{"self": sigs}, **external_interfaces},
            global_ctx,
            # include a nonpayble check here if the contract only has a default function
            check_per_function or not regular_functions,
        )
    else:
        fallback_lll = LLLnode.from_list(["revert", 0, 0], typ=None, annotation="Default function")

    if check_per_function:
        external_seq = ["seq"] + payable_funcs + nonpayable_funcs

    else:
        # payable functions are placed prior to nonpayable functions
        # and seperated by a nonpayable assertion
        external_seq = ["seq"]
        if has_payable:
            external_seq += payable_funcs
        if has_nonpayable:
            external_seq.append(["assert", ["iszero", "callvalue"]])
            external_seq += nonpayable_funcs

    # bytecode is organized by: external functions, fallback fn, internal functions
    # this way we save gas and reduce bytecode by not jumping over internal functions
    runtime = [
        "seq",
        func_init_lll(),
        ["with", "_calldata_method_id", ["mload", 0], external_seq],
        ["seq", ["label", "fallback"], fallback_lll],
    ]
    runtime.extend(internal_funcs)

    immutables = [_global for _global in global_ctx._globals.values() if _global.is_immutable]

    # TODO: enable usage of the data section beyond just user defined immutables
    # https://github.com/vyperlang/vyper/pull/2466#discussion_r722816358
    if len(immutables) > 0:
        # find position of the last immutable so we do not overwrite it in memory
        # when we codecopy the runtime code to memory
        immutables = sorted(immutables, key=lambda imm: imm.pos)
        start_pos = immutables[-1].pos + immutables[-1].size * 32
        # create sequence of actions to copy immutables to the end of the runtime code in memory
        data_section = []
        for immutable in immutables:
            # store each immutable at the end of the runtime code
            memory_loc, offset = (
                immutable.pos,
                immutable.data_offset,
            )
            lhs = LLLnode.from_list(
                ["add", start_pos + offset, "_lllsz"], typ=immutable.typ, location="memory"
            )
            rhs = LLLnode.from_list(memory_loc, typ=immutable.typ, location="memory")
            data_section.append(make_setter(lhs, rhs, None))

        data_section_size = sum([immutable.size * 32 for immutable in immutables])
        o.append(
            [
                "with",
                "_lllsz",  # keep size of runtime bytecode in sz var
                ["lll", start_pos, runtime],  # store runtime code at `start_pos`
                # sequence of copying immutables, with final action of returning the runtime code
                ["seq", *data_section, ["return", start_pos, ["add", data_section_size, "_lllsz"]]],
            ]
        )

    else:
        # NOTE: lll macro first argument is the location in memory to store
        # the compiled bytecode
        # https://lll-docs.readthedocs.io/en/latest/lll_reference.html#code-lll
        o.append(["return", 0, ["lll", 0, runtime]])

    return o, runtime


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
    init_function = next((_def for _def in global_ctx._defs if is_initializer(_def)), None)
    # Default function
    default_function = next((i for i in global_ctx._defs if is_default_func(i)), None)

    regular_functions = [
        _def for _def in global_ctx._defs if not is_initializer(_def) and not is_default_func(_def)
    ]

    sigs: dict = {}
    external_interfaces: dict = {}
    # Create the main statement
    o: List[Union[str, LLLnode]] = ["seq"]
    if global_ctx._contracts or global_ctx._interfaces:
        external_interfaces = parse_external_interfaces(external_interfaces, global_ctx)

    # TODO: fix for #2251 is to move this after parse_regular_functions
    if init_function:
        o.append(init_func_init_lll())
        init_func_lll, _frame_start, _frame_size = generate_lll_for_function(
            init_function,
            {**{"self": sigs}, **external_interfaces},
            global_ctx,
            False,
        )
        o.append(init_func_lll)

    if regular_functions or default_function:
        o, runtime = parse_regular_functions(
            o,
            regular_functions,
            sigs,
            external_interfaces,
            global_ctx,
            default_function,
        )
    else:
        runtime = o.copy()

    return LLLnode.from_list(o), LLLnode.from_list(runtime)


# TODO this function is dead code
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
