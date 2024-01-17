from vyper.codegen.ir_node import IRnode
from vyper.venom.ir_node_to_venom import ir_node_to_venom


def test_simple():
    ir = IRnode.from_list(["calldatacopy", 32, 0, ["calldatasize"]])
    ir_node = IRnode.from_list(ir)
    venom = ir_node_to_venom(ir_node)
    assert venom is not None

    bb = venom.basic_blocks[0]
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
