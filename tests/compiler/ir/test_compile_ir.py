import pytest

from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir
from vyper.ir.s_expressions import parse_s_exp

fail_list = [
    [-(2**255) - 3],
    [2**256 + 3],
    ["set", "_poz"],
    [["set", "var_1", 0, 0]],
    ["with", "var_1", 0, ["set", 1, 1]],
    ["break"],  # invalid break
    ["continue"],  # invalid continue
    ["invalidllelement"],
]


@pytest.mark.parametrize("bad_ir", fail_list)
def test_ir_compile_fail(bad_ir, get_contract_from_ir, assert_compile_failed):
    assert_compile_failed(lambda: get_contract_from_ir(IRnode.from_list(bad_ir)), Exception)


valid_list = [
    ["pass"],
    ["assert", ["slt", ["mload", 0], 300]],
    ["assert", ["sgt", ["mload", 0], -1]],
    ["assert", ["gt", 1, ["mload", 0]]],
    ["assert", ["ge", ["mload", 0], 0]],
]


@pytest.mark.parametrize("good_ir", valid_list)
def test_compile_ir_good(good_ir, get_contract_from_ir):
    get_contract_from_ir(IRnode.from_list(good_ir))


def test_ir_from_s_expression(get_contract_from_ir):
    code = """
(seq
  (deploy
    0
    (seq ; just return 32 byte of calldata back
      (calldatacopy 0 4 32)
      (return 0 32)
      stop
     )
    0))
    """
    abi = [
        {
            "name": "test",
            "outputs": [{"type": "int128", "name": "out"}],
            "inputs": [{"type": "int128", "name": "a"}],
            "stateMutability": "nonpayable",
            "type": "function",
            "gas": 394,
        }
    ]

    s_expressions = parse_s_exp(code)
    ir = IRnode.from_list(s_expressions[0])
    c = get_contract_from_ir(ir, abi=abi)
    assert c.test(-123456) == -123456


def test_pc_debugger():
    debugger_ir = ["seq", ["mstore", 0, 32], ["pc_debugger"]]
    ir_nodes = IRnode.from_list(debugger_ir)
    _, line_number_map = compile_ir.assembly_to_evm(compile_ir.compile_to_assembly(ir_nodes))
    assert line_number_map["pc_breakpoints"][0] == 4
