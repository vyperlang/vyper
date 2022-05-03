import pytest

from vyper.codegen.ir_node import IRnode
from vyper.ir import optimizer

optimize_list = [
    (["eq", 1, 2], [0]),
    (["eq", "x", 0], ["iszero", "x"]),
    (["if", ["eq", 1, 2], "pass"], ["seq"]),
    (["if", ["eq", "x", "y"], "pass"], ["if", ["iszero", ["xor", "x", "y"]], "pass"]),
    (["assert", ["eq", "x", "y"]], ["assert", ["iszero", ["xor", "x", "y"]]]),
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, 0]),
]


@pytest.mark.parametrize("ir", optimize_list)
def test_ir_compile_fail(ir):
    optimized = optimizer.optimize(IRnode.from_list(ir[0]))
    optimized.repr_show_gas = True
    hand_optimized = IRnode.from_list(ir[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized
