import pytest

from tests.venom_utils import PrePostChecker, parse_venom
from vyper.evm.opcodes import version_check
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import SCCP, MemMergePass, RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker([MemMergePass, RemoveUnusedVariablesPass], default_hevm=False)


def _check_no_change(pre):
    _check_pre_post(pre, pre)


# for parametrizing tests
LOAD_COPY = [("dload", "dloadbytes"), ("calldataload", "calldatacopy")]


def test_memmerging():
    """
    Basic memory merge test
    All mloads and mstores can be
    transformed into mcopy
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        %3 = mload 64
        mstore 1000, %1
        mstore 1032, %2
        mstore 1064, %3
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 96
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_out_of_order():
    """
    interleaved mloads/mstores which can be transformed into mcopy
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 32
        %2 = mload 0
        mstore 132, %1
        %3 = mload 64
        mstore 164, %3
        mstore 100, %2
        stop
    """

    post = """
    _global:
        mcopy 100, 0, 96
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_interleaved_overlap():
    """
    Test that mloads do not flush all potential copies, only flush regions
    that they read from.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        %1 = mload 352
        mstore 448, %1

        %2 = mload 416
        mstore 64, %2
        %3 = mload 448  ; barrier, flushes mstore 448 from list of potential copies
        mstore 96, %3
        stop
    """

    post = """
    main:
        %1 = mload 352
        mstore 448, %1
        mcopy 64, 416, 64
        stop
    """

    _check_pre_post(pre, post)


def test_memmerging_imposs():
    """
    Test case of impossible merge
    Impossible because of the overlap
    [0        96]
          [32        128]
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        %3 = mload 64
        mstore 32, %1

        ; BARRIER - overlap between src and dst
        ; (writes to source of potential mcopy)
        mstore 64, %2

        mstore 96, %3
        stop
    """
    _check_no_change(pre)


def test_memmerging_imposs_mstore():
    """
    Test case of impossible merge
    Impossible because of the mstore barrier
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 16
        mstore 1000, %1
        %3 = mload 1000  ; BARRIER - load from dst of potential mcopy
        mstore 1016, %2
        mstore 2000, %3
        stop
    """
    _check_no_change(pre)


@pytest.mark.xfail
def test_memmerging_bypass_fence():
    """
    We should be able to optimize this to an mcopy(0, 1000, 64), but
    currently do not
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail

    pre = """
    function _global {
        _global:
            %1 = mload 0
            %2 = mload 32
            mstore %1, 1000
            %3 = mload 1000
            mstore 1032, %2
            mstore 2000, %3
            stop
    }
    """

    ctx = parse_venom(pre)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        SCCP(ac, fn).run_pass()
        MemMergePass(ac, fn).run_pass()

    fn = next(iter(ctx.functions.values()))
    bb = fn.entry
    assert any(inst.opcode == "mcopy" for inst in bb.instructions)


def test_memmerging_imposs_unkown_place():
    """
    Test case of impossible merge
    Impossible because of the
    non constant address mload and mstore barier
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = param
        %2 = mload 0
        %3 = mload %1  ; BARRIER
        %4 = mload 32
        %5 = mload 64
        mstore 1000, %2
        mstore 1032, %4
        mstore 10, %1  ; BARRIER
        mstore 1064, %5
        return %3  ; block it from being removed by RemoveUnusedVariables
    """
    _check_no_change(pre)


def test_memmerging_imposs_msize():
    """
    Test case of impossible merge
    Impossible because of the msize barier
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = msize  ; BARRIER
        %3 = mload 32
        %4 = mload 64
        mstore 1000, %1
        mstore 1032, %3
        %5 = msize  ; BARRIER
        mstore 1064, %4
        return %2, %5
    """
    _check_no_change(pre)


def test_memmerging_partial_msize():
    """
    Only partial merge possible
    because of the msize barier
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        %3 = mload 64
        mstore 1000, %1
        mstore 1032, %2
        %4 = msize  ; BARRIER
        mstore 1064, %3
        return %4
    """

    post = """
    _global:
        %3 = mload 64
        mcopy 1000, 0, 64
        %4 = msize
        mstore 1064, %3
        return %4
    """
    _check_pre_post(pre, post)


def test_memmerging_partial_overlap():
    """
    Two different copies from overlapping
    source range

    [0                     128]
        [24    88]
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        %3 = mload 64
        %4 = mload 96
        %5 = mload 24
        %6 = mload 56
        mstore 1064, %3
        mstore 1096, %4
        mstore 1000, %1
        mstore 1032, %2
        mstore 2024, %5
        mstore 2056, %6
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 128
        mcopy 2024, 24, 64
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_partial_different_effect():
    """
    Only partial merge possible
    because of the generic memory
    effect barier
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        %3 = mload 64
        mstore 1000, %1
        mstore 1032, %2
        dloadbytes 2000, 1000, 1000  ; BARRIER
        mstore 1064, %3
        stop
    """

    post = """
    _global:
        %3 = mload 64
        mcopy 1000, 0, 64
        dloadbytes 2000, 1000, 1000
        mstore 1064, %3
        stop
    """
    _check_pre_post(pre, post)


def test_memmerge_ok_interval_subset():
    """
    Test subintervals get subsumed by larger intervals
    mstore(<dst>, mload(<src>))
    mcopy(<dst>, <src>, 64)
    =>
    mcopy(<dst>, <src>, 64)
    Because the first mload/mstore is contained in the mcopy
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        mstore 100, %1
        mcopy 100, 0, 33
        stop
    """

    post = """
    _global:
        mcopy 100, 0, 33
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_ok_overlap():
    """
    Test for with source overlap
    which is ok to do
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 24
        %3 = mload 48
        mstore 1000, %1
        mstore 1024, %2
        mstore 1048, %3
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 80
        stop
    """

    _check_pre_post(pre, post)


def test_memmerging_mcopy():
    """
    Test that sequences of mcopy get merged (not just loads/stores)
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 0, 32
        mcopy 1032, 32, 32
        mcopy 1064, 64, 64
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 128
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_mcopy_small():
    """
    Test that sequences of mcopies get merged, and that mcopy of 32 bytes
    gets transformed to mload/mstore (saves 1 byte)
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 0, 16
        mcopy 1016, 16, 16
        stop
    """

    post = """
    _global:
        %1 = mload 0
        mstore 1000, %1
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_mcopy_small_overlap():
    """
    Check that mcopy with overlapping src/dst can get optimized
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 0, 0, 32
        stop
    """

    post = """
    _global:
        %1 = mload 0
        mstore 0, %1
        stop
    """

    _check_pre_post(pre, post)


def test_memmerging_mcopy_small_partial_overlap():
    """
    Test that we can optimize small mcopy even though it is a
    partially self overlapping mcopy
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 0, 16, 32
        stop
    """

    post = """
    _global:
        %1 = mload 16
        mstore 0, %1
        stop
    """

    _check_pre_post(pre, post)


def test_memmerging_mcopy_weird_bisect():
    """
    Check that bisect_left finds the correct merge
    copy(80, 100, 2)
    copy(150, 60, 1)
    copy(82, 102, 3)
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 80, 100, 2
        mcopy 150, 60, 1
        mcopy 82, 102, 3
        stop
    """

    post = """
    _global:
        mcopy 150, 60, 1
        mcopy 80, 100, 5
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_mcopy_weird_bisect2():
    """
    Check that bisect_left finds the correct merge
    copy(80, 50, 2)
    copy(20, 100, 1)
    copy(82, 52, 3)
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 80, 50, 2
        mcopy 20, 100, 1
        mcopy 82, 52, 3
        stop
    """

    post = """
    _global:
        mcopy 20, 100, 1
        mcopy 80, 50, 5
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_allowed_overlapping():
    """
    Test merge of interleaved mload/mstore/mcopy works
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 32
        mcopy 1000, 32, 128
        %2 = mload 0
        mstore 2032, %1
        mstore 2000, %2
        stop
    """

    post = """
    _global:
        mcopy 1000, 32, 128
        mcopy 2000, 0, 64
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_allowed_overlapping2():
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 0, 64
        %1 = mload 1032
        mstore 2000, %1
        %2 = mload 1064
        mstore 2032, %2
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 64
        mcopy 2000, 1032, 64
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_no_eliminate_mload():
    """
    Test that mload that are unused in memmerge will not be eliminated
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 100
        %2 = mload 132
        mstore 64, %2

        # does not interfere with the mload/mstore merging even though
        # it cannot be removed
        %3 = mload 32

        mstore 32, %1
        return %3, %3
    """

    post = """
    _global:
        %3 = mload 32
        mcopy 32, 100, 64
        return %3, %3
    """

    _check_pre_post(pre, post)


def test_memmerging_no_eliminate_mload1():
    """
    Test that mload used both inside and outside of memmerge will not be
    eliminated
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 100
        %2 = mload 132
        mstore 0, %1

        # this gets subsumed by the mcopy, but it still cannot be
        # removed because of the later use after mcopy.
        %3 = mload 32

        mstore 32, %2
        return %3, %3
    """

    post = """
    _global:
        %3 = mload 32
        mcopy 0, 100, 64
        return %3, %3
    """
    _check_pre_post(pre, post)


def test_memmerging_mload_read_after_write_hazard():
    """
    Test on invalidating load by writes
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:

        %1 = mload 100
        %2 = mload 132
        mstore 0, %1
        %3 = mload 32

        ; BARRIER. the mload 32 is overwritten. cannot fuse
        ; into mcopy(1000, 0, 64)!
        mstore 32, %2

        %4 = mload 64
        mstore 1000, %3
        mstore 1032, %4
        stop
    """

    post = """
    _global:
        ; must mload before the read buffer gets overwritten with mcopy
        %3 = mload 32

        ; fuse to mcopy
        mcopy 0, 100, 64

        ; the mloads/mstores from [32,96) to [1000,1064) cannot be fused
        ; to mcopy
        %4 = mload 64
        mstore 1000, %3
        mstore 1032, %4
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_mcopy_read_after_write_hazard():
    """
    Test that check the read after write hazards on mcopy.
    The existing copies must be flushed when some
    other copy needs to read from them
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 32, 64

        ; BARRIER. reads from destination buffer of prev instruction
        mcopy 2000, 1000, 64

        mcopy 1064, 96, 64
        stop
    """
    _check_no_change(pre)


def test_memmerging_write_after_write():
    """
    Check that conflicting writes (from different source locations)
    produce a barrier - mstore+mstore version
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 100
        %3 = mload 32
        %4 = mload 132
        mstore 1000, %1
        mstore 1000, %2  ; result of mload(100), partial barrier
        mstore 1032, %4
        mstore 1032, %3  ; BARRIER
        stop
    """

    post = """
    _global:
        %1 = mload 0
        %3 = mload 32
        mstore 1000, %1
        mcopy 1000, 100, 64
        mstore 1032, %3  ; BARRIER
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_write_after_write_mstore_and_mcopy():
    """
    Check that conflicting writes (from different source locations)
    produce a barrier - mstore+mcopy version
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        mstore 1000, %1

        ; barrier, writes to dst buf of previous instruction
        mcopy 1000, 100, 64

        mstore 1032, %2
        mcopy 1016, 116, 64
        stop
    """
    _check_no_change(pre)


def test_memmerging_write_after_write_mstore_and_mcopy_allowed():
    """
    Test on interleaved case of possible write after writes
    hazards that are however ok
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 132
        mstore 1000, %1

        ; these three instructions write to the same region from the same
        ; source. they can be merged into a single mcopy.
        mcopy 1000, 100, 16
        mstore 1032, %2
        mcopy 1016, 116, 64

        stop
    """

    post = """
    _global:
        %1 = mload 0
        mstore 1000, %1
        mcopy 1000, 100, 80
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_write_after_write_only_mcopy():
    """
    Check that conflicting writes (from different source locations)
    produce a barrier - mcopy+mcopy version
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 0, 16
        mcopy 1000, 100, 16  ; write barrier
        mcopy 1016, 116, 64
        mcopy 1016, 16, 64
        stop
    """

    post = """
    _global:
        mcopy 1000, 0, 16
        mcopy 1000, 100, 80
        mcopy 1016, 16, 64
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_not_allowed_overlapping():
    """
    Test on invalidating mloads by mcopy
    """
    if not version_check(begin="cancun"):
        return

    # NOTE: maybe optimization is possible here, to:
    # mcopy 2000, 1000, 64
    # mcopy 1000, 0, 128
    pre = """
    _global:
        %1 = mload 1000
        %2 = mload 1032
        mcopy 1000, 0, 128 ; BARRIER - invalidates (mload 1000)
        mstore 2000, %1
        mstore 2032, %2
        stop
    """
    _check_no_change(pre)


def test_memmerging_not_allowed_overlapping2():
    """
    Test that mcopy invalidates with partial overlap
    """
    if not version_check(begin="cancun"):
        return

    # NOTE: maybe optimization is possible here, to:
    # mcopy 2000, 1000, 64
    # mcopy 1000, 0, 128
    pre = """
    _global:
        %1 = mload 1032
        mcopy 1000, 0, 64  ; BARRIER - invalidates (mload 1032)
        mstore 2000, %1
        %2 = mload 1064
        mstore 2032, %2
        stop
    """

    _check_no_change(pre)


def test_memmerging_existing_copy_overwrite():
    """
    Check that memmerge does not write over source of another copy
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 1000, 0, 64
        %1 = mload 2000

        # barrier, write over source of existing copy
        mstore 0, %1

        mcopy 1064, 64, 64
        stop
    """

    _check_no_change(pre)


def test_memmerging_double_use():
    """
    Test that the mloads that are used in more places then
    the copying are not removed
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %1 = mload 0
        %2 = mload 32
        mstore 1000, %1
        mstore 1032, %2
        return %1
    """

    post = """
    _global:
        %1 = mload 0
        mcopy 1000, 0, 64
        return %1
    """

    _check_pre_post(pre, post)


def test_existing_mcopy_overlap_nochange():
    """
    Check that mcopy which already contains an overlap does not get optimized
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 32, 33, 2
        return %1
    """
    _check_no_change(pre)


@pytest.mark.parametrize("load_opcode,copy_opcode", LOAD_COPY)
def test_memmerging_load(load_opcode, copy_opcode):
    """
    Test basic merge of two load store pairs into copy
    """
    pre = f"""
    _global:
        %1 = {load_opcode} 0
        mstore 32, %1
        %2 = {load_opcode} 32
        mstore 64, %2
        stop
    """

    post = f"""
    _global:
        {copy_opcode} 32, 0, 64
        stop
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("load_opcode,copy_opcode", LOAD_COPY)
def test_memmerging_two_intervals_diff_offset(load_opcode, copy_opcode):
    """
    Test different dloadbytes/calldatacopy sequences are separately merged
    """
    pre = f"""
    _global:
        %1 = {load_opcode} 0
        mstore 0, %1
        {copy_opcode} 32, 32, 64
        %2 = {load_opcode} 0
        mstore 8, %2
        {copy_opcode} 40, 32, 64
        stop
    """

    post = f"""
    _global:
        {copy_opcode} 0, 0, 96
        {copy_opcode} 8, 0, 96
        stop
    """
    _check_pre_post(pre, post)


def test_memmerging_copy_overlap():
    """
    Test self overlapping mcopies. The fusing is blocked because
    it is not semantics preserving.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        mcopy 100, 90, 20
        mcopy 120, 110, 20
        stop
    """

    _check_no_change(pre)


def test_memmerging_copy_write_after_read():
    """
    Test for write after read case in copy instruction merge logic
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        mcopy 100, 0, 20
        mcopy 0, 1000, 20  ; barrier. reads from prev instruction's dst buffer
        mcopy 120, 20, 20
        stop
    """

    _check_no_change(pre)


def test_memmerging_copy_overlap_ok():
    """
    Test merging of overlapping copies that is ok
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        mcopy 0, 0, 100
        mcopy 100, 100, 10
        stop
    """

    post = """
    main:
        mcopy 0, 0, 110
        stop
    """

    _check_pre_post(pre, post)


def test_memmerging_copy_overlap_not_allowed():
    """
    Test merging overlapping copies that is *not* allowed
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        mcopy 0, 10, 100
        mcopy 10, 20, 100  ; can't fuse these; breaks semantics of mcopy
        stop
    """

    _check_no_change(pre)


def test_memmerge_mload_mstore_overlap_ok():
    """
    Test merging overlapping copies that is allowed - mload/mstore case
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    main:
        %1 = mload 0
        mstore 0, %1
        %2 = mload 32
        mstore 32, %2
        stop
    """

    post = """
    main:
        mcopy 0, 0, 64
        stop
    """

    _check_pre_post(pre, post)


@pytest.mark.xfail
# we could theoretically merge mcopies in the case that one range
# encloses the other range, but currently we don't.
def test_memmmerging_enclosed_mcopy():
    """
    Test with enclosed copy (basic)
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail

    pre = """
    main:
        mcopy 0, 0, 20
        mcopy 0, 0, 50
        stop
    """

    post = """
    main:
        mcopy 0, 0, 50
        stop
    """

    _check_pre_post(pre, post)


@pytest.mark.xfail
def test_memmerging_enclosed_mcopy_dst_src_offset():
    """
    Test on two self overlapping mcopies that each has src/dst overlap
    (should be valid transformation but current solution does not handle it)
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail

    pre = """
    main:
        mcopy 0, 5, 20
        mcopy 0, 5, 50
        stop
    """

    post = """
    main:
        mcopy 0, 5, 50
        stop
    """

    _check_pre_post(pre, post)


@pytest.mark.xfail
def test_memmerging_enclosed_mcopy_different_start():
    """
    Test on two self overlapping mcopies that overlap themselves
    (should be ok but current solution does not handle it)
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail

    pre = """
    main:
        mcopy 10, 10, 20
        mcopy 0, 0, 50
        stop
    """

    post = """
    main:
        mcopy 0, 0, 50
        stop
    """

    _check_pre_post(pre, post)


@pytest.mark.xfail
def test_memmerging_enclosed_mcopy_most_general():
    """
    Test on two self overlapping mcopies that overlap
    themselves (should be ok but current solution does not handle it)
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail

    pre = """
    main:
        mcopy 10, 15, 20
        mcopy 0, 5, 50
        stop
    """

    post = """
    main:
        mcopy 0, 5, 50
        stop
    """

    _check_pre_post(pre, post)


def test_memzeroing_1():
    """
    Test of basic memzeroing done with mstore only
    """

    pre = """
    _global:
        mstore 32, 0
        mstore 64, 0
        mstore 96, 0
        stop
    """

    post = """
    _global:
        %1 = calldatasize
        calldatacopy 32, %1, 96
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_2():
    """
    Test of basic memzeroing done with calldatacopy only

    sequence of these instruction will
    zero out the memory at destination
    %1 = calldatasize
    calldatacopy <dst> %1 <size>
    """

    pre = """
    _global:
        %1 = calldatasize
        calldatacopy 64, %1, 128
        %2 = calldatasize
        calldatacopy 192, %2, 128
        stop
    """

    post = """
    _global:
        %3 = calldatasize
        calldatacopy 64, %3, 256
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_3():
    """
    Test of basic memzeroing done with combination of
    mstores and calldatacopies
    """

    pre = """
    _global:
        %1 = calldatasize
        calldatacopy 0, %1, 100
        mstore 100, 0
        %2 = calldatasize
        calldatacopy 132, %2, 100
        mstore 232, 0
        stop
    """

    post = """
    _global:
        %3 = calldatasize
        calldatacopy 0, %3, 264
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_small_calldatacopy():
    """
    Test of converting calldatacopy of
    size 32 into mstore
    """

    pre = """
    _global:
        %1 = calldatasize
        calldatacopy 0, %1, 32
        stop
    """

    post = """
    _global:
        mstore 0, 0
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_smaller_calldatacopy():
    """
    Test merging smaller (<32) calldatacopies
    into either calldatacopy or mstore
    """

    pre = """
    _global:
        %1 = calldatasize
        calldatacopy 0, %1, 8
        %2 = calldatasize
        calldatacopy 8, %2, 16
        %3 = calldatasize
        calldatacopy 100, %3, 8
        %4 = calldatasize
        calldatacopy 108, %4, 16
        %5 = calldatasize
        calldatacopy 124, %5, 8
        stop
    """

    post = """
    _global:
        %6 = calldatasize
        calldatacopy 0, %6, 24
        mstore 100, 0
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_overlap():
    """
    Test of merging overlaping zeroing intervals

    [128        160]
        [136                  192]
    """

    pre = """
    _global:
        mstore 100, 0
        %1 = calldatasize
        calldatacopy 108, %1, 56
        stop
    """

    post = """
    _global:
        %2 = calldatasize
        calldatacopy 100, %2, 64
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_imposs():
    """
    Test of memzeroing barriers caused
    by non constant arguments
    """

    pre = """
    _global:
        %1 = param  ; abstract location, causes barrier
        mstore 32, 0
        mstore %1, 0
        mstore 64, 0
        %2 = calldatasize
        calldatacopy %1, %2, 10
        mstore 96, 0
        %3 = calldatasize
        calldatacopy 10, %3, %1
        mstore 128, 0
        calldatacopy 10, %1, 10
        mstore 160, 0
        stop
    """
    _check_no_change(pre)


def test_memzeroing_imposs_effect():
    """
    Test of memzeroing bariers caused
    by different effect
    """

    pre = """
    _global:
        mstore 32, 0
        dloadbytes 10, 20, 30  ; BARRIER
        mstore 64, 0
        stop
    """
    _check_no_change(pre)


def test_memzeroing_overlaping():
    """
    Test merging overlapping memzeroes (they can be merged
    since both result in zeroes being written to destination)
    """

    pre = """
    _global:
        mstore 32, 0
        mstore 96, 0
        mstore 32, 0
        mstore 64, 0
        stop
    """

    post = """
    _global:
        %1 = calldatasize
        calldatacopy 32, %1, 96
        stop
    """
    _check_pre_post(pre, post)


def test_memzeroing_interleaved():
    """
    Test merging overlapping memzeroes (they can be merged
    since both result in zeroes being written to destination)
    """

    pre = """
    _global:
        mstore 32, 0
        mstore 1000, 0
        mstore 64, 0
        mstore 1032, 0
        stop
    """

    post = """
    _global:
        %1 = calldatasize
        calldatacopy 32, %1, 64
        %2 = calldatasize
        calldatacopy 1000, %2, 64
        stop
    """
    _check_pre_post(pre, post)


def test_merge_mstore_dload():
    """
    Test for merging the mstore/dload pairs which contains
    variable which would normally trigger barrier
    """
    pre = """
    _global:
        %par = param
        %d = dload %par
        mstore 1000, 123
        mstore 1000, %d
        stop
    """

    post = """
    _global:
        %par = param
        mstore 1000, 123
        dloadbytes 1000, %par, 32
        stop
    """

    _check_pre_post(pre, post)


def test_merge_mstore_dload_more_uses():
    """
    Test for merging the mstore/dload pairs which contains
    variable which would normally trigger barrier.
    In this case, because %d is used by `sink`, we don't optimize
    the dload/mstore sequence into dloadbytes. (We could in the future
    as a further optimization, it requires insertion of an mload).
    """
    pre = """
    _global:
        %par = param
        %d = dload %par
        mstore 1000, %d
        sink %d
    """

    post = """
    _global:
        %par = param
        dloadbytes 1000, %par, 32
        %1 = mload 1000
        sink %1
    """

    _check_pre_post(pre, post)


def test_merge_mstore_dload_disallowed():
    """
    Test for merging the mstore/dload pairs which contains
    variable which would normally trigger barrier.
    In this case, because %d is used by `sink`, we don't optimize
    the dload/mstore sequence into dloadbytes. (We could in the future
    as a further optimization, it requires insertion of an mload).
    """
    pre = """
    _global:
        %par = param
        %d1 = dload %par
        mstore %d1, 1000
        mstore 1000, %d1
        %d2 = dload %par
        mstore %d2, %par
        mstore 1000, %d2
        sink %d1, %d2
    """

    _check_no_change(pre)
