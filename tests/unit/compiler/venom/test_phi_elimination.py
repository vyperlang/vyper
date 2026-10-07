import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.parser import parse_venom
from vyper.venom.passes import PhiEliminationPass

_check_pre_post = PrePostChecker([PhiEliminationPass], default_hevm=False)


@pytest.mark.hevm
def test_simple_phi_elimination():
    pre = """
    main:
        %1 = source
        %cond = source
        %2 = %1
        jnz %cond, @then, @else
    then:
        jmp @else
    else:
        %3 = phi @main, %1, @else, %2
        sink %3
    """

    post = """
    main:
        %1 = source
        %cond = source
        %2 = %1
        jnz %cond, @then, @else
    then:
        jmp @else
    else:
        %3 = %1
        sink %3
    """

    _check_pre_post(pre, post, hevm=True)


def test_phi_elim_loop():
    pre = """
    main:
        %v = source
        jmp @loop
    loop:
        %v:2 = phi @main, %v, @loop, %v:2
        jmp @loop
    """

    post = """
    main:
        %v = source
        jmp @loop
    loop:
        %v:2 = %v
        jmp @loop
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop2():
    pre = """
    main:
        %1 = calldataload 0
        %2 = %1
        jmp @condition

    condition:
        %3 = phi @main, %1, @body, %4
        %cond = calldataload 100
        jnz %cond, @exit, @body

    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %another_cond, @condition, @exit

    exit:
        %5 = phi @condition, %3, @body, %4
        mstore 0, %5
        return 0, 32
    """

    post = """
    main:
        %1 = calldataload 0
        %2 = %1
        jmp @condition

    condition:
        %3 = %1
        %cond = calldataload 100
        jnz %cond, @exit, @body

    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %another_cond, @condition, @exit

    exit:
        %5 = %1
        mstore 0, %5
        return 0, 32
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop_inner_phi():
    pre = """
    main:
        %1 = source
        %rand = source
        %2 = %1
        jmp @condition
    condition:
        %3 = phi @main, %1, @body, %6
        %cond = iszero %3
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %rand, @then, @else
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = phi @then, %6:1, @else, %6:2
        jnz %another_cond, @condition, @exit
    exit:
        %5 = phi @condition, %3, @body, %4
        sink %5
    """

    post = """
    main:
        %1 = source
        %rand = source
        %2 = %1
        jmp @condition
    condition:
        %3 = %1
        %cond = iszero %3
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %rand, @then, @else
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = %1
        jnz %another_cond, @condition, @exit
    exit:
        %5 = %1
        sink %5
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop_inner_phi_simple():
    pre = """
    main:
        %p = source
        jmp @loop_start
    loop_start:
        %1 = phi @main, %p, @loop_join, %4
        jnz %1, @then, @else
    then:
        %2 = %1
        jmp @loop_join
    else:
        %3 = %1
        jmp @loop_join
    loop_join:
        %4 = phi @then, %2, @else, %3
        jmp @loop_start
    """

    post = """
    main:
        %p = source
        jmp @loop_start
    loop_start:
        %1 = %p
        jnz %1, @then, @else
    then:
        %2 = %1
        jmp @loop_join
    else:
        %3 = %1
        jmp @loop_join
    loop_join:
        %4 = %p
        jmp @loop_start
    """

    _check_pre_post(pre, post)


def test_phi_elim_cannot_remove():
    pre = """
    main:
        %p = source
        %rand = source
        jmp @cond
    cond:
        %1 = phi @main, %p, @body, %3
        %cond = iszero %1
        jnz %cond, @body, @join
    body:
        jnz %rand, @then, @join
    then:
        %2 = 2
        jmp @join
    join:
        %3 = phi @body, %1, @then, %2
        jmp @cond
    exit:
        sink %p
    """

    _check_pre_post(pre, pre, hevm=False)


def test_phi_elim_direct_loop():
    pre1 = """
    main:
        %p = source
        jmp @loop
    loop:
        %1 = phi @main, %p, @loop, %2
        %2 = %1
        jmp @loop
    """

    pre2 = """
    main:
        %p = source
        jmp @loop
    loop:
        %1 = phi @main, %p, @loop, %2
        %2 = %1
        jmp @loop
    """

    post = """
    main:
        %p = source
        jmp @loop
    loop:
        %1 = %p
        %2 = %1
        jmp @loop
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)


def test_phi_elim_two_phi_merges():
    pre = """
    main:
        %cond = source
        %cond2 = source
        jnz %cond, @1_then, @2_then
    1_then:
        %1 = 100
        jmp @3_join
    2_then:
        %2 = 101
        jmp @3_join
    3_join:
        %3 = phi @1_then, %1, @2_then, %2
        jnz %cond2, @4_then, @5_then
    4_then:
        %4 = %3
        jmp @6_join
    5_then:
        %5 = %3
        jmp @6_join
    6_join:
        %6 = phi @4_then, %4, @5_then, %5  ; should be reduced to %3!
        sink %6
    """

    post = """
    main:
        %cond = source
        %cond2 = source
        jnz %cond, @1_then, @2_then
    1_then:
        %1 = 100
        jmp @3_join
    2_then:
        %2 = 101
        jmp @3_join
    3_join:
        %3 = phi @1_then, %1, @2_then, %2
        jnz %cond2, @4_then, @5_then
    4_then:
        %4 = %3
        jmp @6_join
    5_then:
        %5 = %3
        jmp @6_join
    6_join:
        %6 = %3
        sink %6
    """

    _check_pre_post(pre, post, hevm=True)


def test_phi_elim_multi_output_invoke_distinct_outputs_kept():
    # a phi over two different outputs of the same invoke instruction
    # must not be collapsed: the origins trace to the same producing
    # instruction, but to different variables (GH 5039)
    pre = """
    function main {
    main:
        %cond = source
        %r1, %r2 = invoke @f
        jnz %cond, @then, @else
    then:
        jmp @join
    else:
        jmp @join
    join:
        %z = phi @then, %r1, @else, %r2
        sink %z
    }

    function f {
    f:
        %retpc = param
        ret %retpc
    }
    """

    ctx = parse_venom(pre)
    fn = ctx.get_function(IRLabel("main"))
    ac = IRAnalysesCache(fn)
    PhiEliminationPass(ac, fn).run_pass()

    insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
    phis = [inst for inst in insts if inst.opcode == "phi"]
    assert len(phis) == 1, "phi over distinct invoke outputs must be kept"
    assert phis[0].output.name == "%z"


def test_phi_elim_multi_output_invoke_same_output_eliminated():
    # Same producer instruction and same output variable: this phi is trivial
    # even though the root instruction has multiple outputs.
    source = """
    function main {
    main:
        %cond = source
        %r1, %r2 = invoke @f
        %r2_copy = %r2
        jnz %cond, @then, @else
    then:
        jmp @join
    else:
        jmp @join
    join:
        %z = phi @then, %r2, @else, %r2_copy
        sink %z
    }

    function f {
    f:
        %retpc = param
        ret %retpc
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("main"))
    ac = IRAnalysesCache(fn)
    PhiEliminationPass(ac, fn).run_pass()

    insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
    phis = [inst for inst in insts if inst.opcode == "phi"]
    assert len(phis) == 0, "phi over the same invoke output should be eliminated"

    z_assigns = [inst for inst in insts if [out.name for out in inst.get_outputs()] == ["%z"]]
    assert len(z_assigns) == 1
    assert z_assigns[0].opcode == "assign"
    assert z_assigns[0].operands[0].name == "%r2"
