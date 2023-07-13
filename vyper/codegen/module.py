# a contract.vy -- all functions and constructor

from typing import Any, List

from vyper.codegen import jumptable
from vyper.codegen.core import shr
from vyper.codegen.function_definitions import generate_ir_for_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
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


def label_for_entry_point(abi_sig, entry_point):
    method_id = method_id_int(abi_sig)
    return f"{entry_point.func_t._ir_info.ir_identifier}{method_id}"


# TODO: probably dead code
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
        # TODO: this would not really be necessary if we had basic block
        # reordering in optimizer.
        ir_node = ["seq", ir_node, func_ir.common_ir]
        func_ir.entry_points[sig] = ir_node

    return IRnode.from_list(ret)


def _ir_for_internal_function(func_ast, *args, **kwargs):
    return generate_ir_for_function(func_ast, *args, **kwargs).func_ir


# codegen for all runtime functions + callvalue/calldata checks,
# with O(1) jumptable for selector table.
# uses two level strategy: uses `method_id % n_buckets` to descend
# into a bucket (of about 8-10 items), and then uses perfect hash
# to select the final function.
# costs about 212 gas for typical function and 8 bytes of code (+ ~87 bytes of global overhead)
def _selector_section_dense(external_functions, global_ctx):
    function_irs = []
    entry_points = {}  # map from ABI sigs to ir code
    sig_of = {}  # reverse map from method ids to abi sig

    for code in external_functions:
        func_ir = generate_ir_for_function(code, global_ctx, skip_nonpayable_check=True)
        for abi_sig, entry_point in func_ir.entry_points.items():
            assert abi_sig not in entry_points
            entry_points[abi_sig] = entry_point
            sig_of[method_id_int(abi_sig)] = abi_sig
        # stick function common body into final entry point to save a jump
        ir_node = IRnode.from_list(["seq", entry_point.ir_node, func_ir.common_ir])
        entry_point.ir_node = ir_node

    for abi_sig, entry_point in entry_points.items():
        label = label_for_entry_point(abi_sig, entry_point)
        ir_node = ["label", label, ["var_list"], entry_point.ir_node]
        function_irs.append(IRnode.from_list(ir_node))

    jumptable_info = jumptable.generate_dense_jumptable_info(entry_points.keys())
    n_buckets = len(jumptable_info)

    #  bucket magic <2 bytes> | bucket location <2 bytes>
    # TODO: can make it smaller if the largest bucket magic <= 255
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
    selector_section.append(["assert", ["eq", "msize", 0]])
    selector_section.append(["codecopy", dst, bucket_hdr_location, SZ_BUCKET_HEADER])

    # figure out the minimum number of bytes we can use to encode
    # min_calldatasize in function info
    largest_mincalldatasize = max(f.min_calldatasize for f in entry_points.values())
    FN_METADATA_BYTES = (largest_mincalldatasize.bit_length() + 7) // 8

    func_info_size = 4 + 2 + FN_METADATA_BYTES
    # grab function info.
    # method id <4 bytes> | label <2 bytes> | func info <1-3 bytes>
    # func info (1-3 bytes, packed) for: expected calldatasize, is_nonpayable bit
    # NOTE: might be able to improve codesize if we use variable # of bytes
    # per bucket

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

    func_info = IRnode.from_list(["mload", 0])
    fn_metadata_mask = 2 ** (FN_METADATA_BYTES * 8) - 1
    calldatasize_mask = fn_metadata_mask - 1  # ex. 0xFFFE
    with func_info.cache_when_complex("func_info") as (b1, func_info):
        x = ["seq"]

        # expected calldatasize always satisfies (x - 4) % 32 == 0
        # the lower 5 bits are always 0b00100, so we can use those
        # bits for other purposes.
        is_nonpayable = ["and", 1, func_info]
        expected_calldatasize = ["and", calldatasize_mask, func_info]

        label_bits_ofst = FN_METADATA_BYTES * 8
        function_label = ["and", 0xFFFF, shr(label_bits_ofst, func_info)]
        method_id_bits_ofst = (FN_METADATA_BYTES + 2) * 8
        function_method_id = shr(method_id_bits_ofst, func_info)

        # check method id is right, if not then fallback.
        calldatasize_valid = ["gt", "calldatasize", 3]
        method_id_correct = ["eq", function_method_id, "_calldata_method_id"]
        should_fallback = ["iszero", ["and", calldatasize_valid, method_id_correct]]
        x.append(["if", should_fallback, ["goto", "fallback"]])

        # assert callvalue == 0 if nonpayable
        bad_callvalue = ["mul", is_nonpayable, "callvalue"]
        # assert calldatasize correct
        bad_calldatasize = ["lt", "calldatasize", expected_calldatasize]
        failed_entry_conditions = ["or", bad_callvalue, bad_calldatasize]
        check_entry_conditions = IRnode.from_list(
            ["assert", ["iszero", failed_entry_conditions]],
            error_msg="bad calldatasize or callvalue",
        )
        x.append(check_entry_conditions)
        x.append(["jump", function_label])
        selector_section.append(b1.resolve(x))

    bucket_headers = ["data", "BUCKET_HEADERS"]

    for bucket_id, bucket in jumptable_info.items():
        bucket_headers.append(bucket.magic.to_bytes(2, "big"))
        bucket_headers.append(["symbol", f"bucket_{bucket_id}"])

    selector_section.append(bucket_headers)

    for bucket_id, bucket in jumptable_info.items():
        function_infos = ["data", f"bucket_{bucket_id}"]
        for method_id in bucket.method_ids:
            abi_sig = sig_of[method_id]
            entry_point = entry_points[abi_sig]

            method_id_bytes = method_id.to_bytes(4, "big")
            symbol = ["symbol", label_for_entry_point(abi_sig, entry_point)]
            func_metadata_int = entry_point.min_calldatasize | int(
                not entry_point.func_t.is_payable
            )
            func_metadata = func_metadata_int.to_bytes(FN_METADATA_BYTES, "big")

            function_infos.extend([method_id_bytes, symbol, func_metadata])

        selector_section.append(function_infos)

    runtime = [
        "seq",
        ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), selector_section],
    ]

    runtime.extend(function_irs)

    return runtime


# codegen for all runtime functions + callvalue/calldata checks,
# with O(1) jumptable for selector table.
# uses two level strategy: uses `method_id % n_methods` to calculate
# a bucket, and then descends into linear search from there.
# costs about 126 gas for typical (nonpayable, >0 args, avg bucket size 1.5)
# function and 24 bytes of code (+ ~23 bytes of global overhead)
def _selector_section_sparse(external_functions, global_ctx):
    entry_points = {}  # map from ABI sigs to ir code
    sig_of = {}  # map from method ids back to signatures

    for code in external_functions:
        func_ir = generate_ir_for_function(code, global_ctx, skip_nonpayable_check=True)
        for abi_sig, entry_point in func_ir.entry_points.items():
            assert abi_sig not in entry_points
            entry_points[abi_sig] = entry_point
            sig_of[method_id_int(abi_sig)] = abi_sig

        # stick function common body into final entry point to save a jump
        ir_node = IRnode.from_list(["seq", entry_point.ir_node, func_ir.common_ir])
        entry_point.ir_node = ir_node

    n_buckets, buckets = jumptable.generate_sparse_jumptable_buckets(entry_points.keys())

    # 2 bytes for bucket location
    SZ_BUCKET_HEADER = 2

    selector_section = ["seq"]

    # XXX: AWAITING MCOPY PR
    # if n_buckets > 1 or core._opt_none():
    if n_buckets > 1:
        bucket_id = ["mod", "_calldata_method_id", n_buckets]
        bucket_hdr_location = [
            "add",
            ["symbol", "selector_buckets"],
            ["mul", bucket_id, SZ_BUCKET_HEADER],
        ]
        # get bucket header
        dst = 32 - SZ_BUCKET_HEADER
        assert dst >= 0

        # memory is PROBABLY 0, but just be paranoid.
        selector_section.append(["assert", ["eq", "msize", 0]])
        selector_section.append(["codecopy", dst, bucket_hdr_location, SZ_BUCKET_HEADER])

        jumpdest = IRnode.from_list(["mload", 0])
        # don't particularly like using `jump` here since it can cause
        # issues for other backends, consider changing `goto` to allow
        # dynamic jumps, or adding some kind of jumptable instruction
        selector_section.append(["jump", jumpdest])

        jumptable_data = ["data", "selector_buckets"]
        for i in range(n_buckets):
            if i in buckets:
                bucket_label = f"selector_bucket_{i}"
                jumptable_data.append(["symbol", bucket_label])
            else:
                # empty bucket
                jumptable_data.append(["symbol", "fallback"])

        selector_section.append(jumptable_data)

    for bucket_id, bucket in buckets.items():
        bucket_label = f"selector_bucket_{bucket_id}"
        selector_section.append(["label", bucket_label, ["var_list"], ["seq"]])

        handle_bucket = ["seq"]

        for method_id in bucket:
            sig = sig_of[method_id]
            entry_point = entry_points[sig]
            func_t = entry_point.func_t
            expected_calldatasize = entry_point.min_calldatasize

            dispatch = ["seq"]  # code to dispatch into the function
            skip_callvalue_check = func_t.is_payable
            skip_calldatasize_check = expected_calldatasize == 4
            bad_callvalue = [0] if skip_callvalue_check else ["callvalue"]
            bad_calldatasize = (
                [0] if skip_calldatasize_check else ["lt", "calldatasize", expected_calldatasize]
            )

            dispatch.append(
                IRnode.from_list(
                    ["assert", ["iszero", ["or", bad_callvalue, bad_calldatasize]]],
                    error_msg="bad calldatasize or callvalue",
                )
            )
            # we could skip a jumpdest per method if we out-lined the entry point
            # so the dispatcher looks just like -
            # ```(if (eq <calldata_method_id> method_id)
            #   (goto entry_point_label))```
            # it would another optimization for patterns like
            # `if ... (goto)` though.
            dispatch.append(entry_point.ir_node)

            method_id_check = ["eq", "_calldata_method_id", _annotated_method_id(sig)]
            has_trailing_zeroes = method_id.to_bytes(4, "big").endswith(b"\x00")
            if has_trailing_zeroes:
                # if the method id check has trailing 0s, we need to include
                # a calldatasize check to distinguish from when not enough
                # bytes are provided for the method id in calldata.
                method_id_check = ["and", ["ge", "calldatasize", 4], method_id_check]
            handle_bucket.append(["if", method_id_check, dispatch])

        handle_bucket.append(["goto", "fallback"])

        selector_section.append(handle_bucket)

    ret = ["seq", ["with", "_calldata_method_id", shr(224, ["calldataload", 0]), selector_section]]

    return ret


# take a GlobalContext, and generate the runtime and deploy IR
def generate_ir_for_module(global_ctx: GlobalContext) -> tuple[IRnode, IRnode]:
    # order functions so that each function comes after all of its callees
    function_defs = _topsort(global_ctx.functions)

    runtime_functions = [f for f in function_defs if not _is_constructor(f)]
    init_function = next((f for f in function_defs if _is_constructor(f)), None)

    internal_functions = [f for f in runtime_functions if _is_internal(f)]

    external_functions = [
        f for f in runtime_functions if not _is_internal(f) and not _is_fallback(f)
    ]
    default_function = next((f for f in runtime_functions if _is_fallback(f)), None)

    internal_functions_ir: list[IRnode] = []

    # compile internal functions first so we have the function info
    for func_ast in internal_functions:
        func_ir = _ir_for_internal_function(func_ast, global_ctx, False)
        internal_functions_ir.append(IRnode.from_list(func_ir))

    # XXX: AWAITING MCOPY PR
    # dense vs sparse global overhead is amortized after about 4 methods
    dense = True  # if core._opt_codesize() and len(external_functions) > 4:
    if dense:
        selector_section = _selector_section_dense(external_functions, global_ctx)
    else:
        selector_section = _selector_section_sparse(external_functions, global_ctx)

    if default_function:
        fallback_ir = _ir_for_external_function(
            default_function, global_ctx, skip_nonpayable_check=False
        )
    else:
        fallback_ir = IRnode.from_list(
            ["revert", 0, 0], annotation="Default function", error_msg="fallback function"
        )

    runtime = ["seq", selector_section, ["label", "fallback", ["var_list"], fallback_ir]]

    runtime.extend(internal_functions_ir)

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
