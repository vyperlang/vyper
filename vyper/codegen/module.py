# a contract.vy -- all functions and constructor

from typing import Any, List, Optional

from vyper import ast as vy_ast
from vyper.codegen.core import shr
from vyper.codegen.function_definitions import generate_ir_for_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.exceptions import CompilerPanic


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


def _is_constructor(func_ast):
    return func_ast._metadata["type"].is_constructor


def _is_fallback(func_ast):
    return func_ast._metadata["type"].is_fallback


def _is_internal(func_ast):
    return func_ast._metadata["type"].is_internal


def _is_payable(func_ast):
    return func_ast._metadata["type"].is_payable


# codegen for all runtime functions + callvalue/calldata checks + method selector routines
def _runtime_ir(runtime_functions, global_ctx):
    # categorize the runtime functions because we will organize the runtime
    # code into the following sections:
    # payable functions, nonpayable functions, fallback function, internal_functions
    internal_functions = [f for f in runtime_functions if _is_internal(f)]

    external_functions = [f for f in runtime_functions if not _is_internal(f)]
    default_function = next((f for f in external_functions if _is_fallback(f)), None)

    # functions that need to go exposed in the selector section
    regular_functions = [f for f in external_functions if not _is_fallback(f)]
    payables = [f for f in regular_functions if _is_payable(f)]
    nonpayables = [f for f in regular_functions if not _is_payable(f)]

    # create a map of the IR functions since they might live in both
    # runtime and deploy code (if init function calls them)
    internal_functions_ir: list[IRnode] = []

    for func_ast in internal_functions:
        func_ir = generate_ir_for_function(func_ast, global_ctx, False)
        internal_functions_ir.append(func_ir)

    # for some reason, somebody may want to deploy a contract with no
    # external functions, or more likely, a "pure data" contract which
    # contains immutables
    if len(external_functions) == 0:
        # TODO: prune internal functions in this case? dead code eliminator
        # might not eliminate them, since internal function jumpdest is at the
        # first instruction in the contract.
        runtime = ["seq"] + internal_functions_ir
        return runtime

    # note: if the user does not provide one, the default fallback function
    # reverts anyway. so it does not hurt to batch the payable check.
    default_is_nonpayable = default_function is None or not _is_payable(default_function)

    # when a contract has a nonpayable default function,
    # we can do a single check for all nonpayable functions
    batch_payable_check = len(nonpayables) > 0 and default_is_nonpayable
    skip_nonpayable_check = batch_payable_check

    selector_section = ["seq"]

    for func_ast in payables:
        func_ir = generate_ir_for_function(func_ast, global_ctx, False)
        selector_section.append(func_ir)

    if batch_payable_check:
        nonpayable_check = IRnode.from_list(
            ["assert", ["iszero", "callvalue"]], error_msg="nonpayable check"
        )
        selector_section.append(nonpayable_check)

    for func_ast in nonpayables:
        func_ir = generate_ir_for_function(func_ast, global_ctx, skip_nonpayable_check)
        selector_section.append(func_ir)

    if default_function:
        fallback_ir = generate_ir_for_function(
            default_function, global_ctx, skip_nonpayable_check=False
        )
    else:
        fallback_ir = IRnode.from_list(
            ["revert", 0, 0], annotation="Default function", error_msg="fallback function"
        )

    # ensure the external jumptable section gets closed out
    # (for basic block hygiene and also for zksync interpreter)
    # NOTE: this jump gets optimized out in assembly since the
    # fallback label is the immediate next instruction,
    close_selector_section = ["goto", "fallback"]

    global_calldatasize_check = ["if", ["lt", "calldatasize", 4], ["goto", "fallback"]]

    runtime = [
        "seq",
        global_calldatasize_check,
        ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), selector_section],
        close_selector_section,
        ["label", "fallback", ["var_list"], fallback_ir],
    ]

    runtime.extend(internal_functions_ir)

    return runtime


# take a GlobalContext, and generate the runtime and deploy IR
def generate_ir_for_module(global_ctx: GlobalContext) -> tuple[IRnode, IRnode]:
    # order functions so that each function comes after all of its callees
    function_defs = _topsort(global_ctx.functions)

    init_function: Optional[vy_ast.FunctionDef] = None

    runtime_functions = [f for f in function_defs if not _is_constructor(f)]
    init_function = next((f for f in function_defs if _is_constructor(f)), None)

    runtime = _runtime_ir(runtime_functions, global_ctx)

    deploy_code: List[Any] = ["seq"]
    immutables_len = global_ctx.immutable_section_bytes
    if init_function:
        # TODO might be cleaner to separate this into an _init_ir helper func
        init_func_ir = generate_ir_for_function(
            init_function, global_ctx, skip_nonpayable_check=False, is_ctor_context=True
        )

        # pass the amount of memory allocated for the init function
        # so that deployment does not clobber while preparing immutables
        # note: (deploy mem_ofst, code, extra_padding)
        init_mem_used = init_function._metadata["type"]._ir_info.frame_info.mem_used

        # force msize to be initialized past the end of immutables section
        # so that builtins which use `msize` for "dynamic" memory
        # allocation do not clobber uninitialized immutables.
        # cf. GH issue 3101.
        # note mload/iload X touches bytes from X to X+32, and msize rounds up
        # to the nearest 32, so `iload`ing `immutables_len - 32` guarantees
        # that `msize` will refer to a memory location of at least
        # `<immutables_start> + immutables_len` (where <immutables_start> ==
        # `_mem_deploy_end` as defined in the assembler).
        # note:
        #   mload 32 => msize == 64
        #   mload 33 => msize == 96
        # assumption in general: (mload X) => msize == ceil32(X + 32)
        # see py-evm extend_memory: after_size = ceil32(start_position + size)
        if immutables_len > 0:
            deploy_code.append(["iload", max(0, immutables_len - 32)])

        deploy_code.append(init_func_ir)

        deploy_code.append(["deploy", init_mem_used, runtime, immutables_len])

        # internal functions come after everything else
        internal_functions = [f for f in runtime_functions if _is_internal(f)]
        for f in internal_functions:
            init_func_t = init_function._metadata["type"]
            if f.name not in init_func_t.recursive_calls:
                # unreachable
                continue

            func_ir = generate_ir_for_function(
                f, global_ctx, skip_nonpayable_check=False, is_ctor_context=True
            )
            deploy_code.append(func_ir)

    else:
        if immutables_len != 0:
            raise CompilerPanic("unreachable")
        deploy_code.append(["deploy", 0, runtime, 0])

    return IRnode.from_list(deploy_code), IRnode.from_list(runtime)
