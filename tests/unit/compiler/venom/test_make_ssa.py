import pytest

from tests.hevm import hevm_check_venom_ctx
from tests.venom_utils import assert_ctx_eq, parse_from_basic_block, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import MakeSSA


def _check_pre_post(pre, post):
    ctx = parse_venom(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_venom(post))


def test_phi_case():
    pre = """
    function loop {
    main:
        %v = mload 64
        jmp @test
    test:
        jnz %v, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @continue
    else:
        jmp @continue
    continue:
        %v = add %v, 1
        jmp @test
    }
    """
    post = """
    function loop {
    main:
        %v = mload 64
        jmp @test
    test:
        %v:1 = phi @main, %v, @continue, %v:2
        jnz %v:1, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @continue
    else:
        jmp @continue
    continue:
        %v:2 = add %v:1, 1
        jmp @test
    }
    """
    _check_pre_post(pre, post)


def test_multiple_make_ssa_error():
    pre = """
    main:
        %v = mload 64
        jmp @test
    test:
        jnz %v, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @if_exit
    else:
        jmp @if_exit
    if_exit:
        %v = add %v, 1
        jmp @test
    """

    # Running MakeSSA twice creates nested versions (%v:1:1).
    # The assign for %v:1 is dead code - DCE would clean it up.
    post = """
    main:
        %v = mload 64
        jmp @test
    test:
        %v:1:1 = phi @main, %v, @if_exit, %v:2
        %v:1 = %v:1:1
        jnz %v:1:1, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @if_exit
    else:
        jmp @if_exit
    if_exit:
        %v:2 = add %v:1:1, 1
        jmp @test
    """

    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_self_loop_phi():
    """
    Test that MakeSSA correctly handles self-loops (blocks with self-edges).

    Regression test for two bugs:
    1. _place_phi skips self-edges when creating phi operands
    2. _remove_degenerate_phis removes single-operand phis without substituting uses

    Together these cause undefined variable uses in self-loop patterns.
    """
    pre = """
    function self_loop {
    entry:
        %x = mload 0
        %cond = mload 32
        jmp @loop
    loop:
        %y = add %x, 1
        %x = %y
        jnz %cond, @loop, @exit
    exit:
        sink %x
    }
    """
    # The phi in loop must have BOTH the entry edge AND the self-edge
    post = """
    function self_loop {
    entry:
        %x = mload 0
        %cond = mload 32
        jmp @loop
    loop:
        %x:1 = phi @entry, %x, @loop, %x:2
        %y = add %x:1, 1
        %x:2 = %y
        jnz %cond, @loop, @exit
    exit:
        sink %x:2
    }
    """
    _check_pre_post(pre, post)


def test_self_loop_no_undefined_vars():
    """
    Verify MakeSSA doesn't leave undefined variable uses in self-loops.

    This is an alternative check that doesn't depend on exact phi format -
    it just verifies all used variables are defined.
    """
    from vyper.venom.basicblock import IRVariable

    pre = """
    function self_loop {
    entry:
        %x = mload 0
        %cond = mload 32
        jmp @loop
    loop:
        %y = add %x, 1
        %x = %y
        jnz %cond, @loop, @exit
    exit:
        sink %x
    }
    """
    ctx = parse_venom(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()

        # Collect all defined variables
        defined = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    defined.add(out)

        # Check all variable uses are defined
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for op in inst.operands:
                    if isinstance(op, IRVariable):
                        assert op in defined, f"{op} used in [{inst}] but never defined"


def test_self_assignment_in_loop():
    """
    Regression test for liveness analysis bug.

    When a variable is both used and defined in the same instruction
    (e.g., %x = add %x, 1), the liveness analysis must mark %x as live-in.
    The bug was computing (live U uses) - defs instead of (live - defs) U uses,
    which incorrectly removed %x from the live set.

    This caused MakeSSA to miss phi placement for tight self-loops.
    """
    pre = """
    function self_assign {
    entry:
        %x = mload 0
        %cond = mload 32
        jmp @loop
    loop:
        %x = add %x, 1
        jnz %cond, @loop, @exit
    exit:
        sink %x
    }
    """
    # The phi MUST be placed in loop block because %x is live-in
    # (used in add before being redefined)
    post = """
    function self_assign {
    entry:
        %x = mload 0
        %cond = mload 32
        jmp @loop
    loop:
        %x:1 = phi @entry, %x, @loop, %x:2
        %x:2 = add %x:1, 1
        jnz %cond, @loop, @exit
    exit:
        sink %x:2
    }
    """
    _check_pre_post(pre, post)


def test_phi_all_same_values():
    """
    Test phi where both branches define %x independently.

    Both edges define %x with the same expression structure,
    but they're different SSA variables, so phi is needed.
    """
    pre = """
    function diamond {
    entry:
        %x = mload 0
        %cond = mload 32
        jnz %cond, @left, @right
    left:
        %x = add %x, 1
        jmp @join
    right:
        %x = add %x, 1
        jmp @join
    join:
        sink %x
    }
    """
    # Variable numbering depends on dominator tree traversal order:
    # - join's phi gets %x:1 (phis placed first)
    # - right gets %x:2, left gets %x:3
    post = """
    function diamond {
    entry:
        %x = mload 0
        %cond = mload 32
        jnz %cond, @left, @right
    left:
        %x:3 = add %x, 1
        jmp @join
    right:
        %x:2 = add %x, 1
        jmp @join
    join:
        %x:1 = phi @left, %x:3, @right, %x:2
        sink %x:1
    }
    """
    _check_pre_post(pre, post)


def test_phi_all_same_values_simplify():
    """
    Test phi simplification when all incoming values are actually the same variable.

    This covers the optimization path where after removing self-references,
    all remaining phi operands have identical values.
    """
    pre = """
    function diamond_same {
    entry:
        %x = mload 0
        %cond = mload 32
        jnz %cond, @left, @right
    left:
        jmp @join
    right:
        jmp @join
    join:
        sink %x
    }
    """
    # %x is not redefined in either branch, so no phi needed at join
    # (liveness check in _place_phi prevents phi placement)
    post = """
    function diamond_same {
    entry:
        %x = mload 0
        %cond = mload 32
        jnz %cond, @left, @right
    left:
        jmp @join
    right:
        jmp @join
    join:
        sink %x
    }
    """
    _check_pre_post(pre, post)


@pytest.mark.hevm
def test_make_ssa_error():
    code = """
    main:
        %cond = source
        %v = 0
        jnz %cond, @then, @else
    then:
        %v = 1
        jnz 1, @join, @unreachable
    unreachable:
        %v = 100
        jmp @join
    else:
        %v = 2
        jmp @join
    join:
        sink %v
    """

    ctx = parse_from_basic_block(code)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    post_ctx = parse_from_basic_block(code)
    for fn in post_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    hevm_check_venom_ctx(ctx, post_ctx)
