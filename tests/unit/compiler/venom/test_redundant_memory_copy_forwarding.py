import pytest

from tests.venom_utils import PrePostChecker, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRLiteral, IRVariable
from vyper.venom.passes import RedundantMemoryCopyForwardingPass

pytestmark = pytest.mark.hevm

_checker = PrePostChecker([RedundantMemoryCopyForwardingPass], default_hevm=True)


def _run_redundant_forwarding(src: str):
    ctx = parse_venom(src)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    for fn in ctx.functions.values():
        RedundantMemoryCopyForwardingPass(analyses[fn], fn).run_pass()
    return ctx


def test_forwards_whole_temp_copy_to_readonly_uses():
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        %src0 = add 0, %src
        %dst0 = add 0, %tmp
        mcopy %dst0, %src0, 64
        %ptr = add 32, %tmp
        %val = mload %ptr
        %out = alloca 64
        mcopy %out, %tmp, 64
        sink %val
    """
    post = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        %src0 = add 0, %src
        %dst0 = add 0, %tmp
        nop
        %ptr = add 32, %tmp
        %1 = add %src0, 32
        %val = mload %1
        %out = alloca 64
        mcopy %out, %src0, 64
        sink %val
    """

    _checker(pre, post)


def test_forwards_readonly_internal_param_source():
    src = """
    function callee {
    callee:
        %arg = param
        %tmp = alloca 64
        mcopy %tmp, %arg, 64
        %ptr = add 32, %tmp
        %val = mload %ptr
        sink %val
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]

    assert all(inst.opcode != "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    forwarded_ptr = next(
        inst for inst in insts if inst.has_outputs and inst.output == mload.operands[0]
    )
    assert forwarded_ptr.opcode == "add"
    assert forwarded_ptr.operands == [IRLiteral(32), IRVariable("%arg")]


def test_forwards_segmented_tuple_temp_copies():
    pre = """
    main:
        %src1 = alloca 64
        %src2 = alloca 64
        %tmp = alloca 128
        %src1_0 = add 0, %src1
        %dst1 = add 0, %tmp
        mcopy %dst1, %src1_0, 64
        %src2_0 = add 0, %src2
        %dst2 = add 64, %tmp
        mcopy %dst2, %src2_0, 64
        %ptr1 = add 32, %tmp
        %val1 = mload %ptr1
        %ptr2 = add 64, %tmp
        %val2 = mload %ptr2
        sink %val1, %val2
    """
    post = """
    main:
        %src1 = alloca 64
        %src2 = alloca 64
        %tmp = alloca 128
        %src1_0 = add 0, %src1
        %dst1 = add 0, %tmp
        nop
        %src2_0 = add 0, %src2
        %dst2 = add 64, %tmp
        nop
        %ptr1 = add 32, %tmp
        %1 = add %src1_0, 32
        %val1 = mload %1
        %ptr2 = add 64, %tmp
        %val2 = mload %src2_0
        sink %val1, %val2
    """

    _checker(pre, post)


def test_keeps_copy_when_source_is_clobbered_before_read():
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        %src0 = add 0, %src
        %dst0 = add 0, %tmp
        mcopy %dst0, %src0, 64
        mstore %src, 1
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


def test_keeps_copy_from_concrete_scratch_memory():
    pre = """
    main:
        %tmp = alloca 96
        mstore 0, 2
        mstore 32, 1
        mstore 64, 2
        mcopy %tmp, 0, 96
        mstore 0, 0
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


def test_keeps_copy_when_unknown_invoke_clobbers_before_read():
    src = """
    function callee {
    callee:
        %arg = param
        %tmp = alloca 64
        mcopy %tmp, %arg, 64
        invoke @unknown_external
        %val = mload %tmp
        sink %val
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]

    assert any(inst.opcode == "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    assert mload.operands[0] == IRVariable("%tmp")


def test_keeps_copy_when_destination_is_overwritten():
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        %src0 = add 0, %src
        %dst0 = add 0, %tmp
        mcopy %dst0, %src0, 64
        mstore %tmp, 1
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


def test_keeps_copy_when_destination_escapes():
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        %src0 = add 0, %src
        %dst0 = add 0, %tmp
        mcopy %dst0, %src0, 64
        return %tmp, 64
    """

    _checker(pre, pre)


def test_keeps_copy_when_root_is_memory_read_size_operand():
    # `%tmp` is a return size, not the return's memory-address operand. Its
    # concrete allocation address is therefore observable even though return
    # reads a disjoint `%out` buffer.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %out = alloca 64
        mcopy %tmp, %src, 64
        %value = mload %tmp
        return %out, %tmp
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_source_root_is_memory_read_size_operand():
    # Forwarding extends %src's allocation lifetime. If its concrete address is
    # also observable as ordinary data, the changed lifetime can change that
    # value even though all memory reads themselves are equivalent.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %out = alloca 64
        mcopy %tmp, %src, 64
        %value = mload %tmp
        return %out, %src
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_source_alias_is_memory_read_size_operand():
    src = """
    function main {
    main:
        %src = alloca 96
        %copy_src = add 32, %src
        %observable_src = add 0, %src
        %tmp = alloca 64
        %out = alloca 64
        mcopy %tmp, %copy_src, 64
        %value = mload %tmp
        return %out, %observable_src
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%copy_src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_root_derived_read_overlaps_segment():
    pre = """
    main:
        %payload = alloca 64
        mstore %payload, 1
        %payload_tail = add 32, %payload
        mstore %payload_tail, 2
        %buf = alloca 96
        mstore %buf, 0x3eba6e4e
        %dst = add 32, %buf
        mcopy %dst, %payload, 64
        %revert_ptr = add 28, %buf
        revert %revert_ptr, 68
    """

    _checker(pre, pre)


def test_keeps_copy_when_destination_read_uses_dynamic_root_offset():
    pre = """
    main:
        %src = alloca 96
        %out = alloca 224
        %dst = add 32, %out
        mcopy %dst, %src, 96
        %idx = calldataload 0
        %offset = mul 96, %idx
        %ptr = add %out, %offset
        %val = mload %ptr
        sink %val
    """

    _checker(pre, pre)


def test_keeps_copy_when_alias_read_has_dynamic_size():
    # The read starts inside the copied segment, but its runtime size could
    # extend beyond the bytes populated by the staging copy. The pass cannot
    # prove containment, so it must keep the copy.
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 96
        %out = alloca 96
        mcopy %tmp, %src, 64
        %alias = add 32, %tmp
        %n = calldataload 0
        mcopy %out, %alias, %n
        sink
    """

    _checker(pre, pre)


def test_keeps_dynamic_size_read_when_whole_alloca_staged():
    # Venom does not carry a proof that %n stays within %tmp. If it exceeds 64,
    # the original read observes the bytes after %tmp while a forwarded read
    # observes the bytes after %src, so even a whole-allocation copy is not
    # sufficient evidence for forwarding.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        %n = calldataload 0
        %out = alloca 64
        mcopy %out, %tmp, %n
        sink
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]

    mcopies = [i for i in insts if i.opcode == "mcopy"]
    assert len(mcopies) == 2
    assert any(
        inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")] for inst in mcopies
    )


def test_forwards_bounded_dynamic_size_read():
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        %raw_n = calldataload 0
        %n = and %raw_n, 63
        %out = alloca 64
        mcopy %out, %tmp, %n
        sink
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]

    mcopies = [inst for inst in insts if inst.opcode == "mcopy"]
    assert len(mcopies) == 1
    assert mcopies[0].operands[1] == IRVariable("%src")


@pytest.mark.parametrize("max_size, forwards", [(64, True), (65, False)])
def test_uses_dynamic_read_max_size_metadata(max_size, forwards):
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        %n = calldataload 0
        %out = alloca 64
        mcopy %out, %tmp, %n
        sink
    }
    """

    ctx = parse_venom(src)
    main = ctx.get_function(IRLabel("main"))
    dynamic_copy = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "mcopy" and isinstance(inst.operands[0], IRVariable)
    )
    dynamic_copy.memory_read_max_size = max_size

    analyses = IRAnalysesCache(main)
    RedundantMemoryCopyForwardingPass(analyses, main).run_pass()
    staging_copy_exists = any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
    )
    assert staging_copy_exists is not forwards


def test_literal_read_size_takes_precedence_over_max_size_metadata():
    # The 65-byte read stays within %tmp but exceeds the 64-byte staged segment.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 65
        mcopy %tmp, %src, 64
        %out = alloca 65
        mcopy %out, %tmp, 65
        sink
    }
    """

    ctx = parse_venom(src)
    main = ctx.get_function(IRLabel("main"))
    oversized_copy = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "mcopy" and inst.operands[0] == IRLiteral(65)
    )
    oversized_copy.memory_read_max_size = 64

    analyses = IRAnalysesCache(main)
    RedundantMemoryCopyForwardingPass(analyses, main).run_pass()

    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
    )


def test_keeps_large_aggregate_copy_without_layout_cost_model():
    pre = """
    main:
        %src = alloca 8192
        %tmp = alloca 8192
        mcopy %tmp, %src, 8192
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


def test_keeps_small_slice_of_large_source_without_layout_cost_model():
    pre = """
    main:
        %src = alloca 8192
        %tmp = alloca 32
        %pressure = alloca 8192
        mstore %src, 1
        mcopy %tmp, %src, 32
        %hash = sha3 %pressure, 8192
        %val = mload %tmp
        sink %hash, %val
    """

    _checker(pre, pre)


@pytest.mark.parametrize("src_size,tmp_size", [(32, 64), (64, 32)])
def test_keeps_copy_when_access_exceeds_alloca(src_size, tmp_size):
    pre = f"""
    main:
        %src = alloca {src_size}
        %tmp = alloca {tmp_size}
        mcopy %tmp, %src, 64
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


# ---------------------------------------------------------------------------
# cross-block coverage
# ---------------------------------------------------------------------------


def test_forwards_into_dominated_successor_block():
    # mcopy in one block, readonly read in a strictly-dominated successor:
    # the read forwards back to %src.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        jmp @next
    next:
        %ptr = add 32, %tmp
        %val = mload %ptr
        sink %val
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]

    assert all(inst.opcode != "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    forwarded_ptr = next(
        inst for inst in insts if inst.has_outputs and inst.output == mload.operands[0]
    )
    assert forwarded_ptr.opcode == "add"
    assert forwarded_ptr.operands == [IRLiteral(32), IRVariable("%src")]


def test_forwards_through_pointer_phi():
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        jnz 1, @left, @right
    left:
        %left_ptr = add 32, %tmp
        jmp @join
    right:
        %right_ptr = add 32, %tmp
        jmp @join
    join:
        %ptr = phi @left, %left_ptr, @right, %right_ptr
        %val = mload %ptr
        sink %val
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]

    assert all(inst.opcode != "mcopy" for inst in insts)

    # The phi is left intact -- rewriting it in place would put a non-phi at the
    # block top. Its read is redirected to a fresh `add 32, %src`.
    phi_inst = next(
        inst for inst in insts if inst.has_outputs and inst.output == IRVariable("%ptr")
    )
    assert phi_inst.opcode == "phi"

    load = next(inst for inst in insts if inst.opcode == "mload")
    ptr_inst = next(inst for inst in insts if inst.has_outputs and inst.output == load.operands[0])
    assert ptr_inst.opcode == "add"
    assert ptr_inst.operands == [IRLiteral(32), IRVariable("%src")]


def test_keeps_copy_when_pointer_phi_may_leave_copied_segment():
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 128
        mcopy %tmp, %src, 64
        jnz 1, @left, @right
    left:
        %left_ptr = add 32, %tmp
        jmp @join
    right:
        %right_ptr = add 96, %tmp
        jmp @join
    join:
        %ptr = phi @left, %left_ptr, @right, %right_ptr
        %val = mload %ptr
        sink %val
    """

    _checker(pre, pre)


def test_forwards_pointer_phi_with_sibling_phi():
    # A pointer-phi that normalizes to a concrete offset must NOT be rewritten in
    # place when the join block has other phis: doing so would drop an `add`
    # ahead of the `%optr` phi and break the phis-at-block-top invariant. The
    # read is redirected instead and both phis stay at the top of @join.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %osrc = alloca 32
        mcopy %tmp, %src, 64
        jnz 1, @left, @right
    left:
        %lp = add 32, %tmp
        %lo = add 0, %osrc
        jmp @join
    right:
        %rp = add 32, %tmp
        %ro = add 0, %osrc
        jmp @join
    join:
        %ptr = phi @left, %lp, @right, %rp
        %optr = phi @left, %lo, @right, %ro
        %val = mload %ptr
        %v2 = mload %optr
        sink %val, %v2
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))

    assert all(inst.opcode != "mcopy" for bb in main.get_basic_blocks() for inst in bb.instructions)

    # no non-phi instruction may precede a phi in any block
    for bb in main.get_basic_blocks():
        seen_non_phi = False
        for inst in bb.instructions:
            if inst.opcode == "phi":
                assert not seen_non_phi, "phi follows a non-phi instruction"
            else:
                seen_non_phi = True


def test_keeps_copy_when_pointer_phi_merges_untracked_address():
    # %p merges the staged buffer with an untracked (calldata-derived) address.
    # On the @b edge %p does not point into %tmp, so its read cannot be
    # forwarded to %src and the copy must stay.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        %ext = calldataload 0
        jnz 1, @a, @b
    a:
        jmp @join
    b:
        jmp @join
    join:
        %p = phi @a, %tmp, @b, %ext
        %v = mload %p
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_has_local_alloca_base():
    # %s is rooted in a local alloca (writable) with an offset coming from a
    # readonly param. The readonly-param clobber check sees unknown-base writes
    # only, so the write to %local would be missed -- the copy must stay.
    # (The exclusive param walk rejects the add-derived %s; the tracked-base
    # guard rejects it independently.)
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %s = add %arg, %local
        mcopy %tmp, %s, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_merges_with_local_bases():
    # MemoryLocation collapses to an unknown base when several local bases can
    # reach %s. That must still not take the readonly-param path, because a
    # later write to either local base can clobber the source selected at runtime.
    # (The phi's alloca arms make the exclusive param walk return None; the
    # tracked-base guard rejects it independently.)
    src = """
    function callee {
    callee:
        %arg = param
        %local1 = alloca 64
        %local2 = alloca 64
        %tmp = alloca 64
        jnz 1, @a, @b
    a:
        jmp @join
    b:
        jnz 1, @b1, @b2
    b1:
        jmp @join
    b2:
        jmp @join
    join:
        %s = phi @a, %arg, @b1, %local1, @b2, %local2
        mcopy %tmp, %s, 64
        mstore %local1, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_reassigned_param_var_has_tracked_base():
    # The parser accepts pre-SSA input (this harness runs the pass without
    # MakeSSA), so a reassigned param variable can be a param leaf for the
    # exclusive param walk while carrying a tracked local-alloca base with
    # unknown offset. Only the tracked-base guard rejects this shape: on SSA
    # input the exclusive walk alone rejects arithmetic-derived sources.
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %dyn = calldataload 0
        %arg = add %local, %dyn
        mcopy %tmp, %arg, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_reassigned_param_var_has_untracked_base():
    # The source variable is syntactically a parameter but its reaching value
    # can be an arbitrary address. Treating it as exclusively param-backed
    # would incorrectly ignore a local write that may alias that address.
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %arg = calldataload 0
        mcopy %tmp, %arg, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_merges_untracked_address():
    # root_param_indices(%s) sees %arg, but the %ext arm is an unknown address
    # root. That missing root must not be accepted as proof that every source
    # path is readonly-param-backed.
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %ext = calldataload 0
        jnz 1, @a, @b
    a:
        jmp @join
    b:
        jmp @join
    join:
        %s = phi @a, %arg, @b, %ext
        mcopy %tmp, %s, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_merges_literal_address():
    # The %lit arm is a literal address, not a param root. A literal is still a
    # non-param root, so it must not be accepted as proof that every source
    # path is readonly-param-backed.
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %lit = assign 288
        jnz 1, @a, @b
    a:
        jmp @join
    b:
        jmp @join
    join:
        %s = phi @a, %arg, @b, %lit
        mcopy %tmp, %s, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_has_param_offset():
    # The readonly-param root query sees both params, but %s is not proven to
    # stay inside either readonly param region. The source could alias a local
    # alloca that is written after the snapshot.
    src = """
    function callee {
    callee:
        %arg = param
        %idx = param
        %local = alloca 64
        %tmp = alloca 64
        %s = add %idx, %arg
        mcopy %tmp, %s, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_readonly_param_source_has_constant_offset():
    # A constant offset from a readonly param is still pointer arithmetic, and
    # this pass has no proof that the copied range stays within the param.
    src = """
    function callee {
    callee:
        %arg = param
        %local = alloca 64
        %tmp = alloca 64
        %s = add 32, %arg
        mcopy %tmp, %s, 64
        mstore %local, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    callee = ctx.get_function(IRLabel("callee"))
    insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_fixed_source_merges_untracked_address():
    # BasePtrAnalysis can report a fixed local source for %s by ignoring the
    # untracked arm. That is not enough proof for forwarding: %ext can alias
    # another local buffer which is written after the snapshot.
    src = """
    function main {
    main:
        %local = alloca 64
        %other = alloca 64
        %tmp = alloca 64
        %ext = calldataload 0
        jnz 1, @a, @b
    a:
        jmp @join
    b:
        jmp @join
    join:
        %s = phi @a, %local, @b, %ext
        mcopy %tmp, %s, 64
        mstore %other, 1
        %v = mload %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%s"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_root_escapes_as_stored_value():
    # The staged buffer pointer is stored into another buffer as a value; a
    # later load through that buffer could read %tmp, so even though %tmp is
    # also read directly, the copy cannot be removed.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %box = alloca 64
        mcopy %tmp, %src, 64
        %v = mload %tmp
        mstore %box, %tmp
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_same_pointer_is_store_address_and_value():
    # %p is outside the copied segment as a write address, but it also escapes
    # as the stored value. Operand role, not value equality, decides that.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 128
        mcopy %tmp, %src, 64
        %p = add 96, %tmp
        %v = mload %tmp
        mstore %p, %p
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_derived_pointer_escapes_as_stored_value():
    # Same escape as storing %tmp directly, but through a derived unknown-offset
    # pointer. The pointer-use walk must treat the non-address mstore operand as
    # an escape even though the write target itself (%box) does not alias %tmp.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %box = alloca 64
        %idx = calldataload 0
        mcopy %tmp, %src, 64
        %p = add %idx, %tmp
        %v = mload %tmp
        mstore %box, %p
        sink %v
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_keeps_copy_when_alias_is_memory_read_size_operand():
    # The staged pointer appears in both the source-address slot and the size
    # slot. Only the source-address occurrence is a readonly memory read; the
    # size occurrence is an ordinary value use and cannot be redirected.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %out = alloca 64
        mcopy %tmp, %src, 64
        %p = add 0, %tmp
        mcopy %out, %p, %p
        sink
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_destination_alias_is_reassigned_to_literal():
    # BasePtr facts are monotone on pre-SSA input. %p therefore still carries
    # %tmp's pointer fact after the literal assignment, but the mload's runtime
    # address is zero and must not be redirected to %src.
    src = """
    function main {
    main:
        %src = alloca 64
        %tmp = alloca 64
        %p = %tmp
        mcopy %tmp, %src, 64
        %p = 0
        %zero_value = mload %p
        %tmp_value = mload %tmp
        sink %zero_value, %tmp_value
    }
    """

    ctx = _run_redundant_forwarding(src)
    main = ctx.get_function(IRLabel("main"))
    insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert any(
        inst.opcode == "mcopy"
        and inst.operands == [IRLiteral(64), IRVariable("%src"), IRVariable("%tmp")]
        for inst in insts
    )


def test_keeps_copy_when_src_clobbered_on_inter_block_path():
    # A write to %src on the path between the copy and a read in the
    # successor block must keep the copy.
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        jmp @next
    next:
        mstore %src, 1
        %val = mload %tmp
        sink %val
    """

    _checker(pre, pre)


def test_keeps_copy_when_loop_back_edge_clobbers_src():
    # The loop body writes %src, and that write reaches the next iteration's
    # read through the loop-header memory phi. The clobber walk sees the
    # backedge and conservatively keeps the copy.
    pre = """
    main:
        %src = alloca 64
        %tmp = alloca 64
        jmp @loop
    loop:
        mcopy %tmp, %src, 64
        %val = mload %tmp
        mstore %src, %val
        jnz %val, @loop, @exit
    exit:
        sink %val
    """

    _checker(pre, pre)


def test_forwards_via_redirect_when_alias_defined_before_src():
    # %alias (a pointer into %tmp) is defined *before* %src, so it cannot be
    # rewritten in place (that would be a use-before-def). Instead its read is
    # redirected to a fresh `add 32, %src` inserted at the read site -- which
    # %src dominates by construction -- and the copy is forwarded. hevm confirms
    # the forwarded form is equivalent.
    pre = """
    main:
        %tmp = alloca 64
        %alias = add 32, %tmp
        %src = alloca 64
        mcopy %tmp, %src, 64
        %val = mload %alias
        sink %val
    """
    post = """
    main:
        %tmp = alloca 64
        %alias = add 32, %tmp
        %src = alloca 64
        nop
        %1 = add %src, 32
        %val = mload %1
        sink %val
    """

    _checker(pre, post)
