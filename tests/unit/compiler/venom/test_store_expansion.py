import pytest

from tests.venom_utils import parse_from_basic_block
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import StoreExpansionPass


def test_store_expansion():
    """
    Test to was created from the example in the
    issue https://github.com/vyperlang/vyper/issues/4215
    it issue is handled by StoreExpansionPass

    Originally it was handled by different reorder algorithm
    which is not necessary with store expansion
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
        StoreExpansionPass(ac, fn).run_pass()

    generate_assembly_experimental(ctx)
