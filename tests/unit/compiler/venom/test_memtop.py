"""
Unit tests for the `memtop` Venom instruction.

`memtop` returns a pointer past all currently-used memory (the EVM `MSIZE`
high-water mark). It is used by builtins (`raw_call(msg.data)`,
`create_copy_of`, `create_from_blueprint`) to obtain runtime-sized scratch
above the static frame and any spill slots.

Semantics:
1. Lowers to a single `MSIZE` byte at assembly time.
2. Has a `MEMORY` read effect — depends on all prior memory writes.
3. CSE may merge two `memtop` instructions only when no memory write
   separates them.
4. DFT must not reorder `memtop` past a memory write.
"""

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.parser import parse_venom
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.venom_to_assembly import VenomCompiler

# --------------------------------------------------------------------------
# Lowering: memtop -> MSIZE
# --------------------------------------------------------------------------


def test_memtop_lowers_to_msize():
    """
    A `memtop` instruction must lower to the EVM `MSIZE` opcode.
    """
    code = """
    function foo {
        main:
            %1 = memtop
            mstore 0, %1
            stop
    }
    """
    ctx = parse_venom(code)
    asm = VenomCompiler(ctx).generate_evm_assembly()
    # The exact stack layout depends on the scheduler; the only
    # guarantee we care about is that an MSIZE opcode is emitted.
    assert "MSIZE" in asm, asm


def test_memtop_only_emits_msize_byte():
    """
    Two memtop instructions in sequence (with no memory write between)
    should each be free to lower to MSIZE — and CSE should be free to
    merge them. Either way, MSIZE appears at least once.
    """
    code = """
    function foo {
        main:
            %1 = memtop
            %2 = memtop
            mstore 0, %1
            mstore 32, %2
            stop
    }
    """
    ctx = parse_venom(code)
    asm = VenomCompiler(ctx).generate_evm_assembly()
    assert asm.count("MSIZE") >= 1, asm


# --------------------------------------------------------------------------
# CSE: memtop is mergeable when no memory write separates two uses,
# and NOT mergeable when one does.
# --------------------------------------------------------------------------


def _run_cse(pre: str):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        CSE(ac, fn).run_pass()
    return ctx


def test_cse_does_not_merge_memtop_across_memory_write():
    """
    Regression: with the `MEMORY` read effect, an `mstore` between two
    `memtop` instructions invalidates the first one in the available
    expressions, so CSE must NOT replace the second with the first.
    Without this effect, both `memtop` ops would compute as the same
    expression and CSE would incorrectly merge them — but at runtime
    the mstore advances MSIZE, so the second memtop would return a
    different value.
    """
    pre = """
    main:
        %1 = memtop
        mstore %1, 42
        %2 = memtop
        sink %1, %2
    """
    ctx = _run_cse(pre)

    # The pass must NOT have collapsed %2 into an alias of %1.
    fn = next(iter(ctx.functions.values()))
    memtops = [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "memtop"
    ]
    assert len(memtops) == 2, (
        f"CSE must not merge memtops across a memory write, " f"got {len(memtops)} memtop(s)"
    )


def test_cse_merges_memtop_without_memory_write():
    """
    Two consecutive `memtop` instructions with no intervening memory
    write are equivalent and CSE may merge them. (At runtime MSIZE
    has not advanced, so both return the same value.)
    """
    pre = """
    main:
        %1 = memtop
        %2 = memtop
        sink %1, %2
    """
    post = """
    main:
        %1 = memtop
        %2 = %1
        sink %1, %2
    """
    ctx_pre = _run_cse(pre)
    assert_ctx_eq(ctx_pre, parse_from_basic_block(post))


# --------------------------------------------------------------------------
# DFT scheduling: memtop must not be reordered past a memory write
# --------------------------------------------------------------------------


def test_memtop_emission_respects_memory_write_ordering():
    """
    A function that writes memory then reads `memtop` must produce
    assembly where MSIZE is emitted *after* MSTORE — the MEMORY read
    effect on memtop creates an effect dependency that prevents DFT
    from reordering the memtop before the mstore.
    """
    code = """
    function foo {
        main:
            mstore 0, 99
            %1 = memtop
            mstore 32, %1
            stop
    }
    """
    ctx = parse_venom(code)
    asm = VenomCompiler(ctx).generate_evm_assembly()

    # Locate the first MSTORE and the MSIZE; MSIZE must come AFTER
    # the first MSTORE so that it observes the memory growth.
    msize_idx = asm.index("MSIZE")
    first_mstore_idx = asm.index("MSTORE")
    assert first_mstore_idx < msize_idx, (
        f"MSIZE must come after the prior MSTORE, " f"got asm={asm}"
    )
