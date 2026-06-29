from tests.venom_utils import PrePostChecker, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRLiteral, IRVariable
from vyper.venom.passes import RedundantMemoryCopyForwardingPass

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
        %dst0 = %src0
        nop
        %ptr = add %src0, 32
        %val = mload %ptr
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
    ptr_inst = next(
        inst for inst in insts if inst.has_outputs and inst.output == IRVariable("%ptr")
    )
    assert ptr_inst.opcode == "add"
    assert ptr_inst.operands == [IRLiteral(32), IRVariable("%arg")]


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
        %dst1 = %src1_0
        nop
        %src2_0 = add 0, %src2
        %dst2 = %src2_0
        nop
        %ptr1 = add %src1_0, 32
        %val1 = mload %ptr1
        %ptr2 = %src2_0
        %val2 = mload %ptr2
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


def test_forwards_dynamic_size_read_when_whole_alloca_staged():
    # When the staging copy fills the ENTIRE alloca from %src (copy_size ==
    # alloca_size) every in-bounds byte of %tmp mirrors %src, so a fixed-offset
    # dynamic-size read can be forwarded: a well-formed read cannot exceed the
    # alloca it targets, so it observes only staged bytes (e.g. a bounded
    # DynArray copy-out of `32 + count*size` bytes, count <= N). Contrast
    # test_keeps_copy_when_alias_read_has_dynamic_size, where staging is partial.
    # Uses the structural runner rather than the hevm checker: a free symbolic
    # size can exceed the alloca -- exactly the well-formedness case that bounded
    # Vyper never emits but that hevm would (correctly) flag.
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
    # the staging copy is gone; the surviving out-copy reads straight from %src
    assert len(mcopies) == 1
    assert mcopies[0].operands[1] == IRVariable("%src")


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
    ptr_inst = next(
        inst for inst in insts if inst.has_outputs and inst.output == IRVariable("%ptr")
    )
    assert ptr_inst.opcode == "add"
    assert ptr_inst.operands == [IRLiteral(32), IRVariable("%src")]


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
