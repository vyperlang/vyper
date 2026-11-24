import pytest

from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import SingleUseExpansion

_check_pre_post = PrePostChecker([SingleUseExpansion], default_hevm=False)


def test_single_use_Expansion():
    """
    Test to was created from the example in the
    issue https://github.com/vyperlang/vyper/issues/4215
    it issue is handled by the SingleUseExpansion pass

    Originally it was handled by different reorder algorithm
    which is not necessary with single-use expansion
    """

    code = """
    main:
        %0 = 1
        %1 = 2
        %2 = 3
        %3 = 4
        %4 = 5

        ; %3 used multiple times by one instruction
        staticcall %0, %1, %2, %3, %4, %3

        ; %4 used multiple times by one instruction
        %5 = add %4, %4

        ret %5
    """

    ctx = parse_from_basic_block(code)

    # `staticcall %0, %1, %2, %3, %4, %3` and
    # `%5 = add %4, %4` are not store-expanded --
    # violates venom_to_assembly assumption
    with pytest.raises(AssertionError):
        generate_assembly_experimental(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        SingleUseExpansion(ac, fn).run_pass()

    generate_assembly_experimental(ctx)


def test_single_use_expansion_phi_operand_live_after_join():
    """
    A phi operand that is still used after the join (here in a
    successor block) must be copied on the incoming edge, so the phi
    does not consume the original.
    """
    pre = """
    main:
        %cond = calldataload 0
        %a = calldataload 32
        %b = calldataload 64
        jnz %cond, @p1, @p2
    p1:
        jmp @join
    p2:
        jmp @join
    join:
        %x = phi @p1, %a, @p2, %b
        jmp @next
    next:
        %z = add %x, %a
        sink %z
    """

    post = """
    main:
        %1 = 0
        %cond = calldataload %1
        %2 = 32
        %a = calldataload %2
        %3 = 64
        %b = calldataload %3
        jnz %cond, @p1, @p2
    p1:
        ; %a is copied on the incoming edge because it is live after the join.
        %4 = %a
        jmp @join
    p2:
        jmp @join
    join:
        ; %b is not used after the join, so it is left alone.
        %x = phi @p1, %4, @p2, %b
        jmp @next
    next:
        %5 = %a
        %z = add %x, %5
        sink %z
    """

    _check_pre_post(pre, post)
