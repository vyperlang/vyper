import pytest

from tests.venom_utils import PrePostChecker
from vyper.evm.opcodes import version_check
from vyper.venom.passes import MemoryCopyElisionPass

_check_pre_post = PrePostChecker([MemoryCopyElisionPass], default_hevm=False)


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_load_store_no_elision():
    """
    Basic load-store test - single word copy is already optimal.
    mload followed by mstore should NOT be changed.
    """
    pre = """
    _global:
        %1 = mload 100
        mstore %1, 200
        stop
    """
    _check_no_change(pre)


def test_redundant_copy_elimination():
    """
    Test that copying to the same location is eliminated entirely.
    """
    pre = """
    _global:
        %1 = mload 100
        mstore 100, %1
        stop
    """

    post = """
    _global:
        nop  ; mstore 100, %1                  [memory copy elision - redundant store]
        nop  ; %1 = mload 100                  [memory copy elision - redundant load]
        stop
    """
    _check_pre_post(pre, post)


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
    _check_no_change(pre)


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
    """
    Test that calldatacopy acts as a barrier for optimizations.
    """
    pre = """
    _global:
        %1 = mload 100
        calldatacopy 200, 0, 32  ; BARRIER - writes to memory
        mstore %1, 300
        %2 = mload 200
        sink %2
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
    Test that special copy + mcopy chain is NOT optimized if intermediate location is read.
    """
    if not version_check(begin="cancun"):
        return

    pre = """
    _global:
        calldatacopy 100, 0, 32  ; Copy to intermediate location
        %1 = mload 100           ; Read from intermediate location - BARRIER
        mcopy 200, 100, 32       ; This cannot be merged
        mstore 300, %1
        %1 = mload 300
        %2 = mload 200
        sink %2, %1
    """
    _check_no_change(pre)


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
    Test that mcopy chains don't merge across basic block boundaries.
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

    # No optimization should happen - mcopies are in different blocks
    post = pre

    _check_pre_post(pre, post)


def test_special_copy_chain_across_blocks():
    """
    Test that special copy + mcopy chains don't merge across basic block boundaries.
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

    # No optimization should happen - copies are in different blocks
    post = pre

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


@pytest.mark.xfail
def test_mem_elision_msize():
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

    post = """
    main:
        %1 = mload 100
        nop
        %2 = msize
        sink %2
    """

    _check_pre_post(pre, post)
