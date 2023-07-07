# a contract.vy -- all functions and constructor

from typing import Any, List

from vyper.codegen.core import shr
from vyper.codegen.function_definitions import generate_ir_for_function, FuncIR
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen import jumptable
from vyper.exceptions import CompilerPanic
from vyper.utils import method_id_int


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


def _annotated_method_id(abi_sig):
    method_id = method_id_int(abi_sig)
    annotation = f"{hex(method_id)}: {abi_sig}"
    return IRnode(method_id, annotation=annotation)


def _ir_for_external_function(func_ast, *args, **kwargs):
    # adapt whatever generate_ir_for_function gives us into an IR node
    ret = ["seq"]
    func_t = func_ast._metadata["type"]
    func_ir = generate_ir_for_function(func_ast, *args, **kwargs)

    if func_t.is_fallback or func_t.is_constructor:
        assert len(func_ir.entry_points) == 1
        # add a goto to make the function entry look like other functions
        # (for zksync interpreter)
        ret.append(["goto", func_t._ir_info.external_function_base_entry_label])
        ret.append(func_ir.common_ir)

    else:
        for sig, ir_node in func_ir.entry_points.items():
            method_id = _annotated_method_id(sig)
            ret.append(["if", ["eq", "_calldata_method_id", method_id], ir_node])
        # stick function common body into final entry point to save a jump
        # TODO: this would not really be necessary if we had block reordering
        # in optimizer.
        ir_node.append(func_ir.common_ir)

    return IRnode.from_list(ret)


def _ir_for_internal_function(func_ast, *args, **kwargs):
    return generate_ir_for_function(func_ast, *args, **kwargs).func_ir


# codegen for all runtime functions + callvalue/calldata checks,
# with O(1) jumptable for selector table.
# uses two level strategy: uses `method_id % n_buckets` to descend
# into a bucket (of about 8-10 items), and then uses perfect hash
# to select the final function.
# costs about 212 gas for typical function and 8 bytes of code.
def _selector_section_dense(runtime_functions, global_ctx):
    # categorize the runtime functions because we will organize the runtime
    # code into the following sections:
    # payable functions, nonpayable functions, fallback function, internal_functions
    internal_functions = [f for f in runtime_functions if _is_internal(f)]

    external_functions = [f for f in runtime_functions if not _is_internal(f)]
    default_function = next((f for f in external_functions if _is_fallback(f)), None)

    internal_functions_ir: list[IRnode] = []

    # compile internal functions first so we have the function info
    for func_ast in internal_functions:
        func_ir = _ir_for_internal_function(func_ast, global_ctx, False)
        internal_functions_ir.append(IRnode.from_list(func_ir))

    function_irs = []
    entry_points = {}  # map from ABI sigs to ir code

    for code in external_functions:
        func_ir = generate_ir_for_function(code, global_ctx, skip_nonpayable_check=True)
        for abi_sig, entry_point in func_ir.entry_points.items():
            assert abi_sig not in entry_points
            entry_points[abi_sig] = entry_point
        # stick function common body into final entry point to save a jump
        entry_point.ir_node.append(func_ir.common_ir)

    for entry_point in entry_points.values():
        function_irs.append(IRnode.from_list(entry_point.ir_node))

    function_irs.extend(internal_functions_ir)

    jumptable_info = jumptable.generate_jumptable_info(entry_points.keys())
    n_buckets = len(jumptable_info)

    # 2 bytes for bucket magic, 2 bytes for bucket location
    SZ_BUCKET_HEADER = 4

    selector_section = ["seq"]

    bucket_id = ["mod", "_calldata_method_id", n_buckets]
    bucket_hdr_location = [
        "add",
        ["symbol", "BUCKET_HEADERS"],
        ["mul", bucket_id, SZ_BUCKET_HEADER],
    ]
    # get bucket header
    dst = 32 - SZ_BUCKET_HEADER
    assert dst >= 0

    # memory is PROBABLY 0, but just be paranoid.
    selector_section.append(["mstore", 0, 0])
    selector_section.append(["codecopy", dst, bucket_hdr_location, SZ_BUCKET_HEADER])

    # figure out the minimum number of bytes we can use to encode
    # min_calldatasize in function info
    largest_mincalldatasize = max(f.min_calldatasize for f in entry_points.values())
    variable_bytes_needed = (largest_mincalldatasize.bit_length() + 7) // 8

    func_info_size = 4 + 2 + variable_bytes_needed
    # grab function info. 4 bytes for method id, 2 bytes for label,
    # 1-3 bytes (packed) for: expected calldatasize, is payable bit
    # TODO: might be able to improve codesize if we use variable # of bytes
    # per bucket

    # TODO: inline all bucket info when there is only one bucket, we know 
    # all the data at compile-time.
    hdr_info = IRnode.from_list(["mload", 0])
    with hdr_info.cache_when_complex("hdr_info") as (b1, hdr_info):
        bucket_location = ["and", 0xFFFF, hdr_info]
        bucket_magic = shr(16, hdr_info)
        # ((method_id * bucket_magic) >> BITS_MAGIC) % bucket_size
        func_id = [
            "mod",
            shr(jumptable.BITS_MAGIC, ["mul", bucket_magic, "_calldata_method_id"]),
            n_buckets,
        ]
        func_info_location = ["add", bucket_location, ["mul", func_id, func_info_size]]
        dst = 32 - func_info_size
        assert func_info_size >= SZ_BUCKET_HEADER  # otherwise mload will have dirty bytes
        assert dst >= 0
        selector_section.append(b1.resolve(["codecopy", dst, func_info_location, func_info_size]))

    # TODO: add a special case when there is only one function?
    func_info = IRnode.from_list(["mload", 0])
    with func_info.cache_when_complex("func_info") as (b1, func_info):
        x = ["seq"]

        # expected calldatasize always satisfies (x - 4) % 32 == 0
        # the lower 5 bits are always 0b00100, so we can use those
        # bits for other purposes.
        is_nonpayable = ["and", 1, func_info]
        expected_calldatasize = ["and", 0xFFFFFE, func_info]

        # method id <4 bytes> | label <2 bytes> | func info <1-3 bytes>

        label_bits_ofst = variable_bytes_needed * 8
        function_label = ["and", 0xFFFF, shr(label_bits_ofst, func_info)]
        method_id_bits_ofst = (variable_bytes_needed + 3) * 8
        function_method_id = shr(method_id_bits_ofst, func_info)

        # check method id is right, if not then fallback.
        calldatasize_valid = ["gt", "calldatasize", 3]
        method_id_correct = ["eq", function_method_id, "_calldata_method_id"]
        should_fallback = ["iszero", ["mul", calldatasize_valid, method_id_correct]]
        x.append(["if", should_fallback, ["goto", "fallback"]])

        # assert callvalue == 0 if nonpayable
        payable_check = ["mul", is_nonpayable, "callvalue"]
        # assert calldatasize correct
        calldatasize_check = ["ge", "calldatasize", expected_calldatasize]
        passed_entry_conditions = ["mul", payable_check, calldatasize_check]
        x.append(["assert", passed_entry_conditions])
        x.append(["goto", function_label])
        selector_section.append(b1.resolve(x))

    if default_function:
        fallback_ir = _ir_for_external_function(
            default_function, global_ctx, skip_nonpayable_check=False
        )
    else:
        fallback_ir = IRnode.from_list(
            ["revert", 0, 0], annotation="Default function", error_msg="fallback function"
        )

    runtime = [
        "seq",
        ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), selector_section],
        ["label", "fallback", ["var_list"], fallback_ir],
    ]

    runtime.extend(function_irs)

    return runtime


# codegen for all runtime functions + callvalue/calldata checks,
# with O(1) jumptable for selector table.
# uses two level strategy: uses `method_id % n_methods` to calculate
# a bucket, and then descends into linear search from there.
# costs about 126 gas for typical (nonpayable, >0 args, avg bucket size 1.5)
# function and 24 bytes of code.
def _selector_table_sparse(external_functions, global_ctx):
    # categorize the runtime functions because we will organize the runtime
    # code into the following sections:
    # payable functions, nonpayable functions, fallback function, internal_functions
    default_function = next((f for f in external_functions if _is_fallback(f)), None)

    function_irs = []
    entry_points = {}  # map from ABI sigs to ir code

    for code in external_functions:
        func_ir = generate_ir_for_function(code, global_ctx, skip_nonpayable_check=True)
        for abi_sig, entry_point in func_ir.entry_points.items():
            assert abi_sig not in entry_points
            entry_points[abi_sig] = entry_point

        # stick function common body into final entry point to save a jump
        entry_point.ir_node.append(func_ir.common_ir)

    for entry_point in entry_points.values():
        function_irs.append(IRnode.from_list(entry_point.ir_node))

    n_buckets = len(external_functions)

    # 2 bytes for bucket location
    SZ_BUCKET_HEADER = 2

    selector_section = ["seq"]

    selector_section.append(["if", ["le", "calldatasize", 4], ["goto", "fallback"]])

    bucket_id = ["mod", "_calldata_method_id", n_buckets]
    bucket_hdr_location = [
        "add",
        ["symbol", "BUCKET_HEADERS"],
        ["mul", bucket_id, SZ_BUCKET_HEADER],
    ]
    # get bucket header
    dst = 32 - SZ_BUCKET_HEADER
    assert dst >= 0

    # memory is PROBABLY 0, but just be paranoid.
    selector_section.append(["mstore", 0, 0])
    selector_section.append(["codecopy", dst, bucket_hdr_location, SZ_BUCKET_HEADER])

    jumpdest = IRnode.from_list(["mload", 0])
    selector_section.append(["goto", jumpdest])

    # slight duplication with jumptable.py.
    buckets = {}   
    for sig, entry_point in entry_points.items():
        t = x % n_buckets
        buckets.setdefault(t, [])
        buckets[t].append((sig, x))

    for bucket_id, bucket in buckets.items():
        bucket_label = f"selector_bucket_{bucket_id}"
        selector_section.append(["label", bucket_label, ["var_list"], ["seq"]])

        handle_bucket = ["seq"]

        for sig, entry_point in bucket:

            dispatch = ["seq"]  # actually dispatch into the function
            callvalue_check = ["iszero", "callvalue"]
            calldatasize_check = ["ge", "calldatasize", expected_calldatasize]
            # TODO, optimize out when we can
            dispatch.append(["assert", ["and", callvalue_check, calldatasize_check]])
            dispatch.append(["goto", FUNCTION_LABEL])

            handle_bucket.append(["if", ["eq", "_calldata_method_id", _annotated_method_id(sig)], dispatch])

        handle_bucket.append(["goto", "fallback"])

        selector_section.append(handle_bucket)

    if default_function:
        fallback_ir = _ir_for_external_function(
            default_function, global_ctx, skip_nonpayable_check=False
        )
    else:
        fallback_ir = IRnode.from_list(
            ["revert", 0, 0], annotation="Default function", error_msg="fallback function"
        )

    runtime = [
        "seq",
        ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), selector_section],
    ]

    runtime.extend(function_irs)

    return runtime



# codegen for all runtime functions + callvalue/calldata checks + method
# selector routines. use the old linear selector table implementation
def _runtime_ir_legacy(runtime_functions, global_ctx):
    default_function = next((f for f in external_functions if _is_fallback(f)), None)

    # categorize the runtime functions because we will organize the runtime
    # code into the following sections:
    # payable functions, nonpayable functions, fallback function, internal_functions
    # functions that need to go exposed in the selector section
    regular_functions = [f for f in external_functions if not _is_fallback(f)]
    payables = [f for f in regular_functions if _is_payable(f)]
    nonpayables = [f for f in regular_functions if not _is_payable(f)]

    internal_functions_ir: list[IRnode] = []

    for func_ast in internal_functions:
        func_ir = _ir_for_internal_function(func_ast, global_ctx, False)
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

    selector_section = _selector_section() ["seq"]

    for func_ast in payables:
        func_ir = _ir_for_external_function(func_ast, global_ctx, skip_nonpayable_check)
        selector_section.append(func_ir)

    if batch_payable_check:
        nonpayable_check = IRnode.from_list(
            ["assert", ["iszero", "callvalue"]], error_msg="nonpayable check"
        )
        selector_section.append(nonpayable_check)

    for func_ast in nonpayables:
        ir = _ir_for_external_function(func_ast, global_ctx, skip_nonpayable_check)
        selector_section.append(ir)

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

    runtime_functions = [f for f in function_defs if not _is_constructor(f)]
    init_function = next((f for f in function_defs if _is_constructor(f)), None)

    internal_functions = [f for f in runtime_functions if _is_internal(f)]

    external_functions = [f for f in runtime_functions if not _is_internal(f)]

    if True:  # XXX: if options.optimize.gas
        selector_table = _selector_table_sparse(runtime_functions, global_ctx)
    else:  # options.optimize.codesize
        selector_table = _selector_table_dense(runtime_functions, global_ctx)

    if default_function:
        fallback_ir = _ir_for_external_function(
            default_function, global_ctx, skip_nonpayable_check=False
        )
    else:
        fallback_ir = IRnode.from_list(
            ["revert", 0, 0], annotation="Default function", error_msg="fallback function"
        )

    runtime = ["seq", selector_table, fallback_ir]

    deploy_code: List[Any] = ["seq"]
    immutables_len = global_ctx.immutable_section_bytes
    if init_function:
        # TODO might be cleaner to separate this into an _init_ir helper func
        init_func_ir = _ir_for_external_function(
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
                # unreachable code, delete it
                continue

            func_ir = _ir_for_internal_function(
                f, global_ctx, skip_nonpayable_check=False, is_ctor_context=True
            )
            deploy_code.append(func_ir)

    else:
        if immutables_len != 0:
            raise CompilerPanic("unreachable")
        deploy_code.append(["deploy", 0, runtime, 0])

    return IRnode.from_list(deploy_code), IRnode.from_list(runtime)
