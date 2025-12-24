from dataclasses import dataclass

import pytest

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import VenomOptimizationFlags
from vyper.venom import run_passes_on
from vyper.venom.ir_node_to_venom import ir_node_to_venom


def test_simple():
    ir = IRnode.from_list(["calldatacopy", 32, 0, ["calldatasize"]])
    ir_node = IRnode.from_list(ir)
    venom = ir_node_to_venom(ir_node)
    assert venom is not None

    fn = list(venom.functions.values())[0]

    bb = fn.entry
    assert bb.instructions[0].opcode == "calldatasize"
    assert bb.instructions[1].opcode == "calldatacopy"


def test_simple_2():
    ir = [
        "seq",
        [
            "seq",
            [
                "mstore",
                ["add", 64, 0],
                [
                    "with",
                    "x",
                    ["calldataload", ["add", 4, 0]],
                    [
                        "with",
                        "ans",
                        ["add", "x", 1],
                        ["seq", ["assert", ["ge", "ans", "x"]], "ans"],
                    ],
                ],
            ],
        ],
        32,
    ]
    ir_node = IRnode.from_list(ir)
    venom = ir_node_to_venom(ir_node)
    assert venom is not None


@dataclass
class _DummyAlloca:
    _id: int
    size: int


@pytest.mark.xfail
def test_sha3_64():
    """
    Test that was introduced because regression in the
    PR https://github.com/vyperlang/vyper/pull/4795
    it is caused by desugaring the sha3_64 early
    and the optimizer cannot combine the these two
    sha3_64 instruction into one

    This test should pass in the commits before that
    and we should try to make it pass again
    """

    ir = [
        "seq",
        ["mstore", "$alloca_64_32", ["calldataload", 32]],
        ["mstore", "$alloca_96_32", ["sload", ["sha3_64", 0, ["mload", "$alloca_64_32"]]]],
        [
            "seq",
            [
                "seq",
                ["unique_symbol", "sstore_1"],
                ["sstore", ["sha3_64", 0, ["mload", "$alloca_64_32"]], 0],
            ],
        ],
        ["sink", ["mload", "$alloca_96_32"]],
    ]

    ir_node = IRnode.from_list(ir)
    alloca0 = ir_node.args[0].args[0]
    assert isinstance(alloca0.value, str)
    assert "alloca" in alloca0.value, alloca0
    alloca0.passthrough_metadata["alloca"] = _DummyAlloca(_id=2, size=32)

    alloca1 = ir_node.args[1].args[0]
    assert isinstance(alloca1.value, str)
    assert "alloca" in alloca1.value, alloca1
    alloca1.passthrough_metadata["alloca"] = _DummyAlloca(_id=1, size=32)

    alloca2 = ir_node.args[1].args[1].args[0].args[1].args[0]
    assert isinstance(alloca2.value, str)
    assert "alloca" in alloca2.value, alloca2
    alloca2.passthrough_metadata["alloca"] = _DummyAlloca(_id=2, size=32)

    alloca3 = ir_node.args[2].args[0].args[1].args[0].args[1].args[0]
    assert isinstance(alloca3.value, str)
    assert "alloca" in alloca3.value, alloca3
    alloca3.passthrough_metadata["alloca"] = _DummyAlloca(_id=2, size=32)

    alloca4 = ir_node.args[3].args[0].args[0]
    assert isinstance(alloca4.value, str)
    assert "alloca" in alloca4.value, alloca4
    alloca4.passthrough_metadata["alloca"] = _DummyAlloca(_id=1, size=32)

    venom = ir_node_to_venom(ir_node)
    flags = VenomOptimizationFlags()
    run_passes_on(venom, flags)
    print(venom)
    fn = next(venom.functions.values().__iter__())
    bb = next(fn.get_basic_blocks())
    print(bb)
    assert len([inst for inst in bb.instructions if "sha" in inst.opcode]) == 1
