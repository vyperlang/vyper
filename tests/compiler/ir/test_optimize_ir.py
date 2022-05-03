import pytest

from vyper.codegen.ir_node import IRnode
from vyper.ir import optimizer

optimize_list = [
    (["eq", 1, 2], [0]),
    (["lt", 1, 2], [1]),
    (["eq", "x", 0], ["iszero", "x"]),
    # branch pruner
    (["if", ["eq", 1, 2], "pass"], ["seq"]),
    (["if", ["eq", 1, 1], 3, 4], [3]),
    (["if", ["eq", 1, 2], 3, 4], [4]),
    # condition rewriter
    (["if", ["eq", "x", "y"], "pass"], ["if", ["iszero", ["xor", "x", "y"]], "pass"]),
    (["if", "cond", 1, 0], ["if", ["iszero", "cond"], 0, 1]),
    (["assert", ["eq", "x", "y"]], ["assert", ["iszero", ["xor", "x", "y"]]]),
    # nesting
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, 0]),
    # conditions
    (["ge", "x", 0], [1]),  # x >= 0 == True
    (["iszero", ["gt", "x", 2 ** 256 - 1]], [1]),  # x >= MAX_UINT256 == False
    (["iszero", ["sgt", "x", 2 ** 255 - 1]], [1]),  # signed x >= MAX_INT256 == False
    (["le", "x", 0], ["iszero", "x"]),
    (["lt", "x", 0], [0]),
    (["slt", "x", -(2 ** 255)], ["slt", "x", -(2 ** 255)]),  # unimplemented
    # arithmetic
    (["add", "x", 0], ["x"]),
    (["add", 0, "x"], ["x"]),
    (["sub", "x", 0], ["x"]),
    (["mul", "x", 1], ["x"]),
    (["div", "x", 1], ["x"]),
    (["sdiv", "x", 1], ["x"]),
    (["mod", "x", 1], [0]),
    (["smod", "x", 1], [0]),
    (["mul", "x", -1], ["sub", 0, "x"]),
    (["sdiv", "x", -1], ["sub", 0, "x"]),
    (["mul", "x", 0], [0]),
    (["div", "x", 0], [0]),
    (["sdiv", "x", 0], [0]),
    (["mod", "x", 0], [0]),
    (["smod", "x", 0], [0]),
    (["mul", "x", 32], ["shl", 5, "x"]),
    (["div", "x", 64], ["shr", 6, "x"]),
    (["mod", "x", 128], ["and", "x", 127]),
    (["sdiv", "x", 64], ["sdiv", "x", 64]),  # no-op
    (["smod", "x", 64], ["smod", "x", 64]),  # no-op
    # bitwise ops
    (["shr", 0, "x"], ["x"]),
    (["sar", 0, "x"], ["x"]),
    (["shl", 0, "x"], ["x"]),
]


@pytest.mark.parametrize("ir", optimize_list)
def test_ir_compile_fail(ir):
    optimized = optimizer.optimize(IRnode.from_list(ir[0]))
    optimized.repr_show_gas = True
    hand_optimized = IRnode.from_list(ir[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized
