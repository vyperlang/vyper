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


def _run_dft_and_get_eda(pre: str):
    """Parse `pre`, run DFT, return (dft_pass, list of original instructions in
    BB order before DFT mutated them)."""
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

    assert mload_inst not in dft.eda.get(mstore_inst, set())
    assert mstore_inst not in dft.eda.get(mload_inst, set())


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

    assert first not in dft.eda.get(second, set())


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
    """Three writes: W1 at 0, W2 at 32, W3 at 0. W3 should fence against W1
    (aliasing) but not against W2 (non-aliasing). This case exercises why
    the single-slot last_write_effects shape is unsafe with alias filtering
    — naively keeping only the most-recent write would lose W1."""
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
    assert w2 not in dft.eda.get(w3, set())


def test_dft_storage_disjoint_slots_drop_fence():
    """Two sstores at distinct fixed slots do not need a write-after-write
    fence — STORAGE locations are tracked per-slot via mem_ssa."""
    pre = """
    main:
        sstore 0, 1
        sstore 1, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["sstore"]

    assert first not in dft.eda.get(second, set())


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

    assert sload_inst not in dft.eda.get(sstore_inst, set())


def test_dft_transient_disjoint_slots_drop_fence():
    pre = """
    main:
        tstore 0, 1
        tstore 1, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    first, second = insts["tstore"]

    assert first not in dft.eda.get(second, set())


def test_dft_storage_independent_of_memory():
    """mstore and sstore touch different effect classes — there has never
    been a fence between them. Sanity-check that the new path doesn't
    accidentally cross-couple them."""
    pre = """
    main:
        mstore 0, 1
        sstore 0, 2
        stop
    """
    dft, insts = _run_dft_and_get_eda(pre)
    mstore_inst = insts["mstore"][0]
    sstore_inst = insts["sstore"][0]

    assert mstore_inst not in dft.eda.get(sstore_inst, set())
    assert sstore_inst not in dft.eda.get(mstore_inst, set())
