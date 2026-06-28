from tests.venom_utils import PrePostChecker, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRLiteral, IRVariable
from vyper.venom.passes import RedundantMemoryCopyForwardingPass

_checker = PrePostChecker([RedundantMemoryCopyForwardingPass], default_hevm=False)


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
        %dst0 = assign %src0
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
        %dst1 = assign %src1_0
        nop
        %src2_0 = add 0, %src2
        %dst2 = assign %src2_0
        nop
        %ptr1 = add %src1_0, 32
        %val1 = mload %ptr1
        %ptr2 = assign %src2_0
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
