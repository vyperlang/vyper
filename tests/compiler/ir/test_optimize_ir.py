import pytest

from vyper.codegen.ir_node import IRnode
from vyper.exceptions import StaticAssertionException
from vyper.ir import optimizer

optimize_list = [
    (["eq", 1, 2], [0]),
    (["lt", 1, 2], [1]),
    (["eq", "x", 0], ["iszero", "x"]),
    # branch pruner
    (["if", ["eq", 1, 2], "pass"], ["seq"]),
    (["if", ["eq", 1, 1], 3, 4], [3]),
    (["if", ["eq", 1, 2], 3, 4], [4]),
    (["seq", ["assert", ["lt", 1, 2]]], ["seq"]),
    (["seq", ["assert", ["lt", 1, 2]], 2], [2]),
    # condition rewriter
    (["if", ["eq", "x", "y"], "pass"], ["if", ["iszero", ["sub", "x", "y"]], "pass"]),
    (["if", "cond", 1, 0], ["if", ["iszero", "cond"], 0, 1]),
    (["assert", ["eq", "x", "y"]], ["assert", ["iszero", ["sub", "x", "y"]]]),
    # nesting
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, 0]),
    # conditions
    (["ge", "x", 0], [1]),  # x >= 0 == True
    (["iszero", ["gt", "x", 2 ** 256 - 1]], [1]),  # x >= MAX_UINT256 == False
    (["iszero", ["sgt", "x", 2 ** 255 - 1]], [1]),  # signed x >= MAX_INT256 == False
    (["le", "x", 0], ["iszero", "x"]),
    (["le", 0, "x"], [1]),
    (["lt", "x", 0], [0]),
    (["lt", 0, "x"], ["iszero", ["iszero", "x"]]),
    (["gt", 5, "x"], ["lt", "x", 5]),
    (["ge", 5, "x"], ["le", "x", 5]),
    (["lt", 5, "x"], ["gt", "x", 5]),
    (["le", 5, "x"], ["ge", "x", 5]),
    (["sgt", 5, "x"], ["slt", "x", 5]),
    (["sge", 5, "x"], ["sle", "x", 5]),
    (["slt", 5, "x"], ["sgt", "x", 5]),
    (["sle", 5, "x"], ["sge", "x", 5]),
    (["slt", "x", -(2 ** 255)], ["slt", "x", -(2 ** 255)]),  # unimplemented
    # tricky conditions
    (["sgt", 2 ** 256 - 1, 0], [0]),  # -1 > 0
    (["gt", 2 ** 256 - 1, 0], [1]),  # -1 > 0
    (["gt", 2 ** 255, 0], [1]),  # 0x80 > 0
    (["sgt", 2 ** 255, 0], [0]),  # 0x80 > 0
    (["sgt", 2 ** 255, 2 ** 255 - 1], [0]),  # 0x80 > 0x81
    (["gt", -(2 ** 255), 2 ** 255 - 1], [1]),  # 0x80 > 0x81
    (["slt", 2 ** 255, 2 ** 255 - 1], [1]),  # 0x80 < 0x7f
    (["lt", -(2 ** 255), 2 ** 255 - 1], [0]),  # 0x80 < 0x7f
    (["sle", -1, 2 ** 256 - 1], [1]),  # -1 <= -1
    (["sge", -(2 ** 255), 2 ** 255], [1]),  # 0x80 >= 0x80
    (["sgt", -(2 ** 255), 2 ** 255], [0]),  # 0x80 > 0x80
    (["slt", 2 ** 255, -(2 ** 255)], [0]),  # 0x80 < 0x80
    # arithmetic
    (["add", "x", 0], ["x"]),
    (["add", 0, "x"], ["x"]),
    (["sub", "x", 0], ["x"]),
    (["sub", "x", "x"], [0]),
    (["sub", ["sload", 0], ["sload", 0]], ["sub", ["sload", 0], ["sload", 0]]),  # no-op
    (["sub", ["callvalue"], ["callvalue"]], ["sub", ["callvalue"], ["callvalue"]]),  # no-op
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
    (["and", 1, 2], [0]),
    (["or", 1, 2], [3]),
    (["xor", 1, 2], [3]),
    (["xor", 3, 2], [1]),
    (["and", 0, "x"], [0]),
    (["and", "x", 0], [0]),
    (["or", "x", 0], ["x"]),
    (["or", 0, "x"], ["x"]),
    (["xor", "x", 0], ["x"]),
    (["xor", "x", 1], ["xor", "x", 1]),  # no-op
    (["and", "x", 1], ["and", "x", 1]),  # no-op
    (["or", "x", 1], ["or", "x", 1]),  # no-op
    (["xor", 0, "x"], ["x"]),
    (["iszero", ["or", "x", 1]], [0]),
    (["iszero", ["or", 2, "x"]], [0]),
    # nested optimizations
    (["eq", 0, ["sub", 1, 1]], [1]),
    (["eq", 0, ["add", 2 ** 255, 2 ** 255]], [1]),  # test compile-time wrapping
    (["eq", 0, ["add", 2 ** 255, -(2 ** 255)]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", 0, -1]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", 2 ** 255, 2 ** 255 - 1]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", -(2 ** 255), 2 ** 255 - 1]], [1]),  # test compile-time wrapping
    (["eq", -2, ["add", 2 ** 256 - 1, 2 ** 256 - 1]], [1]),  # test compile-time wrapping
]


@pytest.mark.parametrize("ir", optimize_list)
def test_ir_optimizer(ir):
    optimized = optimizer.optimize(IRnode.from_list(ir[0]))
    optimized.repr_show_gas = True
    hand_optimized = IRnode.from_list(ir[1])
    hand_optimized.repr_show_gas = True
    assert optimized == hand_optimized


static_assertions_list = [
    ["assert", ["eq", 2, 1]],
    ["assert", ["ne", 1, 1]],
    ["assert", ["sub", 1, 1]],
    ["assert", ["lt", 2, 1]],
    ["assert", ["lt", 1, 1]],
    ["assert", ["lt", "x", 0]],  # +x < 0
    ["assert", ["le", 1, 0]],
    ["assert", ["le", 2 ** 256 - 1, 0]],
    ["assert", ["gt", 1, 2]],
    ["assert", ["gt", 1, 1]],
    ["assert", ["gt", 0, 2 ** 256 - 1]],
    ["assert", ["gt", "x", 2 ** 256 - 1]],
    ["assert", ["ge", 1, 2]],
    ["assert", ["ge", 1, 2]],
    ["assert", ["slt", 2, 1]],
    ["assert", ["slt", 1, 1]],
    ["assert", ["slt", 0, 2 ** 256 - 1]],  # 0 < -1
    ["assert", ["slt", -(2 ** 255), 2 ** 255]],  # 0x80 < 0x80
    ["assert", ["sle", 0, 2 ** 255]],  # 0 < 0x80
    ["assert", ["sgt", 1, 2]],
    ["assert", ["sgt", 1, 1]],
    ["assert", ["sgt", 2 ** 256 - 1, 0]],  # -1 > 0
    ["assert", ["sgt", 2 ** 255, -(2 ** 255)]],  # 0x80 > 0x80
    ["assert", ["sge", 2 ** 255, 0]],  # 0x80 > 0
]


@pytest.mark.parametrize("ir", static_assertions_list)
def test_static_assertions(ir, assert_compile_failed):
    ir = IRnode.from_list(ir)
    assert_compile_failed(lambda: optimizer.optimize(ir), StaticAssertionException)
