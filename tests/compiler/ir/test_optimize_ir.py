import pytest

from vyper.codegen.ir_node import IRnode
from vyper.exceptions import StaticAssertionException
from vyper.ir import optimizer

optimize_list = [
    (["eq", 1, 2], [0]),
    (["lt", 1, 2], [1]),
    (["eq", "x", 0], ["iszero", "x"]),
    (["ne", "x", 0], ["iszero", ["iszero", "x"]]),
    (["ne", "x", 1], None),
    (["iszero", ["ne", "x", 1]], ["iszero", ["iszero", ["iszero", ["xor", "x", 1]]]]),
    (["eq", ["sload", 0], 0], ["iszero", ["sload", 0]]),
    # branch pruner
    (["if", ["eq", 1, 2], "pass"], ["seq"]),
    (["if", ["eq", 1, 1], 3, 4], [3]),
    (["if", ["eq", 1, 2], 3, 4], [4]),
    (["seq", ["assert", ["lt", 1, 2]]], ["seq"]),
    (["seq", ["assert", ["lt", 1, 2]], 2], [2]),
    # condition rewriter
    (["if", ["eq", "x", "y"], "pass"], ["if", ["iszero", ["xor", "x", "y"]], "pass"]),
    (["if", "cond", 1, 0], ["if", ["iszero", "cond"], 0, 1]),
    (["if", ["ne", "x", 1], [1]], None),
    (
        # TODO: this is perf issue (codegen should usually generate `if (ne x y)` though)
        ["if", ["iszero", ["eq", "x", "y"]], [1]],
        ["if", ["iszero", ["iszero", ["xor", "x", "y"]]], 1],
    ),
    (["assert", ["eq", "x", "y"]], ["assert", ["iszero", ["xor", "x", "y"]]]),
    (["assert", ["ne", "x", "y"]], None),
    # nesting
    (["mstore", 0, ["eq", 1, 2]], ["mstore", 0, 0]),
    # conditions
    (["ge", "x", 0], [1]),  # x >= 0 == True
    (["ge", ["sload", 0], 0], None),  # no-op
    (["gt", "x", 2**256 - 1], [0]),  # x >= MAX_UINT256 == False
    # (x > 0) => x == 0
    (["iszero", ["gt", "x", 0]], ["iszero", ["iszero", ["iszero", "x"]]]),
    # !(x < MAX_UINT256) => x == MAX_UINT256
    (["iszero", ["lt", "x", 2**256 - 1]], ["iszero", ["iszero", ["iszero", ["not", "x"]]]]),
    # !(x < MAX_INT256) => x == MAX_INT256
    (
        ["iszero", ["slt", "x", 2**255 - 1]],
        ["iszero", ["iszero", ["iszero", ["xor", "x", 2**255 - 1]]]],
    ),
    # !(x > MIN_INT256) => x == MIN_INT256
    (
        ["iszero", ["sgt", "x", -(2**255)]],
        ["iszero", ["iszero", ["iszero", ["xor", "x", -(2**255)]]]],
    ),
    (["sgt", "x", 2**255 - 1], [0]),  # signed x > MAX_INT256 == False
    (["sge", "x", 2**255 - 1], ["eq", "x", 2**255 - 1]),
    (["eq", -1, "x"], ["iszero", ["not", "x"]]),
    (["iszero", ["eq", -1, "x"]], ["iszero", ["iszero", ["not", "x"]]]),
    (["le", "x", 0], ["iszero", "x"]),
    (["le", 0, "x"], [1]),
    (["le", 0, ["sload", 0]], None),  # no-op
    (["ge", "x", 0], [1]),
    (["le", "x", "x"], [1]),
    (["ge", "x", "x"], [1]),
    (["sle", "x", "x"], [1]),
    (["sge", "x", "x"], [1]),
    (["lt", "x", "x"], [0]),
    (["gt", "x", "x"], [0]),
    (["slt", "x", "x"], [0]),
    (["sgt", "x", "x"], [0]),
    # boundary conditions
    (["slt", "x", -(2**255)], [0]),
    (["sle", "x", -(2**255)], ["eq", "x", -(2**255)]),
    (["lt", "x", 2**256 - 1], None),
    (["le", "x", 2**256 - 1], [1]),
    (["gt", "x", 0], ["iszero", ["iszero", "x"]]),
    # x < 0 => false
    (["lt", "x", 0], [0]),
    # 0 < x => x != 0
    (["lt", 0, "x"], ["iszero", ["iszero", "x"]]),
    (["gt", 5, "x"], None),
    # x < 1 => x == 0
    (["lt", "x", 1], ["iszero", "x"]),
    (["slt", "x", 1], None),
    (["gt", "x", 1], None),
    (["sgt", "x", 1], None),
    (["gt", "x", 2**256 - 2], ["iszero", ["not", "x"]]),
    (["lt", "x", 2**256 - 2], None),
    (["slt", "x", 2**256 - 2], None),
    (["sgt", "x", 2**256 - 2], None),
    (["slt", "x", -(2**255) + 1], ["eq", "x", -(2**255)]),
    (["sgt", "x", -(2**255) + 1], None),
    (["lt", "x", -(2**255) + 1], None),
    (["gt", "x", -(2**255) + 1], None),
    (["sgt", "x", 2**255 - 2], ["eq", "x", 2**255 - 1]),
    (["slt", "x", 2**255 - 2], None),
    (["gt", "x", 2**255 - 2], None),
    (["lt", "x", 2**255 - 2], None),
    # 5 > x; x < 5; x <= 4
    (["iszero", ["gt", 5, "x"]], ["iszero", ["le", "x", 4]]),
    (["iszero", ["ge", 5, "x"]], None),
    # 5 >= x; x <= 5; x < 6
    (["ge", 5, "x"], ["lt", "x", 6]),
    (["lt", 5, "x"], None),
    # 5 < x; x > 5; x >= 6
    (["iszero", ["lt", 5, "x"]], ["iszero", ["ge", "x", 6]]),
    (["iszero", ["le", 5, "x"]], None),
    # 5 <= x; x >= 5; x > 4
    (["le", 5, "x"], ["gt", "x", 4]),
    (["sgt", 5, "x"], None),
    # 5 > x; x < 5; x <= 4
    (["iszero", ["sgt", 5, "x"]], ["iszero", ["sle", "x", 4]]),
    (["iszero", ["sge", 5, "x"]], None),
    # 5 >= x; x <= 5; x < 6
    (["sge", 5, "x"], ["slt", "x", 6]),
    (["slt", 5, "x"], None),
    # 5 < x; x > 5; x >= 6
    (["iszero", ["slt", 5, "x"]], ["iszero", ["sge", "x", 6]]),
    (["iszero", ["sle", 5, "x"]], None),
    # 5 <= x; x >= 5; x > 4
    (["sle", 5, "x"], ["sgt", "x", 4]),
    # tricky constant folds
    (["sgt", 2**256 - 1, 0], [0]),  # -1 > 0
    (["gt", 2**256 - 1, 0], [1]),  # -1 > 0
    (["gt", 2**255, 0], [1]),  # 0x80 > 0
    (["sgt", 2**255, 0], [0]),  # 0x80 > 0
    (["sgt", 2**255, 2**255 - 1], [0]),  # 0x80 > 0x81
    (["gt", -(2**255), 2**255 - 1], [1]),  # 0x80 > 0x81
    (["slt", 2**255, 2**255 - 1], [1]),  # 0x80 < 0x7f
    (["lt", -(2**255), 2**255 - 1], [0]),  # 0x80 < 0x7f
    (["sle", -1, 2**256 - 1], [1]),  # -1 <= -1
    (["sge", -(2**255), 2**255], [1]),  # 0x80 >= 0x80
    (["sgt", -(2**255), 2**255], [0]),  # 0x80 > 0x80
    (["slt", 2**255, -(2**255)], [0]),  # 0x80 < 0x80
    # arithmetic
    (["ceil32", "x"], None),
    (["ceil32", 0], [0]),
    (["ceil32", 1], [32]),
    (["ceil32", 32], [32]),
    (["ceil32", 33], [64]),
    (["ceil32", 95], [96]),
    (["ceil32", 96], [96]),
    (["ceil32", 97], [128]),
    (["add", "x", 0], ["x"]),
    (["add", 0, "x"], ["x"]),
    (["sub", "x", 0], ["x"]),
    (["sub", "x", "x"], [0]),
    (["sub", ["sload", 0], ["sload", 0]], None),
    (["sub", ["callvalue"], ["callvalue"]], None),
    (["sub", -1, ["sload", 0]], ["not", ["sload", 0]]),
    (["mul", "x", 1], ["x"]),
    (["div", "x", 1], ["x"]),
    (["sdiv", "x", 1], ["x"]),
    (["mod", "x", 1], [0]),
    (["mod", ["sload", 0], 1], None),
    (["smod", "x", 1], [0]),
    (["mul", "x", -1], ["sub", 0, "x"]),
    (["sdiv", "x", -1], ["sub", 0, "x"]),
    (["mul", "x", 0], [0]),
    (["mul", ["sload", 0], 0], None),
    (["div", "x", 0], [0]),
    (["div", ["sload", 0], 0], None),
    (["sdiv", "x", 0], [0]),
    (["sdiv", ["sload", 0], 0], None),
    (["mod", "x", 0], [0]),
    (["mod", ["sload", 0], 0], None),
    (["smod", "x", 0], [0]),
    (["mul", "x", 32], ["shl", 5, "x"]),
    (["div", "x", 64], ["shr", 6, "x"]),
    (["mod", "x", 128], ["and", "x", 127]),
    (["sdiv", "x", 64], None),
    (["smod", "x", 64], None),
    (["exp", 3, 5], [3**5]),
    (["exp", 3, 256], [(3**256) % (2**256)]),
    (["exp", 2, 257], [0]),
    (["exp", "x", 0], [1]),
    (["exp", "x", 1], ["x"]),
    (["exp", 1, "x"], [1]),
    (["exp", 0, "x"], ["iszero", "x"]),
    # bitwise ops
    (["xor", "x", 2**256 - 1], ["not", "x"]),
    (["and", "x", 2**256 - 1], ["x"]),
    (["or", "x", 2**256 - 1], [2**256 - 1]),
    (["shr", 0, "x"], ["x"]),
    (["sar", 0, "x"], ["x"]),
    (["shl", 0, "x"], ["x"]),
    (["shr", 256, "x"], None),
    (["sar", 256, "x"], None),
    (["shl", 256, "x"], None),
    (["and", 1, 2], [0]),
    (["or", 1, 2], [3]),
    (["xor", 1, 2], [3]),
    (["xor", 3, 2], [1]),
    (["and", 0, "x"], [0]),
    (["and", "x", 0], [0]),
    (["or", "x", 0], ["x"]),
    (["or", 0, "x"], ["x"]),
    (["xor", "x", 0], ["x"]),
    (["xor", "x", 1], None),
    (["and", "x", 1], None),
    (["or", "x", 1], None),
    (["xor", 0, "x"], ["x"]),
    (["xor", "x", "x"], [0]),
    (["iszero", ["or", "x", 1]], [0]),
    (["iszero", ["or", 2, "x"]], [0]),
    (["iszero", ["or", 1, ["sload", 0]]], None),
    # nested optimizations
    (["eq", 0, ["sub", 1, 1]], [1]),
    (["eq", 0, ["add", 2**255, 2**255]], [1]),  # test compile-time wrapping
    (["eq", 0, ["add", 2**255, -(2**255)]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", 0, -1]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", 2**255, 2**255 - 1]], [1]),  # test compile-time wrapping
    (["eq", -1, ["add", -(2**255), 2**255 - 1]], [1]),  # test compile-time wrapping
    (["eq", -2, ["add", 2**256 - 1, 2**256 - 1]], [1]),  # test compile-time wrapping
    (["eq", "x", "x"], [1]),
    (["eq", "callvalue", "callvalue"], None),
    (["ne", "x", "x"], [0]),
]


@pytest.mark.parametrize("ir", optimize_list)
def test_ir_optimizer(ir):
    optimized = optimizer.optimize(IRnode.from_list(ir[0]))
    optimized.repr_show_gas = True
    if ir[1] is None:
        # no-op, assert optimizer does nothing
        expected = IRnode.from_list(ir[0])
    else:
        expected = IRnode.from_list(ir[1])
    expected.repr_show_gas = True
    optimized.annotation = None
    assert optimized == expected


static_assertions_list = [
    ["assert", ["eq", 2, 1]],
    ["assert", ["ne", 1, 1]],
    ["assert", ["sub", 1, 1]],
    ["assert", ["lt", 2, 1]],
    ["assert", ["lt", 1, 1]],
    ["assert", ["lt", "x", 0]],  # +x < 0
    ["assert", ["le", 1, 0]],
    ["assert", ["le", 2**256 - 1, 0]],
    ["assert", ["gt", 1, 2]],
    ["assert", ["gt", 1, 1]],
    ["assert", ["gt", 0, 2**256 - 1]],
    ["assert", ["gt", "x", 2**256 - 1]],
    ["assert", ["ge", 1, 2]],
    ["assert", ["ge", 1, 2]],
    ["assert", ["slt", 2, 1]],
    ["assert", ["slt", 1, 1]],
    ["assert", ["slt", 0, 2**256 - 1]],  # 0 < -1
    ["assert", ["slt", -(2**255), 2**255]],  # 0x80 < 0x80
    ["assert", ["sle", 0, 2**255]],  # 0 < 0x80
    ["assert", ["sgt", 1, 2]],
    ["assert", ["sgt", 1, 1]],
    ["assert", ["sgt", 2**256 - 1, 0]],  # -1 > 0
    ["assert", ["sgt", 2**255, -(2**255)]],  # 0x80 > 0x80
    ["assert", ["sge", 2**255, 0]],  # 0x80 > 0
]


@pytest.mark.parametrize("ir", static_assertions_list)
def test_static_assertions(ir, assert_compile_failed):
    ir = IRnode.from_list(ir)
    assert_compile_failed(lambda: optimizer.optimize(ir), StaticAssertionException)


def test_operator_set_values():
    # some sanity checks
    assert optimizer.COMPARISON_OPS == {"lt", "gt", "le", "ge", "slt", "sgt", "sle", "sge"}
    assert optimizer.STRICT_COMPARISON_OPS == {"lt", "gt", "slt", "sgt"}
    assert optimizer.UNSTRICT_COMPARISON_OPS == {"le", "ge", "sle", "sge"}
