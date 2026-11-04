from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import DFTPass

_check_pre_post = PrePostChecker([DFTPass])


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_dft():
    """
    Basic test for dft pass
    """
    pre = """
    main:
        %x = 1
        %y = 2
        return %x, %y
    """
    post = """
    main:
        %y = 2
        %x = 1
        return %x, %y
    """
    _check_pre_post(pre, post)


def test_dft_does_not_reorder_fmp_register_ops():
    """
    `setfmp` (an FMP register write) must not be reordered across `getfmp`
    reads (and vice versa); the FMP effect row creates the ordering edges.
    """
    pre = """
    main:
        %a = getfmp
        setfmp 128
        %b = getfmp
        sink %a, %b
    """
    _check_no_change(pre)


def test_dft_reorders_across_disjoint_store():
    """
    the load from [0, 32) does not alias the store to [32, 64), so the
    store is free to move across the load.
    """
    pre = """
    main:
        %x = mload 0
        mstore 32, 1
        %y = add %x, 1
        mstore 0, %y
        stop
    """
    post = """
    main:
        mstore 32, 1
        %x = mload 0
        %y = add %x, 1
        mstore 0, %y
        stop
    """
    _check_pre_post(pre, post)


def test_dft_keeps_order_across_aliasing_store():
    pre = """
    main:
        %x = mload 0
        mstore 0, 1
        %y = add %x, 1
        mstore 32, %y
        stop
    """
    _check_no_change(pre)


def _run_dft_and_get_eda(pre: str):
    """Parse `pre`, run DFT, return (dft_pass, original instructions of the
    entry block grouped by opcode, in BB order before DFT mutated them)."""
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    bb = fn.entry
    insts_by_opcode: dict[str, list] = {}
    for inst in bb.instructions:
        insts_by_opcode.setdefault(inst.opcode, []).append(inst)
    ac = IRAnalysesCache(fn)
    dft = DFTPass(ac, fn)
    dft.run_pass()
    return dft, insts_by_opcode


def test_dft_mem_ssa_disjoint_locs_drops_fence():
    """mload at offset 0 and mstore at offset 32 do not alias — DFT should
    not place either in the other's effect-dep set."""
    pre = """
    main:
        %x = mload 0
        mstore 32, 99
        return %x, %x
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mload_inst = insts["mload"][0]
    mstore_inst = insts["mstore"][0]

    assert mload_inst not in dft.eda[mstore_inst]
    assert mstore_inst not in dft.eda[mload_inst]


def test_dft_mem_ssa_same_loc_keeps_fence():
    """mload and mstore at the same offset must keep the effect-dep edge."""
    pre = """
    main:
        %x = mload 0
        mstore 0, 99
        return %x, %x
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mload_inst = insts["mload"][0]
    mstore_inst = insts["mstore"][0]

    assert mload_inst in dft.eda[mstore_inst]


def test_dft_mem_ssa_disjoint_stores_drop_fence():
    """Two mstores at disjoint offsets do not need a write-after-write fence."""
    pre = """
    main:
        mstore 0, 1
        mstore 32, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["mstore"]

    assert first not in dft.eda[second]


def test_dft_mem_ssa_overlapping_stores_keep_fence():
    """Two mstores at the same offset require a write-after-write fence."""
    pre = """
    main:
        mstore 0, 1
        mstore 0, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["mstore"]

    assert first in dft.eda[second]


def test_dft_mem_ssa_unknown_offset_is_conservative():
    """An mstore through a dynamic pointer that mem_ssa cannot pin to a
    fixed location must keep the fence against a prior mload."""
    pre = """
    main:
        %p = param
        %x = mload 0
        mstore %p, 99
        return %x, %x
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mload_inst = insts["mload"][0]
    mstore_inst = insts["mstore"][0]

    assert mload_inst in dft.eda[mstore_inst]


def test_dft_mem_ssa_skips_non_aliasing_earlier_write():
    """Three writes: W1 at 0, W2 at 32, W3 at 0. W3 must fence against W1
    (aliasing) but not against W2 (non-aliasing): a non-aliasing write in
    between must not hide the earlier aliasing one."""
    pre = """
    main:
        mstore 0, 1
        mstore 32, 2
        mstore 0, 3
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    w1, w2, w3 = insts["mstore"]

    assert w1 in dft.eda[w3]
    assert w2 not in dft.eda[w3]


def test_dft_storage_disjoint_slots_drop_fence():
    """Two sstores at distinct fixed slots do not need a write-after-write
    fence; STORAGE locations are tracked per slot."""
    pre = """
    main:
        sstore 0, 1
        sstore 1, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["sstore"]

    assert first not in dft.eda[second]


def test_dft_storage_same_slot_keeps_fence():
    pre = """
    main:
        sstore 0, 1
        sstore 0, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["sstore"]

    assert first in dft.eda[second]


def test_dft_storage_disjoint_sload_sstore_no_fence():
    pre = """
    main:
        %x = sload 0
        sstore 1, 99
        return %x, %x
    """
    dft, insts = _run_dft_and_get_eda(pre)
    sload_inst = insts["sload"][0]
    sstore_inst = insts["sstore"][0]

    assert sload_inst not in dft.eda[sstore_inst]


def test_dft_transient_disjoint_slots_drop_fence():
    pre = """
    main:
        tstore 0, 1
        tstore 1, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["tstore"]

    assert first not in dft.eda[second]


def test_dft_storage_independent_of_memory():
    """mstore and sstore touch different effect classes; there is no
    fence between them."""
    pre = """
    main:
        mstore 0, 1
        sstore 0, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mstore_inst = insts["mstore"][0]
    sstore_inst = insts["sstore"][0]

    assert mstore_inst not in dft.eda[sstore_inst]
    assert sstore_inst not in dft.eda[mstore_inst]


def test_dft_bump_reclaim_reuse_keeps_fence():
    # after FmpLoweringPass a reclaimed dynamic allocation is reused: the
    # second bump is based at the first allocation's mark, so %b == %a at
    # runtime. the store through %b must stay after the loads through %a.
    pre = """
    main:
        %fmp0 = initial_fmp
        %a, %fmp1 = bump 64, %fmp0
        mstore %a, 1
        %u = mload %a
        sstore 0, %u
        %v = mload %a
        %b, %fmp2 = bump 64, %a
        mstore %b, 2
        sink %v
    """
    dft, insts = _run_dft_and_get_eda(pre)
    store_b = insts["mstore"][1]
    load_u, load_v = insts["mload"]
    assert load_u in dft.eda[store_b]
    assert load_v in dft.eda[store_b]


def test_dft_call_buffers():
    pre = """
    main:
        %g = param
        %addr = param
        mstore 64, 5
        %x = mload 0
        %ok = call %g, %addr, 0, 64, 36, 96, 40
        %y = mload 96
        mstore 64, 7
        sink %x, %y, %ok
    """
    dft, insts = _run_dft_and_get_eda(pre)
    call = insts["call"][0]
    store_args, store_after = insts["mstore"]
    load_0, load_ret = insts["mload"]
    assert store_args in dft.eda[call]  # args buffer written before the call
    assert load_0 not in dft.eda[call]  # [0, 32) is neither read nor written
    assert call in dft.eda[load_ret]  # return buffer read after the call
    assert call in dft.eda[store_after]  # args buffer not overwritten before the call


def test_dft_mcopy_variable_size():
    pre = """
    main:
        %n = param
        mstore 32, 1
        mcopy 64, 0, %n
        mstore 0, 9
        sink %n
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mcopy = insts["mcopy"][0]
    store_32, store_0 = insts["mstore"]
    assert store_32 in dft.eda[mcopy]  # unknown-size source may read [32, 64)
    assert mcopy in dft.eda[store_0]  # source read before overwrite


def test_dft_overlapping_stores_keep_fence():
    pre = """
    main:
        mstore 0, 1
        mstore 16, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["mstore"]
    assert first in dft.eda[second]


def test_dft_invoke_fences_everything():
    pre = """
    main:
        mstore 0, 1
        sstore 0, 1
        invoke @f
        %q = mload 32
        %s = sload 5
        sink %q, %s
    """
    dft, insts = _run_dft_and_get_eda(pre)
    invoke = insts["invoke"][0]
    assert insts["mstore"][0] in dft.eda[invoke]
    assert insts["sstore"][0] in dft.eda[invoke]
    assert invoke in dft.eda[insts["mload"][0]]
    assert invoke in dft.eda[insts["sload"][0]]


def test_dft_terminator_and_log_reads():
    pre = """
    main:
        mstore 0, 1
        mstore 64, 2
        %h = sha3 0, 32
        log 64, 32, %h
        return 64, 32
    """
    dft, insts = _run_dft_and_get_eda(pre)
    store_0, store_64 = insts["mstore"]
    assert list(dft.eda[insts["sha3"][0]]) == [store_0]
    assert list(dft.eda[insts["log"][0]]) == [store_64]
    assert list(dft.eda[insts["return"][0]]) == [store_64]


def test_dft_iload_is_conservative():
    pre = """
    main:
        mstore 64, 3
        %v = iload 0
        sink %v
    """
    dft, insts = _run_dft_and_get_eda(pre)
    assert insts["mstore"][0] in dft.eda[insts["iload"][0]]


def test_dft_call_clobbers_storage():
    pre = """
    main:
        %g = param
        %addr = param
        %x = sload 0
        %ok = call %g, %addr, 0, 64, 36, 96, 40
        sstore 1, %x
        sink %ok
    """
    dft, insts = _run_dft_and_get_eda(pre)
    call = insts["call"][0]
    assert insts["sload"][0] in dft.eda[call]
    assert call in dft.eda[insts["sstore"][0]]
