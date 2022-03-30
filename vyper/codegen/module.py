# a contract.vy -- all functions and constructor

from typing import List, Tuple, Union

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignature, FunctionSignatures
from vyper.codegen.core import shr
from vyper.codegen.function_definitions import (
    generate_ir_for_function,
    is_default_func,
    is_initializer,
)
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
)
from vyper.semantics.types.function import FunctionVisibility, StateMutability

# TODO remove this check
if not hasattr(vy_ast, "AnnAssign"):
    raise Exception("Requires python 3.6 or higher for annotation support")


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
                sigs=global_ctx.interface_names,
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
    regular_functions, sigs, external_interfaces, global_ctx, default_function, init_function
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

    # generate IR for regular functions
    payable_funcs = []
    nonpayable_funcs = []
    internal_funcs = []
    add_gas = 0

    for func_node in regular_functions:
        func_type = func_node._metadata["type"]
        func_ir, frame_start, frame_size = generate_ir_for_function(
            func_node, {**{"self": sigs}, **external_interfaces}, global_ctx, check_per_function
        )

        if func_type.visibility == FunctionVisibility.INTERNAL:
            internal_funcs.append(func_ir)

        elif func_type.mutability == StateMutability.PAYABLE:
            add_gas += 30  # CMC 20210910 why?
            payable_funcs.append(func_ir)

        else:
            add_gas += 30  # CMC 20210910 why?
            nonpayable_funcs.append(func_ir)

        func_ir.total_gas += add_gas

        # update sigs with metadata gathered from compiling the function so that
        # we can handle calls to self
        # TODO we only need to do this for internal functions; external functions
        # cannot be called via `self`
        sig = FunctionSignature.from_definition(func_node, external_interfaces, global_ctx._structs)
        sig.gas = func_ir.total_gas
        sig.frame_start = frame_start
        sig.frame_size = frame_size
        sigs[sig.name] = sig

    # generate IR for fallback function
    if default_function:
        fallback_ir, _frame_start, _frame_size = generate_ir_for_function(
            default_function,
            {**{"self": sigs}, **external_interfaces},
            global_ctx,
            # include a nonpayble check here if the contract only has a default function
            check_per_function or not regular_functions,
        )
    else:
        fallback_ir = IRnode.from_list(["revert", 0, 0], typ=None, annotation="Default function")

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

    # ensure the external jumptable section gets closed out
    # (for basic block hygiene and also for zksync interpreter)
    # NOTE: this jump gets optimized out in assembly since the
    # fallback label is the immediate next instruction,
    close_selector_section = ["goto", "fallback"]

    # bytecode is organized by: external functions, fallback fn, internal functions
    # this way we save gas and reduce bytecode by not jumping over internal functions
    runtime = [
        "seq",
        # check that calldatasize is at least 4, otherwise
        # calldataload will load zeros (cf. yellow paper).
        ["if", ["lt", "calldatasize", 4], ["goto", "fallback"]],
        ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), external_seq],
        close_selector_section,
        ["label", "fallback", ["var_list"], fallback_ir],
    ]
    runtime.extend(internal_funcs)

    return runtime


# Main python parse tree => IR method
def parse_tree_to_ir(global_ctx: GlobalContext) -> Tuple[IRnode, IRnode, FunctionSignatures]:
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
    o: List[Union[str, IRnode]] = ["seq"]
    if global_ctx._contracts or global_ctx._interfaces:
        external_interfaces = parse_external_interfaces(external_interfaces, global_ctx)

    init_func_ir = None
    if init_function:
        init_func_ir, _frame_start, init_frame_size = generate_ir_for_function(
            init_function,
            {**{"self": sigs}, **external_interfaces},
            global_ctx,
            False,
        )
        o.append(init_func_ir)

    if regular_functions or default_function:
        runtime = parse_regular_functions(
            regular_functions,
            sigs,
            external_interfaces,
            global_ctx,
            default_function,
            init_func_ir,
        )
    else:
        # for some reason, somebody may want to deploy a contract with no code,
        # or more likely, a "pure data" contract which contains immutables
        runtime = IRnode.from_list(["seq"])

    immutables_len = global_ctx.immutable_section_bytes

    if init_function:
        memsize = init_func_ir.context.memory_allocator.size_of_mem  # type: ignore
    else:
        memsize = 0

    # note: (deploy mem_ofst, code, extra_padding)
    o.append(["deploy", memsize, runtime, immutables_len])  # type: ignore

    return IRnode.from_list(o), IRnode.from_list(runtime), sigs
