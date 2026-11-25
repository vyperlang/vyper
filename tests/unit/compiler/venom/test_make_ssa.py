import pytest

from tests.evm_backends.base_env import BaseEnv
from tests.hevm import hevm_check_venom_ctx
from tests.venom_utils import assert_ctx_eq, parse_from_basic_block, parse_venom
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.assembler.core import assembly_to_evm
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.check_venom import check_venom_ctx
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


def _execute_venom(
    env: BaseEnv, code: str, calldata: bytes = b"", level: OptimizationLevel = OptimizationLevel.O1
) -> int:
    ctx = parse_venom(code)
    flags = VenomOptimizationFlags(level=level)
    run_passes_on(ctx, flags)
    asm = generate_assembly_experimental(ctx, optimize=level)
    bytecode, _ = assembly_to_evm(asm)
    initcode = bytes.fromhex(f"61{len(bytecode):04x}3d81600a3d39f3") + bytecode
    contract = env.deploy([], initcode)
    out = env.message_call(contract.address, data=calldata, gas=1_000_000)
    return int.from_bytes(out, "big")


def _assert_single_assignment(ctx) -> None:
    for fn in ctx.functions.values():
        seen = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    assert out not in seen, f"duplicate SSA definition of {out} in [{inst}]"
                    seen.add(out)


def test_user_var_ssa_name_collision_diamond(env):
    """
    Regression test for GH #5401: MakeSSA must not capture or collide with
    pre-existing user variables whose names match the `%name:version` pattern.
    """
    code = """
    function main [fmp_lowered, eom=0] {
      main:
        %z = 0
        %1 = calldataload %z
        jnz %1, @b1, @b2
      b1:
        %1 = 11
        jmp @join
      b2:
        %1 = 22
        jmp @join
      join:
        %1:1 = 77
        %2 = add %1, %1:1
        mstore %z, %2
        %3 = 32
        return %z, %3
    }
    """
    ctx = parse_venom(code)
    for fn in ctx.functions.values():
        MakeSSA(IRAnalysesCache(fn), fn).run_pass()
    _assert_single_assignment(ctx)
    check_venom_ctx(ctx)

    # calldata != 0 -> branch b1 (11 + 77 = 88); calldata == 0 -> branch b2 (22 + 77 = 99)
    for level in (OptimizationLevel.O1, OptimizationLevel.O2):
        assert _execute_venom(env, code, (1).to_bytes(32, "big"), level=level) == 88
        assert _execute_venom(env, code, (0).to_bytes(32, "big"), level=level) == 99


def test_user_var_ssa_name_collision_same_block_and_chained(env):
    """
    Verify MakeSSA avoids collisions in straight-line code, both when a
    colon-suffixed variable is defined before and after reassignments, and
    when multiple colliding names (%1:1, %1:2, %1:1:1) already exist.
    """
    code = """
    function main [fmp_lowered, eom=0] {
      main:
        %z = 0
        %1 = 10
        %1:1 = 100
        %1:2 = 200
        %1:1:1 = 300
        %1 = 20
        %1:1 = 400
        %s1 = add %1, %1:1
        %s2 = add %1:2, %1:1:1
        %res = add %s1, %s2
        mstore %z, %res
        %sz = 32
        return %z, %sz
    }
    """
    ctx = parse_venom(code)
    for fn in ctx.functions.values():
        MakeSSA(IRAnalysesCache(fn), fn).run_pass()
    _assert_single_assignment(ctx)
    check_venom_ctx(ctx)

    # 20 + 400 + 200 + 300 = 920
    assert _execute_venom(env, code) == 920


def test_user_var_ssa_name_collision_sibling_branches(env):
    """
    Verify MakeSSA does not assign a versioned name to a variable in one branch
    that collides with a pre-existing user variable in a sibling branch.
    """
    code = """
    function main [fmp_lowered, eom=0] {
      main:
        %z = 0
        %c = calldataload %z
        %1 = 1
        jnz %c, @left, @right
      left:
        %1 = 2
        %a = add %1, 10
        mstore %z, %a
        jmp @done
      right:
        %1:1 = 50
        %b = add %1, %1:1
        mstore %z, %b
        jmp @done
      done:
        %sz = 32
        return %z, %sz
    }
    """
    ctx = parse_venom(code)
    for fn in ctx.functions.values():
        MakeSSA(IRAnalysesCache(fn), fn).run_pass()
    _assert_single_assignment(ctx)
    check_venom_ctx(ctx)

    # calldata != 0 -> left (2 + 10 = 12); calldata == 0 -> right (1 + 50 = 51)
    assert _execute_venom(env, code, (1).to_bytes(32, "big")) == 12
    assert _execute_venom(env, code, (0).to_bytes(32, "big")) == 51
