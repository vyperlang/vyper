import pytest

from vyper.compiler import compile_code


@pytest.mark.parametrize("type", ["DynArray[NestedStruct, 2]", "NestedStruct[2]"])
def test_nested_struct(type):
    code = f"""
struct MyStruct:
    a: address
    b: bytes32

struct NestedStruct:
    t: MyStruct
    foo: uint256

@view
@external
def getStructList() -> {type}:
    return [
        NestedStruct({{t: MyStruct({{a: msg.sender, b: block.prevhash}}), foo: 1}}),
        NestedStruct({{t: MyStruct({{a: msg.sender, b: block.prevhash}}), foo: 2}})
    ]
    """

    out = compile_code(
        code,
        output_formats=["abi"],
    )

    assert out["abi"] == [
        {
            "inputs": [],
            "name": "getStructList",
            "outputs": [
                {
                    "components": [
                        {
                            "components": [
                                {
                                    "name": "a",
                                    "type": "address"
                                },
                                {
                                    "name": "b",
                                    "type": "bytes32"
                                }
                            ],
                            "name": "t",
                            "type": "tuple"
                        },
                        {
                            "name": "foo",
                            "type": "uint256"
                        }
                    ],
                    "name": "",
                    "type": "tuple[]"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]
