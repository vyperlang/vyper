import pytest

from vyper.lll import optimizer
from vyper.old_codegen.parser import LLLnode

optimize_list = [
    (["eq", 1, 0], ["iszero", 1]),
    (["eq", 1, 2], ["eq", 1, 2]),  # noop
    (["if", ["eq", 1, 2], "pass"], ["if", ["iszero", ["xor", 1, 2]], "pass"]),
    (["assert", ["eq", 1, 2]], ["assert", ["iszero", ["xor", 1, 2]]]),
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, ["eq", 1, 2]]),  # noop
]


@pytest.mark.parametrize("lll", optimize_list)
def test_lll_compile_fail(lll):
    optimized = optimizer.optimize(LLLnode.from_list(lll[0]))
    optimized.repr_show_gas = True
    hand_optimized = LLLnode.from_list(lll[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized
