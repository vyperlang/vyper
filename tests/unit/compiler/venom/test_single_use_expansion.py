import pytest

from tests.venom_utils import parse_from_basic_block
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRVariable
from vyper.venom.parser import parse_venom
from vyper.venom.passes import SingleUseExpansion


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
    code = """
    function main {
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
    }
    """
    ctx = parse_venom(code)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    SingleUseExpansion(ac, fn).run_pass()

    phi = fn.get_basic_block("join").instructions[0]
    assert phi.opcode == "phi"
    incoming = dict((label.name, var) for label, var in phi.phi_operands)

    # %a is copied on the edge from p1
    assert incoming["p1"] != IRVariable("a")
    copy = fn.get_basic_block("p1").instructions[-2]
    assert copy.opcode == "assign"
    assert copy.output == incoming["p1"]
    assert copy.operands == [IRVariable("a")]

    # %b is not used after the join, so it is left alone
    assert incoming["p2"] == IRVariable("b")
