import pytest

from vyper.codegen.ir_node import IRnode
from vyper.ir import optimizer

optimize_list = [
    (["eq", 1, 0], ["iszero", 1]),
    (["eq", 1, 2], ["eq", 1, 2]),  # noop
    (["if", ["eq", 1, 2], "pass"], ["if", ["iszero", ["xor", 1, 2]], "pass"]),
    (["assert", ["eq", 1, 2]], ["assert", ["iszero", ["xor", 1, 2]]]),
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, ["eq", 1, 2]]),  # noop
]


@pytest.mark.parametrize("ir", optimize_list)
def test_ir_compile_fail(ir):
    optimized = optimizer.optimize(IRnode.from_list(ir[0]))
    optimized.repr_show_gas = True
    hand_optimized = IRnode.from_list(ir[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized
