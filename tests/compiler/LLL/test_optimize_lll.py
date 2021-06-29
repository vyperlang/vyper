import pytest

from vyper.lll import optimizer
from vyper.old_codegen.parser import LLLnode

optimize_list = [
    (["ne", 1, 0], ["ne", 1, 0]),  # noop
    (["if", ["ne", 1, 0], "pass"], ["if", ["xor", 1, 0], "pass"]),
    (["assert", ["ne", 1, 0]], ["assert", ["xor", 1, 0]]),
    (["mstore", 0, ["ne", 1, 0]], ["mstore", 0, ["ne", 1, 0]]),  # noop
]


@pytest.mark.parametrize("lll", optimize_list)
def test_lll_compile_fail(lll):
    optimized = optimizer.optimize(LLLnode.from_list(lll[0]))
    optimized.repr_show_gas = True
    hand_optimized = LLLnode.from_list(lll[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized
