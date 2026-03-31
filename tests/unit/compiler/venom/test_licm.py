from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import LICMPass


def test_licm_simple_hoist():
    """
    %inv should be hoisted out of the loop since it doesn't depend on loop vars
    and its block (body) dominates the exit.
    """
    pre = """
    _global:
        %x = 10
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        jmp @body
    body:
        %inv = add %x, 5
        %use = add %inv, %i
        %i_next = add %i, 1
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        return %use, 0
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    # %inv should be hoisted to preheader (_global)
    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # %inv = add %x, 5 should now be in preheader
    assert preheader_opcodes.count("add") == 1
    # body should have %use = add and %i_next = add, plus lt and jnz
    assert body_opcodes.count("add") == 2


def test_licm_no_hoist_loop_dependent():
    """
    %dep depends on %i which changes each iteration - should NOT be hoisted.
    """
    pre = """
    _global:
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        jmp @body
    body:
        %dep = add %i, 5
        %i_next = add %i, 1
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        return %dep, 0
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    # %dep should stay in the loop body (depends on %i)
    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # No adds should be hoisted
    assert "add" not in preheader_opcodes
    # Both adds should remain in body
    assert body_opcodes.count("add") == 2


def test_licm_needs_preheader():
    """
    Loop with multiple entry points - needs preheader insertion.
    """
    pre = """
    _global:
        %init1 = 0
        jnz 1, @entry1, @entry2
    entry1:
        %init2 = 0
        jmp @header
    entry2:
        %init3 = 0
        jmp @header
    header:
        %i = phi @entry1, %init2, @entry2, %init3, @body, %i_next
        jmp @body
    body:
        %inv = add 1, 2
        %i_next = add %i, 1
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    # A preheader should have been created
    preheader = fn.get_basic_block("preheader_header")
    assert preheader is not None

    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # %inv = add 1, 2 should be hoisted to preheader
    assert "add" in preheader_opcodes
    # body should only have %i_next = add, plus lt and jnz
    assert body_opcodes.count("add") == 1


def test_licm_no_hoist_not_dominating_exit():
    """
    %inv is invariant but in a block that doesn't dominate the exit.
    Should NOT be hoisted to avoid extra work.
    """
    pre = """
    _global:
        %x = 10
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        %cond = lt %i, 100
        jnz %cond, @body, @exit
    body:
        %inv = add %x, 5
        %i_next = add %i, 1
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    # %inv should NOT be hoisted because body doesn't dominate exit
    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # No adds in preheader
    assert "add" not in preheader_opcodes
    # Both adds remain in body
    assert body_opcodes.count("add") == 2


def test_licm_hoist_sload_no_sstore():
    """
    sload can be hoisted if there's no sstore in the loop.
    """
    pre = """
    _global:
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        jmp @body
    body:
        %val = sload 0
        %i_next = add %i, %val
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        return %i_next, 0
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # sload should be hoisted
    assert "sload" in preheader_opcodes
    assert "sload" not in body_opcodes


def test_licm_no_hoist_sload_with_sstore():
    """
    sload should NOT be hoisted if there's an sstore in the loop.
    """
    pre = """
    _global:
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        jmp @body
    body:
        sstore 0, %i
        %val = sload 0
        %i_next = add %i, %val
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        return %i_next, 0
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # sload should NOT be hoisted due to sstore in loop
    assert "sload" not in preheader_opcodes
    assert "sload" in body_opcodes


def test_licm_no_hoist_write_effects():
    """
    Instructions with write effects (like sstore) should NOT be hoisted.
    """
    pre = """
    _global:
        %x = 10
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        jmp @body
    body:
        sstore 0, %x
        %i_next = add %i, 1
        %cond = lt %i_next, 100
        jnz %cond, @header, @exit
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    LICMPass(ac, fn).run_pass()

    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # sstore should NOT be hoisted (has write effects)
    assert "sstore" not in preheader_opcodes
    assert "sstore" in body_opcodes


def test_licm_allow_speculative():
    """
    With allow_speculative=True, hoist even from blocks that don't dominate exits.
    """
    pre = """
    _global:
        %x = 10
        %init = 0
        jmp @header
    header:
        %i = phi @_global, %init, @body, %i_next
        %cond = lt %i, 100
        jnz %cond, @body, @exit
    body:
        %inv = add %x, 5
        %i_next = add %i, 1
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    # With allow_speculative=True, %inv should be hoisted even though body doesn't dominate exit
    LICMPass(ac, fn, allow_speculative=True).run_pass()

    preheader = fn.get_basic_block("_global")
    body = fn.get_basic_block("body")

    preheader_opcodes = [inst.opcode for inst in preheader.instructions]
    body_opcodes = [inst.opcode for inst in body.instructions]

    # %inv = add %x, 5 should be hoisted with speculative mode
    assert preheader_opcodes.count("add") == 1
    # body should only have %i_next = add
    assert body_opcodes.count("add") == 1
