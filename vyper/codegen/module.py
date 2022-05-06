# a contract.vy -- all functions and constructor

from typing import Dict, List, Optional, Tuple, Union, Any

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignature, FunctionSignatures
from vyper.codegen.core import shr
from vyper.codegen.function_definitions import generate_ir_for_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.exceptions import CompilerPanic, FunctionDeclarationException, StructureException
from vyper.semantics.types.function import StateMutability


def _topsort_helper(functions, lookup):
    #  single pass to get a global topological sort of functions (so that each
    # function comes after each of its callees). may have duplicates, which get
    # filtered out in _topsort()

    ret = []
    for f in functions:
        # called_functions is a list of ContractFunctions, need to map
        # back to FunctionDefs.
        callees = [lookup[t.name] for t in f._metadata["type"].called_functions]
        ret.extend(_topsort_helper(callees, lookup))
        ret.append(f)

    return ret


def _topsort(functions):
    lookup = {f.name: f for f in functions}
    # strip duplicates
    return list(dict.fromkeys(_topsort_helper(functions, lookup)))


# TODO this should really live in GlobalContext
def parse_external_interfaces(external_interfaces, global_ctx):
    for _interfacename in global_ctx._contracts:
        _interface_defs = global_ctx._contracts[_interfacename]
        _defnames = [_def.name for _def in _interface_defs]
        interface = {}
        # CMC 2022-05-06: TODO this seems like dead code
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


# codegen for all external functions + callvalue/calldata checks + method selector routines
def _runtime_ir(external_functions, all_sigs, global_ctx, default_function):
    has_payable = any(
        f._metadata["type"].mutability == StateMutability.PAYABLE for f in external_functions
    )
    has_nonpayable = any(
        f._metadata["type"].mutability != StateMutability.PAYABLE for f in external_functions
    )

    is_default_payable = (
        default_function is not None
        and default_function._metadata["type"].mutability == StateMutability.PAYABLE
    )

    # when a contract has a payable default function and at least one nonpayable
    # external function, we must perform the nonpayable check on every function
    check_per_function = is_default_payable and has_nonpayable

    # generate IR for regular functions
    payable_funcs = []
    nonpayable_funcs = []

    for func_ast in external_functions:
        func_type = func_ast._metadata["type"]
        func_ir = generate_ir_for_function(func_ast, all_sigs, global_ctx, check_per_function)

        if func_type.mutability == StateMutability.PAYABLE:
            payable_funcs.append(func_ir)
        else:
            nonpayable_funcs.append(func_ir)

    # generate IR for fallback function
    # include a nonpayable check here if the contract only has a default function
    nonpayable_check = check_per_function or not external_functions

    if default_function:
        fallback_ir = generate_ir_for_function(
            default_function, all_sigs, global_ctx, nonpayable_check
        )
    else:
        fallback_ir = IRnode.from_list(["revert", 0, 0], annotation="Default function")

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

    # bytecode is organized by: external functions, fallback fn, internal_functions
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

    return runtime


# Main python parse tree => IR method
def generate_ir_for_module(global_ctx: GlobalContext) -> Tuple[IRnode, IRnode, FunctionSignatures]:
    # order functions so that each function comes after all of its callees
    function_defs = _topsort(global_ctx._function_defs)

    # FunctionSignatures for all interfaces defined in this module
    all_sigs: Dict[str, Dict[str, FunctionSignature]] = {}
    if global_ctx._contracts or global_ctx._interfaces:
        all_sigs = parse_external_interfaces(all_sigs, global_ctx)

    init_function: Optional[vy_ast.FunctionDef] = None
    default_function: Optional[vy_ast.FunctionDef] = None
    external_functions: List[vy_ast.FunctionDef] = []
    sigs: Dict[str, FunctionSignature] = {}

    # generate all signatures
    # TODO really this should live in GlobalContext
    for f in function_defs:
        sig = FunctionSignature.from_definition(f, all_sigs, global_ctx._structs)
        # add it to the global namespace.
        sigs[sig.name] = sig
        # a little hacky, eventually FunctionSignature should be
        # merged with ContractFunction
        f._metadata["signature"] = sig

    assert "self" not in all_sigs
    all_sigs["self"] = sigs

    # generate IR for internal functions
    # create a map of the functions since they might live in both
    # runtime and deploy code (if init function calls them)
    internal_functions: Dict[str, IRnode] = {}

    for f in function_defs:
        if not f._metadata["type"].is_internal:
            continue

        # note: check_nonpayable is N/A for internal functions
        ir = generate_ir_for_function(f, all_sigs, global_ctx, check_nonpayable=False)
        internal_functions[f.name] = ir

    for f in function_defs:
        sig = f._metadata["signature"]
        if not f._metadata["type"].is_external:
            continue

        if sig.is_regular_function:
            external_functions.append(f)

        elif sig.is_init_func:
            init_function = f

        elif sig.is_default_func:
            default_function = f

        else:  # pragma: nocover
            raise CompilerPanic("unreachable")

    if external_functions or default_function:
        runtime = _runtime_ir(external_functions, all_sigs, global_ctx, default_function)
        # TODO: prune unreachable functions
        runtime.extend(internal_functions.values())
    else:
        # for some reason, somebody may want to deploy a contract with no
        # external functions, or more likely, a "pure data" contract which
        # contains immutables
        runtime = ["seq"]

    deploy_code: List[Any] = ["seq"]
    immutables_len = global_ctx.immutable_section_bytes
    if init_function:
        init_func_ir = generate_ir_for_function(init_function, all_sigs, global_ctx, False)
        deploy_code.append(init_func_ir)

        # pass the amount of memory allocated for the init function
        # so that deployment does not clobber while preparing immutables
        # note: (deploy mem_ofst, code, extra_padding)
        init_mem_used = init_function._metadata["signature"].frame_info.mem_used
        deploy_code.append(["deploy", init_mem_used, runtime, immutables_len])

        # internal functions come after everything else
        for f in init_function._metadata["type"].called_functions:
            deploy_code.append(internal_functions[f.name])

    else:
        if immutables_len != 0:
            raise CompilerPanic("unreachable")
        deploy_code.append(["deploy", 0, runtime, 0])

    return IRnode.from_list(deploy_code), IRnode.from_list(runtime), sigs
