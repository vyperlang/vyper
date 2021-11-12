import pytest

from vyper.lll import compile_lll
from vyper.lll.s_expressions import parse_s_exp
from vyper.old_codegen.parser import LLLnode

fail_list = [
    [-(2 ** 255) - 3],
    [2 ** 256 + 3],
    ["set", "_poz"],
    [["set", "var_1", 0, 0]],
    ["with", "var_1", 0, ["set", 1, 1]],
    ["break"],  # invalid break
    ["continue"],  # invalid continue
    ["invalidllelement"],
]


@pytest.mark.parametrize("bad_lll", fail_list)
def test_lll_compile_fail(bad_lll, get_contract_from_lll, assert_compile_failed):
    assert_compile_failed(lambda: get_contract_from_lll(LLLnode.from_list(bad_lll)), Exception)


valid_list = [
    ["pass"],
    ["clamplt", ["mload", 0], 300],
    ["clampgt", ["mload", 0], -1],
    ["uclampgt", 1, ["mload", 0]],
    ["uclampge", ["mload", 0], 0],
]


@pytest.mark.parametrize("good_lll", valid_list)
def test_compile_lll_good(good_lll, get_contract_from_lll):
    get_contract_from_lll(LLLnode.from_list(good_lll))


def test_lll_from_s_expression(get_contract_from_lll):
    code = """
(seq
  (return
    0
    (lll ; just return 32 byte of calldata back
      0
      (seq
          (calldatacopy 0 4 32)
          (return 0 32)
          stop
        )
      )))
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
    lll = LLLnode.from_list(s_expressions[0])
    c = get_contract_from_lll(lll, abi=abi)
    assert c.test(-123456) == -123456


def test_pc_debugger():
    debugger_lll = ["seq", ["mstore", 0, 32], ["pc_debugger"]]
    lll_nodes = LLLnode.from_list(debugger_lll)
    _, line_number_map = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll_nodes))
    assert line_number_map["pc_breakpoints"][0] == 5
