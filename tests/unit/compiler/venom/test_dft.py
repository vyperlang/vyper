import pytest

from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.assembler.core import assembly_to_evm
from vyper.evm.opcodes import version_check
from vyper.venom import run_passes_on
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import DFTPass
from vyper.venom.venom_to_assembly import VenomCompiler

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


def test_dft_alias_analysis_disjoint_locs_drops_fence():
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


def test_dft_alias_analysis_same_loc_keeps_fence():
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


def test_dft_alias_analysis_disjoint_stores_drop_fence():
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


def test_dft_alias_analysis_overlapping_stores_keep_fence():
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


def test_dft_alias_analysis_unknown_offset_is_conservative():
    """An mstore through a dynamic pointer that alias analysis cannot pin to a
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


def test_dft_unknown_offset_write_keeps_other_allocation_reads():
    """A write at an unknown offset into one allocation does not alias reads
    of another allocation, so it must not hide them from a later write to
    that allocation."""
    pre = """
    main:
        %dyn = param
        %a = alloca 64
        %b = alloca 32
        %p = add %a, %dyn
        %x = mload %b
        mstore %p, 1
        mstore %b, 2
        sink %x
    """
    dft, insts = _run_dft_and_get_eda(pre)
    load_b = insts["mload"][0]
    store_p, store_b = insts["mstore"]

    assert load_b not in dft.eda[store_p]
    assert load_b in dft.eda[store_b]


def test_dft_alias_analysis_skips_non_aliasing_earlier_write():
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


@pytest.mark.parametrize("level", [OptimizationLevel.O1, OptimizationLevel.O2])
@pytest.mark.parametrize("prefix", ["s", "t"])
@pytest.mark.parametrize("signed_slot", [-1, -(2**255)])
def test_dft_equivalent_storage_slots_execute_in_order(env, level, prefix, signed_slot):
    if prefix == "t" and not version_check(begin="cancun"):
        pytest.skip("Transient storage requires Cancun")

    # Run the full pipeline, including SingleUseExpansion before DFT. Both
    # representations address the same EVM slot, so the load must see zero.
    ctx = parse_from_basic_block(f"""
    main:
        %slot = {signed_slot}
        %alias = %slot
        %value = {prefix}load %alias
        {prefix}store {signed_slot + 2**256}, 9
        %output = alloca 32
        mstore %output, %value
        return %output, 32
    """)
    run_passes_on(ctx, VenomOptimizationFlags(level=level))
    bytecode, _ = assembly_to_evm(VenomCompiler(ctx).generate_evm_assembly())
    initcode = bytes.fromhex(f"61{len(bytecode):04x}3d81600a3d39f3") + bytecode
    contract = env.deploy([], initcode)

    assert env.message_call(contract.address) == bytes(32)


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


def test_dft_does_not_hoist_assert_above_invoke():
    """
    An `assert` must not move above an earlier `invoke`: if both fail,
    the callee's revert (with its revert data) must win.
    """
    pre = """
    main:
        invoke @f
        %x = calldataload 0
        %y = add %x, 1
        %c = gt %x, %y
        %ok = iszero %c
        assert %ok
        mstore 0, %y
        return 0, 32
    """
    _check_no_change(pre)


def test_dft_does_not_hoist_assert_above_returndatacopy():
    """
    `returndatacopy` aborts with an exceptional halt and `assert` with a
    revert, so an `assert` must not move above an earlier `returndatacopy`.
    """
    pre = """
    main:
        returndatacopy 64, 0, 32
        %x = calldataload 0
        %ok = iszero %x
        assert %ok
        %y = mload 64
        mstore 32, %y
        return 32, 32
    """
    _check_no_change(pre)


def test_dft_computes_assert_condition_after_earlier_invoke():
    """
    Each `assert` stays after the `invoke` before it, and its condition is
    computed next to it rather than up front, where it would stay on the
    stack across every call.
    """
    pre = """
    main:
        invoke @f
        %x = calldataload 0
        %c1 = iszero %x
        assert %c1
        invoke @f
        %c2 = iszero %x
        assert %c2
        mstore 0, %x
        return 0, 32
    """
    _check_no_change(pre)


def test_dft_long_chain_of_aborts():
    # each `assert` is ordered after the `invoke` before it, so the chain of
    # dependencies is as long as the block
    n = 2000
    body = "".join(
        f"%c{i} = iszero %x\n        assert %c{i}\n        invoke @f\n        " for i in range(n)
    )
    pre = f"""
    main:
        invoke @f
        %x = calldataload 0
        {body}return 0, 32
    """
    _check_no_change(pre)
