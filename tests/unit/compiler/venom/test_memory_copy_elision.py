from tests.venom_utils import PrePostChecker
from vyper.evm.address_space import MEMORY
from vyper.evm.opcodes import version_check
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes import (
    DeadStoreElimination,
    MemoryCopyElisionPass,
    RemoveUnusedVariablesPass,
)

_checker = PrePostChecker([MemoryCopyElisionPass], default_hevm=False)


def _check_pre_post(pre, post, hevm: bool = True):
    pre_ctx, post_ctx = _checker.run_passes(pre, post)
    for fn in pre_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        DeadStoreElimination(ac, fn).run_pass(addr_space=MEMORY)

    _checker.check(pre_ctx, post_ctx, pre, post, hevm)


def _check_pre_post_with_unused_var_removal(pre, post, hevm: bool = True):
    """Like _check_pre_post but also runs RemoveUnusedVariablesPass.

    This is needed for tests involving load-store elision where the load
    becomes unused after the store is nop'd. RemoveUnusedVariablesPass
    has proper MSIZE fence handling to preserve loads that affect msize.
    """
    pre_ctx, post_ctx = _checker.run_passes(pre, post)
    for fn in pre_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        DeadStoreElimination(ac, fn).run_pass(addr_space=MEMORY)
        RemoveUnusedVariablesPass(ac, fn).run_pass()

    _checker.check(pre_ctx, post_ctx, pre, post, hevm)


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_load_store_no_elision():
    """Basic load-store test.

    Single-word copies are already optimal, but the store must be observable
    (otherwise this pass will remove it as an unused write).
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 200, %1
        %2 = mload 200
        sink %2
    """
    _check_no_change(pre)


def test_redundant_copy_elimination():
    """
    Test that copying to the same location is eliminated entirely.

    MemoryCopyElisionPass only nops the store. The load is removed by
    RemoveUnusedVariablesPass (which has proper MSIZE fence handling).
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 100, %1
        stop
    """

    # After MemoryCopyElisionPass: store is nop'd, load remains
    # After RemoveUnusedVariablesPass: load is also removed (no msize downstream), nops cleared
    post = """
    _global:
        stop
    """
    _check_pre_post_with_unused_var_removal(pre, post)


def test_mcopy_chain_optimization():
    """
    Test that mcopy chains are optimized.
    A->B followed by B->C should become A->C.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        mcopy 300, 200, 32
        %1 = mload 300
        sink %1
    """

    post = """
    _global:
        nop  ; mcopy 200, 100, 32              [memory copy elision - merged mcopy]
        mcopy 300, 100, 32
        %1 = mload 300
        sink %1
    """
    _check_pre_post(pre, post)


def test_mcopy_redundant_elimination():
    """
    Test that mcopy with same src and dst is eliminated.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 100, 100, 32
        stop
    """

    post = """
    _global:
        nop  ; mcopy 100, 100, 32              [memory copy elision - redundant mcopy]
        stop
    """
    _check_pre_post(pre, post)


def test_no_elision_with_intermediate_write():
    """
    Test that copy elision doesn't happen if there's an intermediate write
    to the source location.
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 100, 42  ; BARRIER - writes to source
        mstore 200, %1
        %2 = mload 100
        %3 = mload 200
        sink %3, %2
    """
    _check_no_change(pre)


def test_no_elision_with_multiple_uses():
    """
    Test that copy elision doesn't happen if the loaded value has multiple uses.
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 200, %1
        %2 = add %1, 1  ; Another use of %1
        %3 = mload 200
        sink %3
    """
    _check_no_change(pre)


def test_mcopy_chain_with_intermediate_read():
    """
    Test that mcopy chain optimization doesn't happen with intermediate reads
    from the intermediate location.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        %1 = mload 200  ; BARRIER - read from intermediate location
        mcopy 300, 200, 32
        mstore 400, %1
        %2 = mload 300
        %3 = mload 400
        sink %3, %2
    """

    post = """
    _global:
        mcopy 200, 100, 32
        %1 = mload 200  ; BARRIER - read from intermediate location
        mcopy 300, 100, 32 ; but this can be still changed
        mstore 400, %1
        %2 = mload 300
        %3 = mload 400
        sink %3, %2
    """

    _check_pre_post(pre, post)


def test_mcopy_chain_with_size_mismatch():
    """
    Test that mcopy chains with different sizes are not merged.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        mcopy 300, 200, 64  ; Different size
        %1 = mload 300
        sink %3
    """
    _check_no_change(pre)


def test_mcopy_chain_with_variable_size():
    """
    Test mcopy chains with variable sizes - currently not optimized.

    When mcopy uses variable sizes, the memory location can't be tracked
    precisely (is_fixed returns False), so no chain optimization happens.
    This test documents the current behavior.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %sz = 32
        mcopy 200, 100, %sz
        mcopy 300, 200, %sz
        %1 = mload 300
        sink %1
    """
    # No optimization - variable size locations aren't tracked
    _check_no_change(pre)


def test_overlapping_memory_regions():
    """
    Test that overlapping memory regions prevent optimization.
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 116, 42  ; BARRIER - overlaps with source [100-131]
        mstore 200, %1
        %2 = mload 116
        %3 = mload 200
        sink %3, %2
    """
    _check_no_change(pre)


def test_call_instruction_clears_optimization():
    """
    Test that call instructions clear all tracked optimizations.
    """
    pre = """
    _global:
        %1 = mload 100
        %2 = call 0, 0, 0, 0, 0, 0, 0  ; BARRIER - can modify any memory
        mstore 200, %1
        %3 = mload 200
        sink %3
    """
    _check_no_change(pre)


def test_multiple_load_store_pairs():
    """
    Test that multiple independent load-store pairs are not changed.
    Single word copies are already optimal.
    """
    pre = """
    _global:
        %1 = mload 100
        %2 = mload 200
        mstore 300, %1
        mstore 400, %2
        %3 = mload 300
        %4 = mload 400
        sink %4, %3
    """
    _check_no_change(pre)


def test_sha3_does_not_break_copy_chain():
    """
    Test that sha3 (which only READS memory) doesn't break copy chain optimization.
    sha3 reads memory but doesn't write to it, so tracked copies remain valid.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        %hash = sha3 100, 32  ; Reads memory, but doesn't write to it
        mcopy 200, 100, 32    ; Should still optimize!
        %1 = mload 200
        sink %hash, %1
    """

    # mcopy is transformed to calldatacopy. The first calldatacopy is NOT
    # nop'd because sha3 reads from it (so it's not dead).
    post = """
    _global:
        calldatacopy 100, 0, 32
        %hash = sha3 100, 32
        calldatacopy 200, 0, 32
        %1 = mload 200
        sink %hash, %1
    """
    _check_pre_post(pre, post)


def test_mcopy_chain_longer():
    """
    Test longer mcopy chains: A->B->C->D should become A->D.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        mcopy 300, 200, 32
        mcopy 400, 300, 32
        %1 = mload 400
        sink %1
    """

    post = """
    _global:
        nop  ; mcopy 200, 100, 32              [memory copy elision - merged mcopy]
        nop  ; mcopy 300, 200, 32              [memory copy elision - merged mcopy]
        mcopy 400, 100, 32
        %1 = mload 400
        sink %1
    """
    _check_pre_post(pre, post)


def test_calldatacopy_barrier():
    """Test that calldatacopy acts as a barrier for optimizations.

    Also ensure the mstore is observable (otherwise this pass may remove it
    as an unnecessary effect).
    """
    pre = """
    _global:
        %1 = mload 100
        calldatacopy 200, 0, 32  ; BARRIER - writes to memory
        mstore 300, %1
        %2 = mload 200
        %3 = mload 300
        sink %3, %2
    """
    _check_no_change(pre)


def test_dloadbytes_barrier():
    """
    Test that dloadbytes acts as a barrier for optimizations.
    """
    pre = """
    _global:
        %1 = mload 100
        dloadbytes 200, 0, 32  ; BARRIER - writes to memory
        mstore 300, %1
        %2 = mload 200
        %3 = mload 300
        sink %3, %2
    """
    _check_no_change(pre)


def test_calldatacopy_mcopy_chain():
    """
    Test that calldatacopy followed by mcopy can be optimized.
    calldatacopy -> A, mcopy A -> B should become calldatacopy -> B.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Copy 32 bytes from calldata offset 0 to memory 100
        mcopy 200, 100, 32       ; Copy from 100 to 200
        %1 = mload 200
        sink %1
    """

    post = """
    _global:
        nop  ; calldatacopy 100, 0, 32         [memory copy elision - merged calldatacopy]
        calldatacopy 200, 0, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_codecopy_mcopy_chain():
    """
    Test that codecopy followed by mcopy can be optimized.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        codecopy 100, 10, 64    ; Copy 64 bytes from code offset 10 to memory 100
        mcopy 300, 100, 64      ; Copy from 100 to 300
        %1 = mload 300
        sink %1
    """

    post = """
    _global:
        nop  ; codecopy 100, 10, 64            [memory copy elision - merged codecopy]
        codecopy 300, 10, 64
        %1 = mload 300
        sink %1
    """
    _check_pre_post(pre, post)


def test_dloadbytes_mcopy_chain():
    """
    Test that dloadbytes followed by mcopy can be optimized.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        dloadbytes 100, 0, 32   ; Load 32 bytes from transient offset 0 to memory 100
        mcopy 200, 100, 32      ; Copy from 100 to 200
        %1 = mload 200
        sink %1
    """

    post = """
    _global:
        nop  ; dloadbytes 100, 0, 32           [memory copy elision - merged dloadbytes]
        dloadbytes 200, 0, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_special_copy_mcopy_chain_with_read():
    """
    Test that special copy + mcopy chain is NOT totally removed if intermediate location is read
    but it can be bit optimized.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Copy to intermediate location so it cannot be removed
        %1 = mload 100           ; Read from intermediate location - BARRIER
        mcopy 200, 100, 32
        mstore 300, %1
        %1 = mload 300
        %2 = mload 200
        sink %2, %1
    """

    post = """
    _global:
        calldatacopy 100, 0, 32  ; Copy to intermediate location
        %1 = mload 100           ; Read from intermediate location - BARRIER
        calldatacopy 200, 0, 32  ; can be transformed into calldatacopy
        mstore 300, %1
        %1 = mload 300
        %2 = mload 200
        sink %2, %1
    """
    _check_pre_post(pre, post)


def test_special_copy_mcopy_chain_size_mismatch():
    """
    Test that special copy + mcopy chain with different sizes are not merged.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Copy 32 bytes
        mcopy 200, 100, 64       ; Try to copy 64 bytes - size mismatch
        %1 = mload 200
        sink %1
    """
    _check_no_change(pre)


def test_special_copy_multiple_mcopy_chain():
    """
    Test that special copy followed by multiple mcopies can be optimized.
    calldatacopy -> A, mcopy A -> B, mcopy B -> C should become calldatacopy -> C.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Copy from calldata to 100
        mcopy 200, 100, 32       ; Copy from 100 to 200
        mcopy 300, 200, 32       ; Copy from 200 to 300
        %1 = mload 300
        sink %1
    """

    post = """
    _global:
        nop  ; calldatacopy 100, 0, 32         [memory copy elision - merged calldatacopy]
        nop  ; mcopy 200, 100, 32              [memory copy elision - merged mcopy]
        calldatacopy 300, 0, 32
        %1 = mload 300
        sink %1
    """
    _check_pre_post(pre, post)


def test_inter_block_no_optimization():
    """
    Test that optimizations don't cross basic block boundaries.
    Load and store in different blocks should not be optimized.
    """
    pre = """
    _global:
        %1 = mload 100
        jmp @label1

    label1:
        mstore 100, %1     ; Even though this is redundant, it's in a different block
        %2 = mload 100
        sink %2
    """

    # No optimization should happen - load and store are in different blocks
    post = pre

    _check_pre_post(pre, post)


def test_mcopy_chain_across_blocks():
    """
    Test that mcopy chains DO merge across basic block boundaries.

    Cross-BB copy elision propagates copy info along CFG edges, allowing
    the second mcopy to be transformed to copy directly from the original source.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        jmp @label1

    label1:
        mcopy 300, 200, 32
        %1 = mload 300
        sink %1
    """

    # Cross-BB optimization: second mcopy reads from 200, which was
    # written by first mcopy from 100. Chain is merged.
    post = """
    _global:
        nop  ; mcopy 200, 100, 32             [dead store - 200 not read]
        jmp @label1

    label1:
        mcopy 300, 100, 32
        %1 = mload 300
        sink %1
    """

    _check_pre_post(pre, post)


def test_special_copy_chain_across_blocks():
    """
    Test that special copy + mcopy chains DO merge across basic block boundaries.

    Cross-BB copy elision propagates copy info along CFG edges, allowing
    the mcopy to be transformed to a calldatacopy directly from calldata.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        jmp @label1

    label1:
        mcopy 200, 100, 32
        %1 = mload 200
        sink %1
    """

    # Cross-BB optimization: mcopy reads from 100, which was written by
    # calldatacopy. Chain is merged to calldatacopy directly to 200.
    post = """
    _global:
        nop  ; calldatacopy 100, 0, 32        [dead store - 100 not read]
        jmp @label1

    label1:
        calldatacopy 200, 0, 32
        %1 = mload 200
        sink %1
    """

    _check_pre_post(pre, post)


def test_conditional_branch_no_optimization():
    """
    Test that optimizations are conservative with conditional branches.
    """
    pre = """
    _global:
        %1 = mload 100
        %2 = iszero %1
        jnz %2, @label1, @label2

    label1:
        mstore 100, %1    ; Can't optimize - control flow dependent
        %1 = mload 100
        sink %1

    label2:
        mstore 200, %1    ; Can't optimize - control flow dependent
        %2 = mload 200
        sink %2
    """

    # No optimization should happen
    post = pre

    _check_pre_post(pre, post)


def test_special_copy_not_merged_with_hazard():
    """Test that special copy + mcopy chain is not merged when there's a hazard."""
    pre = """
    _global:
        calldatacopy 100, 200, 32
        %1 = mload 100
        add %1, 1
        mstore 100, %1
        mcopy 200, 100, 32
        %2 = mload 200
        sink %2
    """

    post = pre  # No change - hazard prevents optimization

    _check_pre_post(pre, post)


def test_mem_elision_load_needed():
    pre = """
    main:
        ; cannot remove this copy since
        ; the mload uses this data
        calldatacopy 100, 200, 64
        mcopy 300, 100, 64
        %1 = mload 100
        %2 = mload 300
        sink %2, %1
    """

    post = """
    main:
        calldatacopy 100, 200, 64
        calldatacopy 300, 200, 64
        %1 = mload 100
        %2 = mload 300
        sink %2, %1
    """

    _check_pre_post(pre, post)


def test_mem_elision_load_needed_not_precise():
    pre = """
    main:
        ; cannot remove this copy since
        ; the mload uses this data
        calldatacopy 100, 200, 64
        mcopy 300, 100, 64
        %1 = mload 132
        %2 = mload 332
        sink %2, %1
    """

    post = """
    main:
        calldatacopy 100, 200, 64
        calldatacopy 300, 200, 64
        %1 = mload 132
        %2 = mload 332
        sink %2, %1
    """

    _check_pre_post(pre, post)


def test_mem_elision_msize():
    """
    Test that mload is preserved when msize is read downstream.

    MemoryCopyElisionPass only nops the store. RemoveUnusedVariablesPass
    would normally remove the unused load, but it correctly preserves it
    because there's an msize instruction downstream (msize fence).
    """
    pre = """
    main:
        ; you cannot nop both of
        ; them since you need correct
        ; msize (currently it does that)
        %1 = mload 100
        mstore 100, %1
        %2 = msize
        sink %2
    """

    # After MemoryCopyElisionPass: store is nop'd
    # After RemoveUnusedVariablesPass: load is KEPT (msize fence), nops cleared
    post = """
    main:
        %1 = mload 100
        %2 = msize
        sink %2
    """
    _check_pre_post_with_unused_var_removal(pre, post)


def test_remove_unused_writes():
    pre = """
    main:
        %par = param
        mstore 100, %par
        mstore 300, %par
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        stop
        ;%1 = mload 100
        ;sink %1
    else:
        stop
        ;%2 = mload 200
        ;sink %2
    """

    post = """
    main:
        %par = param
        nop
        nop
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        stop
    else:
        stop
    """

    _check_pre_post(pre, post)


def test_remove_unused_writes_with_read():
    pre = """
    main:
        %par = param
        mstore 100, %par
        mstore 300, %par
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload 100
        sink %1
    else:
        %2 = mload 100
        sink %2
    """

    post = """
    main:
        %par = param
        mstore 100, %par
        nop
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload 100
        sink %1
    else:
        %2 = mload 100
        sink %2
    """

    _check_pre_post(pre, post)


def test_remove_unused_writes_with_read_loop():
    pre = """
    main:
        %par = param
        mstore 100, %par
        mstore 300, %par
        jmp @cond
    cond:
        %cond = iszero %par
        jnz %cond, @body, @after
    body:
        %1 = mload 100
        jmp @cond
    after:
        %2 = mload 100
        sink %2
    """

    post = """
    main:
        %par = param
        mstore 100, %par
        nop
        jmp @cond
    cond:
        %cond = iszero %par
        jnz %cond, @body, @after
    body:
        %1 = mload 100
        jmp @cond
    after:
        %2 = mload 100
        sink %2
    """

    _check_pre_post(pre, post)


# ============================================================================
# Alloca-relative memory tests
# These test proper handling of alloca-based memory locations
# ============================================================================


def test_mcopy_chain_with_allocas():
    """Chain merging should work correctly with allocas.

    A->B->C chain: second mcopy is updated to copy from A directly,
    making the first mcopy dead (B is no longer read).

    Text format: mcopy dst, src, size
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %a1 = alloca 64
        %a2 = alloca 64
        %a3 = alloca 64
        mcopy %a2, %a1, 64
        mcopy %a3, %a2, 64
        %1 = mload %a3
        sink %1
    """
    # Chain merging: second mcopy reads from %a1 directly
    # Dead store elimination: first mcopy is dead since %a2 is never read
    post = """
    _global:
        %a1 = alloca 64
        %a2 = alloca 64
        %a3 = alloca 64
        nop
        mcopy %a3, %a1, 64
        %1 = mload %a3
        sink %1
    """
    _check_pre_post(pre, post)


def test_different_allocas_not_redundant():
    """Different allocas at offset 0 are NOT the same location.

    Two different allocas pointing to offset 0 within their respective
    allocations are distinct memory regions - copying between them
    is not redundant.

    Text format: mcopy dst, src, size
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %a1 = alloca 64
        %a2 = alloca 64
        mcopy %a2, %a1, 64
        %1 = mload %a2
        sink %1
    """
    _check_no_change(pre)


def test_same_alloca_redundant():
    """Copy from alloca to itself IS redundant.

    Text format: mcopy dst, src, size
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %a1 = alloca 64
        mcopy %a1, %a1, 64
        stop
    """
    post = """
    _global:
        %a1 = alloca 64
        nop
        stop
    """
    _check_pre_post(pre, post)


def test_calldatacopy_mcopy_chain_with_alloca():
    """Special copy chain with alloca destination.

    calldatacopy -> alloca A, mcopy A -> alloca B: mcopy is converted to
    calldatacopy directly to B, making the first calldatacopy dead.

    Text format: mcopy dst, src, size
    Text format: calldatacopy dst, src_offset, size
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %a1 = alloca 64
        %a2 = alloca 64
        calldatacopy %a1, 0, 64
        mcopy %a2, %a1, 64
        %1 = mload %a2
        sink %1
    """
    # Chain merging: mcopy becomes calldatacopy to %a2
    # Dead store elimination: first calldatacopy is dead since %a1 is never read
    post = """
    _global:
        %a1 = alloca 64
        %a2 = alloca 64
        nop
        calldatacopy %a2, 0, 64
        %1 = mload %a2
        sink %1
    """
    _check_pre_post(pre, post)


# ============================================================================
# Cross-BB copy elision tests
# These test the dataflow-based cross-BB optimization
# ============================================================================


def test_cross_bb_copy_chain_multiple_blocks():
    """
    Test copy chain optimization across multiple basic blocks.
    A -> B in block1, B -> C in block2, C -> D in block3.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        jmp @block2

    block2:
        mcopy 300, 200, 32
        jmp @block3

    block3:
        mcopy 400, 300, 32
        %1 = mload 400
        sink %1
    """

    # All intermediate copies can be eliminated, final copies directly from 100
    post = """
    _global:
        nop  ; mcopy 200, 100, 32             [dead store]
        jmp @block2

    block2:
        nop  ; mcopy 300, 200, 32             [dead store]
        jmp @block3

    block3:
        mcopy 400, 100, 32
        %1 = mload 400
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_with_source_clobber():
    """
    Test that cross-BB optimization correctly handles clobbering writes.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        jmp @block2

    block2:
        mstore 100, 42  ; Clobber source location
        mcopy 300, 200, 32  ; Should NOT chain because source was modified
        %1 = mload 300
        %2 = mload 100
        sink %2, %1
    """

    # No chain optimization - source location was clobbered
    # But the mcopy 200, 100 is dead (200 is only read after clobber but that's okay
    # since we read from 200, not 100)
    post = """
    _global:
        mcopy 200, 100, 32
        jmp @block2

    block2:
        mstore 100, 42
        mcopy 300, 200, 32
        %1 = mload 300
        %2 = mload 100
        sink %2, %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_diamond_merge():
    """
    Test that cross-BB optimization is conservative at merge points.

    If copy info comes from different paths, only common info is kept.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        calldatacopy 100, 0, 32  ; Copy from calldata offset 0
        jmp @merge

    path2:
        calldatacopy 100, 32, 32  ; Copy from calldata offset 32 (different!)
        jmp @merge

    merge:
        mcopy 200, 100, 32  ; Can't optimize - different sources on each path
        %1 = mload 200
        sink %1
    """
    _check_no_change(pre)


def test_cross_bb_copy_diamond_same_source():
    """
    Test that cross-BB optimization works at merge points with same source.

    If the same copy exists on all paths to a merge point, it can be used.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Same copy before branch
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        %1 = add 1, 2  ; Some work, but no memory clobber
        jmp @merge

    path2:
        %2 = sub 5, 3  ; Some work, but no memory clobber
        jmp @merge

    merge:
        mcopy 200, 100, 32  ; CAN optimize - same source on all paths
        %3 = mload 200
        sink %3
    """

    post = """
    _global:
        nop  ; calldatacopy 100, 0, 32        [dead store]
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        %1 = add 1, 2
        jmp @merge

    path2:
        %2 = sub 5, 3
        jmp @merge

    merge:
        calldatacopy 200, 0, 32
        %3 = mload 200
        sink %3
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_diamond_identical_copies():
    """
    Test diamond CFG where both paths have identical copy instructions.

    Both paths write to the same location from the same source, so we can
    safely optimize the mcopy at the merge point to use the original source.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        calldatacopy 100, 0, 32  ; Copy from calldata offset 0
        jmp @merge

    path2:
        calldatacopy 100, 0, 32  ; SAME source (calldata offset 0)
        jmp @merge

    merge:
        mcopy 200, 100, 32  ; CAN optimize - both paths have equivalent copies
        %1 = mload 200
        sink %1
    """

    # Both calldatacopies are equivalent, so mcopy can chain through
    post = """
    _global:
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        nop  ; calldatacopy 100, 0, 32        [dead store]
        jmp @merge

    path2:
        nop  ; calldatacopy 100, 0, 32        [dead store]
        jmp @merge

    merge:
        calldatacopy 200, 0, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_diamond_equivalent_operands():
    """
    Test that diamond CFG with copies that have equivalent operands
    (via assign chains) DOES optimize.

    are_equivalent handles assign chains, so %x = 0 and %y = 0 are equivalent.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        %x = 0
        calldatacopy 100, %x, 32
        jmp @merge

    path2:
        %y = 0  ; Different variable, but equivalent via assign chain
        calldatacopy 100, %y, 32
        jmp @merge

    merge:
        mcopy 200, 100, 32  ; CAN optimize - operands are equivalent
        %1 = mload 200
        sink %1
    """

    # Optimization happens - operands are equivalent via assign chains
    post = """
    _global:
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        %x = 0
        nop  ; calldatacopy 100, %x, 32
        jmp @merge

    path2:
        %y = 0
        nop  ; calldatacopy 100, %y, 32
        jmp @merge

    merge:
        calldatacopy 200, 0, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_loop():
    """
    Test that copy info doesn't incorrectly persist through loops.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        %zero = 0
        jmp @loop

    loop:
        %i = phi @_global, %zero, @body, %i2
        %cond = lt %i, 10
        jnz %cond, @body, @exit

    body:
        mcopy 200, 100, 32  ; Can optimize on first iteration
        mstore 100, 42  ; Clobber source for next iteration
        %i2 = add %i, 1
        jmp @loop

    exit:
        %1 = mload 200
        sink %1
    """

    # This is a complex case. The calldatacopy provides info on first loop entry,
    # but after the mstore clobbers it. The worklist will stabilize with
    # no copy info available at the loop header (since one predecessor has it clobbered).
    # So the mcopy cannot be optimized.
    _check_no_change(pre)


def test_cross_bb_diamond_clobber_one_path():
    """
    Test that clobbering on one path of a diamond correctly invalidates at merge.

    Even if the copy dominates the branch, if one path clobbers the source,
    the copy info should not be available at the merge point.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        %cond = param
        jnz %cond, @path1, @path2

    path1:
        mstore 100, 42  ; Clobber the destination on this path
        jmp @merge

    path2:
        ; No clobber here
        jmp @merge

    merge:
        mcopy 200, 100, 32  ; Cannot optimize - clobbered on one path
        %1 = mload 200
        sink %1
    """
    _check_no_change(pre)


def test_cross_bb_volatile_clears_copies():
    """
    Test that volatile instructions clear copy info across blocks.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        jmp @block2

    block2:
        %ret = call 0, 0, 0, 0, 0, 0, 0  ; Volatile - clears memory
        mcopy 200, 100, 32  ; Can't optimize - call may have modified memory
        %1 = mload 200
        sink %1
    """
    _check_no_change(pre)


def test_cross_bb_calldatacopy_chain():
    """
    Test calldatacopy chains across blocks.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 64
        jmp @block2

    block2:
        mcopy 200, 100, 64
        jmp @block3

    block3:
        mcopy 300, 200, 64
        %1 = mload 300
        sink %1
    """

    post = """
    _global:
        nop  ; calldatacopy 100, 0, 64        [dead store]
        jmp @block2

    block2:
        nop  ; mcopy 200, 100, 64             [dead store]
        jmp @block3

    block3:
        calldatacopy 300, 0, 64
        %1 = mload 300
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_with_intermediate_read():
    """
    Test that cross-BB optimization preserves intermediate reads correctly.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32
        jmp @block2

    block2:
        %1 = mload 100  ; Read from intermediate location
        mcopy 200, 100, 32  ; Can still optimize
        mstore 300, %1
        %2 = mload 200
        %3 = mload 300
        sink %3, %2
    """

    # The calldatacopy is NOT dead because %1 reads from 100
    # But mcopy can still be optimized to calldatacopy
    post = """
    _global:
        calldatacopy 100, 0, 32
        jmp @block2

    block2:
        %1 = mload 100
        calldatacopy 200, 0, 32
        mstore 300, %1
        %2 = mload 200
        %3 = mload 300
        sink %3, %2
    """
    _check_pre_post(pre, post)


# ============================================================================
# Stress tests and edge cases
# ============================================================================


def test_many_copies_in_sequence():
    """
    Test handling of many sequential copies (stress test for tracking).
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        mcopy 300, 200, 32
        mcopy 400, 300, 32
        mcopy 500, 400, 32
        mcopy 600, 500, 32
        mcopy 700, 600, 32
        mcopy 800, 700, 32
        mcopy 900, 800, 32
        %1 = mload 900
        sink %1
    """

    post = """
    _global:
        nop  ; mcopy 200
        nop  ; mcopy 300
        nop  ; mcopy 400
        nop  ; mcopy 500
        nop  ; mcopy 600
        nop  ; mcopy 700
        nop  ; mcopy 800
        mcopy 900, 100, 32
        %1 = mload 900
        sink %1
    """
    _check_pre_post(pre, post)


def test_overlapping_copy_regions():
    """
    Test that overlapping copy regions are handled correctly.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 64  ; Copies [100-164) to [200-264)
        mcopy 300, 216, 32  ; Reads from middle of first copy's destination
        %1 = mload 300
        sink %1
    """

    # The second mcopy reads from 216, but first copy wrote to [200-264),
    # which overlaps but doesn't match exactly. No optimization.
    _check_no_change(pre)


def test_copy_with_zero_size():
    """
    Test that zero-size copies don't break anything.

    Zero-size copies don't write anything, so they're effectively no-ops.
    DSE will remove them, and they shouldn't be tracked for chaining.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 0  ; Zero-size copy
        mcopy 300, 200, 32  ; Can't chain - source wasn't really written
        %1 = mload 300
        sink %1
    """

    # Zero-size copy is removed by DSE, second mcopy cannot chain
    post = """
    _global:
        nop  ; mcopy 200, 100, 0 [zero-size, removed by DSE]
        mcopy 300, 200, 32
        %1 = mload 300
        sink %1
    """
    _check_pre_post(pre, post)


def test_interleaved_copies_different_regions():
    """
    Test that copies to different regions don't interfere.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        mcopy 200, 100, 32
        mcopy 400, 300, 32  ; Different region
        mcopy 500, 200, 32  ; Chain from first
        mcopy 600, 400, 32  ; Chain from second
        %1 = mload 500
        %2 = mload 600
        sink %2, %1
    """

    post = """
    _global:
        nop  ; mcopy 200
        nop  ; mcopy 400
        mcopy 500, 100, 32
        mcopy 600, 300, 32
        %1 = mload 500
        %2 = mload 600
        sink %2, %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_with_gep_different_geps():
    """
    Two paths with different gep instructions that compute same value.
    Should NOT optimize because gep results are different variables,
    and _traverse_assign_chain stops at gep (not assign).
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        %base = alloca 1, 256
        jnz %cond, @path1, @path2

    path1:
        %gep1 = gep 32, %base
        %x = assign %gep1
        calldatacopy 100, %x, 32
        jmp @merge

    path2:
        %gep2 = gep 32, %base
        %y = assign %gep2
        calldatacopy 100, %y, 32
        jmp @merge

    merge:
        mcopy 200, 100, 32
        %1 = mload 200
        sink %1
    """

    # mcopy should NOT be optimized - different geps break equivalence
    _check_no_change(pre)


def test_cross_bb_copy_with_gep_in_dominator():
    """
    Single gep in common dominator, assign chains through it.
    SHOULD optimize because the gep dominates merge point.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        %base = alloca 1, 256
        %gep = gep 32, %base
        jnz %cond, @path1, @path2

    path1:
        %x = assign %gep
        calldatacopy 100, %x, 32
        jmp @merge

    path2:
        %y = assign %gep
        calldatacopy 100, %y, 32
        jmp @merge

    merge:
        mcopy 200, 100, 32
        %1 = mload 200
        sink %1
    """

    post = """
    _global:
        %cond = param
        %base = alloca 1, 256
        %gep = gep 32, %base
        jnz %cond, @path1, @path2

    path1:
        %x = assign %gep
        nop  ; calldatacopy 100, %x, 32 [dead store - overwritten at merge]
        jmp @merge

    path2:
        %y = assign %gep
        nop  ; calldatacopy 100, %y, 32 [dead store - overwritten at merge]
        jmp @merge

    merge:
        calldatacopy 200, %gep, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_with_longer_assign_chain_through_gep():
    """
    Longer assign chain that goes through a gep in dominator.
    Should optimize - the gep dominates merge point.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        %base = alloca 1, 256
        %gep = gep 32, %base
        jnz %cond, @path1, @path2

    path1:
        %a = assign %gep
        %b = assign %a
        calldatacopy 100, %b, 32
        jmp @merge

    path2:
        %c = assign %gep
        %d = assign %c
        calldatacopy 100, %d, 32
        jmp @merge

    merge:
        mcopy 200, 100, 32
        %1 = mload 200
        sink %1
    """

    post = """
    _global:
        %cond = param
        %base = alloca 1, 256
        %gep = gep 32, %base
        jnz %cond, @path1, @path2

    path1:
        %a = assign %gep
        %b = assign %a
        nop  ; calldatacopy [dead store]
        jmp @merge

    path2:
        %c = assign %gep
        %d = assign %c
        nop  ; calldatacopy [dead store]
        jmp @merge

    merge:
        calldatacopy 200, %gep, 32
        %1 = mload 200
        sink %1
    """
    _check_pre_post(pre, post)


def test_cross_bb_copy_with_nested_gep_different_inner_geps():
    """
    Nested gep (gep of gep) with different inner gep instructions in each path.
    Should NOT optimize - the inner geps are different variables.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        %cond = param
        %base = alloca 1, 256
        %gep = gep 32, %base
        jnz %cond, @path1, @path2

    path1:
        %inner1 = gep 64, %gep
        %a = assign %inner1
        calldatacopy 100, %a, 32
        jmp @merge

    path2:
        %inner2 = gep 64, %gep
        %b = assign %inner2
        calldatacopy 100, %b, 32
        jmp @merge

    merge:
        mcopy 200, 100, 32
        %1 = mload 200
        sink %1
    """

    # mcopy should NOT be optimized - different inner geps break equivalence
    _check_no_change(pre)
